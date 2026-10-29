"""Speed ramp, protection and balance-run sequencing. Runs in its own thread at 20 Hz.

Modes:
  idle   motor released (0 A)
  run    rpm_cmd ramps toward rpm_target at ramp_rate_rpm_s (down at decel_rpm_s); ramp can be paused
  stop   rpm_cmd ramps down at decel_rpm_s, then the rotor is released and coasts to idle
  trip   a limit was exceeded: trip_action (soft) or trip_hard_action (hard) is applied;
         stays in trip until reset, which is only accepted once the rotor is below rpm_release
"""
import math, time, threading, os, csv, collections
import numpy as np
from . import analysis as A
from . import balance as B

HIST_HZ = 4.0


class Controller:
    def __init__(self, cfg, vesc, imu_buf, opr_buf, opr_enabled, sim=None):
        self.cfg = cfg
        self.vesc = vesc
        self.imu = imu_buf
        self.opr = opr_buf
        self.opr_enabled = opr_enabled
        self.sim = sim
        self.lock = threading.RLock()
        self.mode = 'idle'
        self.rpm_target = 0.0
        self.rpm_cmd = 0.0
        self.paused = False
        self.pause_reason = ''
        self.trip_reason = ''
        self.trip_kind = ''
        self.trip_t = 0.0
        self.events = collections.deque(maxlen=200)
        self.hist = collections.deque(maxlen=int(600 * HIST_HZ))   # 10 min
        self.last = {}            # latest analysis
        self.spec = None
        self.ns_growth = A.Growth(1.5)
        self.slope = A.SlopeVsRpm(150.0)
        self.track_err_since = None
        self.oc_since = None
        self.run_t0 = 0.0
        self.slope_override = False
        self.clients = 0
        self.no_client_since = time.monotonic()
        self.balance = B.Store(os.path.join(os.path.dirname(cfg.path) or '.', 'balance.json'))
        self.bal = dict(state='idle', label='', msg='', t0=0.0)
        self.log = None
        self.running = True
        self.t_an = 0.0
        self.th = threading.Thread(target=self._run, daemon=True, name='ctl')

    # ------------------------------------------------------------------ commands
    def ev(self, msg):
        self.events.append((time.time(), msg))

    def start_run(self, rpm_target, ramp_rate=None):
        with self.lock:
            if self.mode == 'trip':
                return 'tripped: reset first'
            rpm_target = max(0.0, min(float(rpm_target), self.cfg['rpm_max']))
            if ramp_rate is not None:
                self.cfg.set('ramp_rate_rpm_s', ramp_rate)
            if self.mode in ('idle', 'stop'):
                rpm_now = self.rpm_meas()
                self.rpm_cmd = max(self.cfg['rpm_start'], rpm_now)
                self.run_t0 = time.monotonic()
                self.slope.reset()
                self._open_log()
            self.rpm_target = rpm_target
            self.mode = 'run'
            self.paused = False
            self.slope_override = False
            self.pause_reason = ''
            self.ev('run to %.0f rpm at %.0f rpm/s' % (rpm_target, self.cfg['ramp_rate_rpm_s']))
            return 'ok'

    def hold(self):
        with self.lock:
            if self.mode == 'run':
                self.rpm_target = self.rpm_cmd
                self.ev('hold at %.0f rpm' % self.rpm_cmd)
            return 'ok'

    def resume(self):
        with self.lock:
            if self.mode == 'run' and self.paused:
                self.paused = False
                self.slope_override = True
                self.slope.reset()
                if self.last:
                    self.last['slope_n'] = 0.0
                self.ev('ramp resumed; resonance pause disabled until the next Run')
            return 'ok'

    def stop(self):
        with self.lock:
            if self.mode in ('run',):
                self.mode = 'stop'
                self.ev('stop')
            self.bal_abort('stopped')
            return 'ok'

    def estop(self):
        self.trip('E-STOP from UI', hard=True)
        return 'ok'

    def reset(self):
        with self.lock:
            if self.mode != 'trip':
                return 'ok'
            if self.rpm_meas() > self.cfg['rpm_release']:
                return 'rotor still at %.0f rpm; wait until below rpm_release' % self.rpm_meas()
            self.mode = 'idle'
            self.trip_reason = ''
            self.trip_kind = ''
            self.ev('trip reset')
            return 'ok'

    def trip(self, reason, hard=False):
        with self.lock:
            if self.mode == 'trip' and (self.trip_kind == 'hard' or not hard):
                return
            self.mode = 'trip'
            self.trip_kind = 'hard' if hard else 'soft'
            self.trip_reason = reason
            self.trip_t = time.time()
            self.paused = False
            self.ev('TRIP (%s): %s' % (self.trip_kind, reason))
            self.bal_abort('trip: ' + reason)

    # ------------------------------------------------------------------ measurements
    def rpm_vesc(self):
        v = self.vesc.values
        if not v:
            return 0.0
        return abs(v['erpm']) / self.cfg['motor_pole_pairs'] / self.cfg['belt_ratio']

    def rpm_meas(self):
        if self.opr_enabled:
            last = self.opr.last()
            if last is not None and time.monotonic() - last < 1.0:
                return self.opr.rpm(2)
        return self.rpm_vesc()

    def axis(self):
        return 'xyz'.index(self.cfg['imu_axis'].lower()[0])

    def analyse(self, now):
        t, acc = self.imu.window(self.cfg['analysis_window_s'])
        if len(t) < 200:
            return
        x = acc[:, self.axis()].astype(np.float64)
        rpm = self.rpm_meas()
        pulses = self.opr.since(t[0]) if self.opr_enabled else None
        o = A.one_x(t, x, rpm / 60.0, pulses)
        s = A.spectrum(t, x, o['f_hz'])
        if s is None:
            return
        self.ns_growth.add(now, s['ns_g'])
        rate = self.ns_growth.rate()
        if self.mode == 'run' and not self.paused and self.rpm_cmd < self.rpm_target - 1:
            self.slope.add(rpm, o['amp_g'])
        self.last = dict(a1x_g=o['amp_g'], a1x_deg=o['phase_deg'], f1_hz=o['f_hz'], rms_g=s['rms_g'],
                         ns_g=s['ns_g'], ns_hz=s['ns_hz'], ns_rate=rate,
                         ns_tau_s=(1.0 / rate) if rate > 1e-3 else None,
                         slope_n=self.slope.exponent(), t=now)
        self.spec = dict(f=s['f'], a=s['a'], f1=o['f_hz'])

    # ------------------------------------------------------------------ protection
    def check(self, now):
        c = self.cfg
        v = self.vesc.values
        spinning = self.mode in ('run', 'stop') or self.rpm_meas() > c['rpm_release']
        if not spinning:
            self.track_err_since = None
            return
        # stale data
        if now - self.vesc.values_t > c['sensor_timeout_s']:
            return self.trip('VESC telemetry lost (%.1f s)' % (now - self.vesc.values_t), hard=True)
        if now - self.imu.last_t > c['sensor_timeout_s']:
            return self.trip('accelerometer data lost (%.1f s)' % (now - self.imu.last_t))
        if v and v['fault']:
            return self.trip('VESC fault %s' % v['fault_name'], hard=True)
        L = self.last
        if L and now - L['t'] < 1.0:
            if L['rms_g'] > c['vib_hard_limit_g']:
                return self.trip('vibration RMS %.2f g > vib_hard_limit_g' % L['rms_g'], hard=True)
            if L['rms_g'] > c['vib_rms_limit_g']:
                return self.trip('vibration RMS %.2f g > vib_rms_limit_g' % L['rms_g'])
            if L['a1x_g'] > c['vib_1x_limit_g']:
                return self.trip('1x vibration %.2f g > vib_1x_limit_g' % L['a1x_g'])
            if L['ns_g'] > c['vib_nonsync_limit_g']:
                return self.trip('non-synchronous %.2f g at %.1f Hz > vib_nonsync_limit_g' % (L['ns_g'], L['ns_hz']))
            tau = L['ns_tau_s']
            if tau is not None and tau < c['vib_growth_limit_s'] and L['ns_g'] > 0.25 * c['vib_nonsync_limit_g']:
                return self.trip('non-synchronous vibration growing (x e in %.2f s) at %.1f Hz' % (tau, L['ns_hz']))
            if (self.mode == 'run' and not self.paused and not self.slope_override
                    and L['slope_n'] > c['vib_1x_slope_limit']
                    and L['a1x_g'] > 0.3 * c['vib_1x_limit_g']):
                self.paused = True
                self.rpm_target = self.rpm_cmd
                self.pause_reason = ('1x rising as rpm^%.1f (> vib_1x_slope_limit): resonance ahead. '
                                     'Resume to continue or Stop.' % L['slope_n'])
                self.ev('ramp paused: ' + self.pause_reason)
        if v:
            if abs(v['motor_current_a']) > c['motor_current_limit_a']:
                self.oc_since = self.oc_since or now
                if now - self.oc_since > 0.5:
                    return self.trip('motor current %.1f A > motor_current_limit_a for 0.5 s' % v['motor_current_a'])
            else:
                self.oc_since = None
            if v['temp_fet_c'] > c['temp_fet_limit_c']:
                return self.trip('FET temp %.0f C > temp_fet_limit_c' % v['temp_fet_c'])
            if v['temp_motor_c'] > c['temp_motor_limit_c']:
                return self.trip('motor temp %.0f C > temp_motor_limit_c' % v['temp_motor_c'])
        if self.mode == 'run' and self.rpm_cmd > c['rpm_start'] * 1.5:
            err = abs(self.rpm_meas() - self.rpm_cmd) / self.rpm_cmd * 100
            if err > c['rpm_track_err_pct']:
                self.track_err_since = self.track_err_since or now
                if now - self.track_err_since > c['rpm_track_time_s']:
                    return self.trip('rpm %.0f vs command %.0f (%.0f %% > rpm_track_err_pct)'
                                     % (self.rpm_meas(), self.rpm_cmd, err))
            else:
                self.track_err_since = None
        if self.opr_enabled and self.mode == 'run' and self.rpm_vesc() > 200:
            last = self.opr.last_index()
            limit = max(c['opr_timeout_revs'] * 60.0 / self.rpm_vesc(), 0.2)
            ref = last if (last is not None and last > self.run_t0) else self.run_t0 + 2.0
            if now - ref > limit:
                return self.trip('once-per-rev pulses missing (check sensor gap and opr_edge)')
        if c['ui_deadman_s'] > 0 and self.mode == 'run' and self.clients == 0 \
                and now - self.no_client_since > c['ui_deadman_s']:
            return self.trip('no browser connected for %.0f s (ui_deadman_s)' % c['ui_deadman_s'])

    # ------------------------------------------------------------------ output
    def drive(self, dt):
        c = self.cfg
        pp, ratio = c['motor_pole_pairs'], c['belt_ratio']
        if self.mode == 'run':
            if not self.paused:
                if self.rpm_cmd < self.rpm_target:
                    self.rpm_cmd = min(self.rpm_target, self.rpm_cmd + c['ramp_rate_rpm_s'] * dt)
                elif self.rpm_cmd > self.rpm_target:
                    self.rpm_cmd = max(self.rpm_target, self.rpm_cmd - c['decel_rpm_s'] * dt)
            if self.rpm_target < c['rpm_release'] and self.rpm_cmd <= c['rpm_release']:
                self.mode = 'stop'
            else:
                self.vesc.set_command('rpm', self.rpm_cmd * ratio * pp)
                return
        if self.mode == 'stop' or (self.mode == 'trip' and self.trip_kind == 'soft' and c['trip_action'] == 'ramp_down'):
            self.rpm_cmd = max(c['rpm_release'], min(self.rpm_cmd, self.rpm_meas() + 50) - c['decel_rpm_s'] * dt)
            if self.rpm_cmd > c['rpm_release'] or self.rpm_meas() > c['rpm_release'] * 1.2:
                self.vesc.set_command('rpm', self.rpm_cmd * ratio * pp)
            else:
                self.vesc.set_command('current', 0.0)
                if self.mode == 'stop' and self.rpm_meas() < 30:
                    self.mode = 'idle'
                    self.ev('idle')
                    self._close_log()
            return
        if self.mode == 'trip':
            action = c['trip_hard_action'] if self.trip_kind == 'hard' else c['trip_action']
            self.rpm_cmd = 0.0
            if action == 'brake' and self.rpm_meas() > c['rpm_release']:
                self.vesc.set_command('brake', c['brake_current_a'])
            else:
                self.vesc.set_command('current', 0.0)
            if self.rpm_meas() < 30:
                self._close_log()
            return
        self.rpm_cmd = 0.0
        self.vesc.set_command('current', 0.0)

    # ------------------------------------------------------------------ balance runs
    def bal_start(self, label):
        with self.lock:
            if self.mode == 'trip':
                return 'tripped: reset first'
            if self.bal['state'] != 'idle':
                return 'a balance run is already in progress'
            self.bal = dict(state='spinup', label=label, msg='spinning up to %.0f rpm' % self.cfg['balance_rpm'],
                            t0=time.monotonic())
            r = self.start_run(self.cfg['balance_rpm'])
            self.ev('balance run "%s"' % label)
            return r

    def bal_abort(self, why):
        if self.bal['state'] != 'idle':
            self.ev('balance run "%s" aborted: %s' % (self.bal['label'], why))
            self.bal = dict(state='idle', label='', msg='aborted: ' + why, t0=0.0)

    def bal_step(self, now):
        b, c = self.bal, self.cfg
        if b['state'] == 'idle':
            return
        rpm = self.rpm_meas()
        if b['state'] == 'spinup':
            if self.mode == 'run' and abs(rpm - c['balance_rpm']) < 0.02 * c['balance_rpm'] \
                    and self.rpm_cmd >= c['balance_rpm'] - 1:
                b.update(state='settle', t0=now, msg='settling %.0f s' % c['balance_settle_s'])
        elif b['state'] == 'settle':
            if now - b['t0'] > c['balance_settle_s']:
                b.update(state='measure', t0=now, msg='averaging %.0f s' % c['balance_avg_s'])
        elif b['state'] == 'measure':
            left = c['balance_avg_s'] - (now - b['t0'])
            b['msg'] = 'averaging, %.0f s left' % max(0, left)
            if left <= 0:
                self._bal_record(now)
                b.update(state='idle', msg='run "%s" recorded; stopping so you can fit masses' % b['label'])
                self.stop()

    def _bal_record(self, now):
        c = self.cfg
        t, acc = self.imu.window(c['balance_avg_s'])
        x = acc[:, self.axis()].astype(np.float64)
        pulses = self.opr.since(t[0]) if self.opr_enabled else None
        o = A.one_x(t, x, self.rpm_meas() / 60.0, pulses)
        run = dict(amp_g=o['amp_g'], phase_deg=o['phase_deg'], rpm=o['f_hz'] * 60, n_revs=o['n_revs'],
                   time=time.time(), masses=list(self.bal_masses()))
        self.balance.d['runs'][self.bal['label']] = run
        self.balance.save()
        self.ev('balance "%s": 1x %.3f g%s at %.0f rpm' % (
            self.bal['label'], o['amp_g'], '' if o['phase_deg'] is None else ' @ %.0f deg' % o['phase_deg'],
            o['f_hz'] * 60))

    def bal_masses(self):
        return self.balance.d.get('fitted', [])

    def bal_fit(self, grams, deg, remove=False):
        """Record that a mass was fitted (or removed). The simulator applies it to its rotor."""
        with self.lock:
            m = self.balance.d.setdefault('fitted', [])
            if remove:
                for i, (g, a) in enumerate(m):
                    if abs(g - grams) < 1e-6 and abs(a - deg) < 1e-6:
                        del m[i]
                        break
                if self.sim:
                    self.sim.remove_mass(grams, deg, self.cfg['balance_radius_mm'])
            else:
                m.append([grams, deg])
                if self.sim:
                    self.sim.fit_mass(grams, deg, self.cfg['balance_radius_mm'])
            self.balance.save()
            self.ev('%s %.2f g at %.0f deg' % ('removed' if remove else 'fitted', grams, deg))
            return 'ok'

    def bal_clear(self):
        with self.lock:
            self.balance.d['runs'] = {}
            self.balance.d['fitted'] = []
            self.balance.save()
            return 'ok'

    def bal_compute(self, trial_g, trial_deg):
        runs = self.balance.d['runs']
        c = self.cfg
        pos = [float(p) for p in c['balance_positions_deg'].replace(' ', '').split(',') if p]
        out = {}
        if 'baseline' not in runs:
            return dict(error='no baseline run')
        b0 = runs['baseline']
        if b0['phase_deg'] is not None and 'trial' in runs and runs['trial']['phase_deg'] is not None:
            V0 = B.pol(b0['amp_g'], b0['phase_deg'])
            V1 = B.pol(runs['trial']['amp_g'], runs['trial']['phase_deg'])
            r = B.vector_method(V0, V1, trial_g, trial_deg)
            self.balance.set_H(r['H'], b0['rpm'], c['balance_radius_mm'])
            self.balance.save()
            out = dict(method='vector (once-per-rev)', correction_g=r['correction'][0], correction_deg=r['correction'][1],
                       with_trial_left_g=r['with_trial_left'][0], with_trial_left_deg=r['with_trial_left'][1],
                       trial_effect_pct=r['trial_effect_pct'],
                       g_per_gram=abs(r['H']))
        elif all(k in runs for k in ('trial_a', 'trial_b', 'trial_c')):
            angs = [trial_deg, trial_deg + 120, trial_deg + 240]
            r = B.four_run(b0['amp_g'], [runs[k]['amp_g'] for k in ('trial_a', 'trial_b', 'trial_c')], trial_g, angs)
            out = dict(method='4-run (amplitude only)', correction_g=r['correction'][0],
                       correction_deg=r['correction'][1], g_per_gram=r['g_per_gram'], fit_resid=r['fit_resid_g2'])
        else:
            return dict(error='need runs: baseline + trial (with once-per-rev), or baseline + trial_a/b/c')
        if pos:
            out['split'] = B.split(out['correction_g'], out['correction_deg'], pos)
        out['radius_mm'] = c['balance_radius_mm']
        return out

    def bal_trim(self):
        """One-shot correction from the latest 'check' run and the saved influence coefficient."""
        H = self.balance.H
        run = self.balance.d['runs'].get('check')
        if H is None or not run or run['phase_deg'] is None:
            return dict(error='need a saved influence coefficient and a "check" run with once-per-rev')
        g, deg = B.trim(B.pol(run['amp_g'], run['phase_deg']), H)
        return dict(method='trim (saved influence coefficient)', correction_g=g, correction_deg=deg,
                    radius_mm=self.balance.d.get('H_radius_mm'))

    # ------------------------------------------------------------------ logging
    def _open_log(self):
        self._close_log()
        d = os.path.expanduser(self.cfg['log_dir'])
        os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, time.strftime('run_%Y%m%d_%H%M%S.csv'))
        f = open(fn, 'w', newline='')
        w = csv.writer(f)
        w.writerow(['t_s', 'mode', 'rpm_target', 'rpm_cmd', 'rpm', 'a1x_g', 'a1x_deg', 'rms_g', 'ns_g', 'ns_hz',
                    'ns_tau_s', 'slope_n', 'motor_current_a', 'input_current_a', 'v_in', 'temp_fet_c',
                    'temp_motor_c', 'fault', 'event'])
        self.log = (f, w, time.monotonic(), fn)
        self.ev('log ' + fn)

    def _close_log(self):
        if self.log:
            self.log[0].close()
            self.log = None

    # ------------------------------------------------------------------ main loop
    def snapshot(self):
        v = self.vesc.values or {}
        L = self.last
        now = time.monotonic()
        return dict(
            mode=self.mode, paused=self.paused, pause_reason=self.pause_reason,
            trip_kind=self.trip_kind, trip_reason=self.trip_reason,
            rpm_target=round(self.rpm_target, 1), rpm_cmd=round(self.rpm_cmd, 1),
            rpm=round(self.rpm_meas(), 1), rpm_vesc=round(self.rpm_vesc(), 1),
            opr=self.opr_enabled, opr_rpm=round(self.opr.rpm(), 1) if self.opr_enabled else None,
            opr_age_s=round(now - self.opr.last(), 2) if (self.opr_enabled and self.opr.last()) else None,
            opr_pattern_errors=self.opr.pattern_errors if self.opr_enabled else None,
            a1x_g=L.get('a1x_g'), a1x_deg=L.get('a1x_deg'), rms_g=L.get('rms_g'), ns_g=L.get('ns_g'),
            ns_hz=L.get('ns_hz'), ns_tau_s=L.get('ns_tau_s'), slope_n=L.get('slope_n'),
            motor_current_a=v.get('motor_current_a'), input_current_a=v.get('input_current_a'),
            v_in=v.get('v_in'), temp_fet_c=v.get('temp_fet_c'), temp_motor_c=v.get('temp_motor_c'),
            fault=v.get('fault_name'), duty=v.get('duty'),
            vesc_age_s=round(now - self.vesc.values_t, 2) if self.vesc.values_t else None,
            vesc_errors=self.vesc.errors, imu_rate_hz=round(self.imu.rate, 1),
            imu_age_s=round(now - self.imu.last_t, 2) if self.imu.last_t else None,
            balance=dict(state=self.bal['state'], label=self.bal['label'], msg=self.bal['msg'],
                         runs=self.balance.d['runs'], fitted=self.bal_masses(),
                         have_H=self.balance.H is not None),
            log=self.log[3] if self.log else None,
            sim=self.sim is not None,
        )

    def _run(self):
        dt = 0.05
        nxt = time.monotonic()
        t_hist = 0.0
        while self.running:
            now = time.monotonic()
            with self.lock:
                if now - self.t_an >= 1.0 / HIST_HZ:
                    self.t_an = now
                    try:
                        self.analyse(now)
                    except Exception as e:
                        self.ev('analysis error: %r' % e)
                self.check(now)
                self.bal_step(now)
                self.drive(dt)
                if now - t_hist >= 1.0 / HIST_HZ:
                    t_hist = now
                    s = self.snapshot()
                    h = dict(t=time.time(), **{k: s[k] for k in (
                        'mode', 'rpm_target', 'rpm_cmd', 'rpm', 'a1x_g', 'a1x_deg', 'rms_g', 'ns_g', 'ns_hz',
                        'motor_current_a', 'v_in')})
                    self.hist.append(h)
                    if self.log:
                        f, w, t0, _ = self.log
                        ev = self.events[-1][1] if self.events and self.events[-1][0] > time.time() - 1 / HIST_HZ else ''
                        w.writerow(['%.2f' % (now - t0), s['mode'], s['rpm_target'], s['rpm_cmd'], s['rpm'],
                                    _f(s['a1x_g']), _f(s['a1x_deg'], 1), _f(s['rms_g']), _f(s['ns_g']), _f(s['ns_hz'], 2),
                                    _f(s['ns_tau_s'], 2), _f(s['slope_n'], 2), _f(s['motor_current_a'], 2),
                                    _f(s['input_current_a'], 2), _f(s['v_in'], 1), _f(s['temp_fet_c'], 1),
                                    _f(s['temp_motor_c'], 1), s['fault'], ev])
                        f.flush()
            nxt += dt
            d = nxt - time.monotonic()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.monotonic()

    def start(self):
        self.th.start()


def _f(v, n=4):
    return '' if v is None else ('%.' + str(n) + 'f') % v
