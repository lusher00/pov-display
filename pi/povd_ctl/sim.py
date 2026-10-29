"""Bench simulator: rotor + soft mount + VESC + MPU-6050 + once-per-rev sensor.

The VESC side speaks the real UART protocol through a fake serial port, so the driver code is exercised.
Model (single measured axis):
  - rotor speed follows the commanded rpm with an acceleration limit; coasts on aero drag at 0 A
  - unbalance U (g*mm, complex) -> force U*w^2 at once-per-rev into a mount with a 4 Hz rigid-body
    mode and a 27.5 Hz structural mode (shows up near 1650 rpm)
  - an unstable non-synchronous mode at 0.62 x rotor frequency between 1700 and 1850 rpm
    (ground-resonance-like); grows at +0.9 /s inside the band, decays at -3 /s outside
  - sensor noise ~9 mg RMS
"""
import math, struct, threading, time, random
import numpy as np
from . import vesc as V


class SimRotor:
    def __init__(self, cfg, imu_buf, opr_buf):
        self.cfg = cfg
        self.imu = imu_buf
        self.opr = opr_buf
        self.lock = threading.Lock()
        self.omega = 0.0          # rotor rad/s
        self.theta = 0.0          # rotor angle rad (0 = once-per-rev mark)
        self.cmd = ('current', 0.0)
        self.unbalance = 120.0 * np.exp(1j * math.radians(70))   # g*mm at 70 deg
        self.masses = []          # fitted (g, deg, radius_mm)
        self.ns_amp = 0.002       # g, non-synchronous mode amplitude
        self.ns_phase = 0.0
        self.temp_fet = 30.0
        self.temp_motor = 30.0
        self.tacho = 0
        self.current = 0.0
        self.running = True
        self.t_last = time.monotonic()
        self.samp_carry = 0.0
        self.th = threading.Thread(target=self._run, daemon=True, name='sim')

    # ---- balancing hooks (the UI tells the sim what mass you "fitted") ----
    def fit_mass(self, grams, angle_deg, radius_mm):
        with self.lock:
            self.masses.append((grams, angle_deg, radius_mm))

    def remove_mass(self, grams, angle_deg, radius_mm):
        with self.lock:
            for i, m in enumerate(self.masses):
                if abs(m[0] - grams) < 1e-6 and abs(m[1] - angle_deg) < 1e-6:
                    del self.masses[i]
                    return

    def total_unbalance(self):
        u = self.unbalance
        for g, a, r in self.masses:
            u = u + g * r * np.exp(1j * math.radians(a))
        return u

    def start(self):
        self.th.start()

    def _run(self):
        rng = np.random.default_rng(1)
        while self.running:
            time.sleep(0.01)
            now = time.monotonic()
            dt = now - self.t_last
            self.t_last = now
            with self.lock:
                self._step(dt, now, rng)

    def _step(self, dt, now, rng):
        cfg = self.cfg
        kind, val = self.cmd
        pp, ratio = cfg['motor_pole_pairs'], cfg['belt_ratio']
        drag = 2.0e-5 * self.omega ** 2 + 1.0           # rad/s^2
        if kind == 'rpm':
            target = val / pp / ratio * 2 * math.pi / 60
            err = target - self.omega
            acc = max(-60.0, min(60.0, 12.0 * err))
            self.current = 2.0 + abs(acc) * 0.25 + drag * 2.5
        elif kind == 'brake':
            acc = -drag - val * 3.0 if self.omega > 0 else 0
            self.current = -val
        else:
            acc = -drag if self.omega > 0 else 0
            self.current = 0.0
        self.omega = max(0.0, self.omega + acc * dt)
        self.temp_fet += (30 + abs(self.current) * 1.2 - self.temp_fet) * dt / 60
        self.temp_motor += (30 + abs(self.current) * 1.5 - self.temp_motor) * dt / 120

        # ---- accelerometer samples ----
        self.samp_carry += dt * 1000.0 * 1.012         # MPU clock 1.2 % fast
        k = int(self.samp_carry)
        self.samp_carry -= k
        if k <= 0:
            return
        ts = now - dt + (np.arange(k) + 1) * dt / k
        w = self.omega
        f = w / 2 / math.pi
        U = self.total_unbalance() * 1e-6               # kg*m
        F = U * w * w                                   # N (complex amplitude)
        M = 4.0
        def mode(fn, z, m):
            wn = 2 * math.pi * fn
            return 1.0 / (m * (wn * wn - w * w + 2j * z * wn * w))
        X = F * (mode(4.0, 0.08, M) + mode(27.5, 0.05, 20.0))
        A1 = -w * w * X / 9.81                          # g, complex, phase vs rotor angle
        th = self.theta + w * (ts - (now - dt))
        x = (A1 * np.exp(1j * th)).real
        x += 0.03 * (abs(A1) + 0.01) * np.cos(2 * th + 1.0)     # small 2x
        # non-synchronous unstable mode
        rpm = w * 60 / 2 / math.pi
        grow = 0.9 if 1700 < rpm < 1850 else -3.0
        self.ns_amp = min(3.0, max(0.002, self.ns_amp * math.exp(grow * dt)))
        fns = 0.62 * f
        ph = self.ns_phase + 2 * math.pi * fns * (ts - (now - dt))
        x += self.ns_amp * np.sin(ph)
        self.ns_phase = (self.ns_phase + 2 * math.pi * fns * dt) % (2 * math.pi)
        x += rng.normal(0, 0.009, k)
        y = 0.3 * x + rng.normal(0, 0.009, k)
        z = 1.0 + rng.normal(0, 0.009, k)
        self.imu.push(np.stack([x, y, z], 1).astype(np.float32), now)

        # ---- hall edges: opr_positions magnets, opr_missing of them north-out (no pulse) ----
        npos = max(1, self.cfg['opr_positions'])
        miss = self.cfg['opr_missing'] if npos > 1 else 0
        step = 2 * math.pi / npos
        th_end = self.theta + w * dt
        k0 = math.floor(self.theta / step)
        k1 = math.floor(th_end / step)
        for kk in range(k0 + 1, k1 + 1):
            if miss and kk % npos == npos - 1:
                continue                                # the north-out magnet
            tp = (now - dt) + (kk * step - self.theta) / w
            if self.opr is not None:
                self.opr.push(tp)
        self.tacho += int((th_end - self.theta) / (2 * math.pi) * ratio * pp * 6)
        self.theta = th_end % (2 * math.pi * 1000)

    def values(self):
        pp, ratio = self.cfg['motor_pole_pairs'], self.cfg['belt_ratio']
        erpm = self.omega * 60 / 2 / math.pi * ratio * pp
        return dict(temp_fet=self.temp_fet, temp_motor=self.temp_motor, current=self.current,
                    erpm=erpm, v_in=24.0 - 0.02 * abs(self.current), tacho=self.tacho)


class SimSerial:
    """Fake VESC on a fake UART."""
    def __init__(self, rotor):
        self.rotor = rotor
        self.rx = bytearray()
        self.d = V.Deframer()

    def write(self, data):
        for p in self.d.feed(data):
            c = p[0]
            with self.rotor.lock:
                if c == V.COMM_SET_RPM:
                    self.rotor.cmd = ('rpm', struct.unpack('>i', p[1:5])[0])
                elif c == V.COMM_SET_CURRENT:
                    self.rotor.cmd = ('current', struct.unpack('>i', p[1:5])[0] / 1000)
                elif c == V.COMM_SET_CURRENT_BRAKE:
                    self.rotor.cmd = ('brake', struct.unpack('>i', p[1:5])[0] / 1000)
                elif c == V.COMM_GET_VALUES:
                    v = self.rotor.values()
                    pl = struct.pack('>Bhhiiiihihiiiiii', V.COMM_GET_VALUES,
                                     int(v['temp_fet'] * 10), int(v['temp_motor'] * 10),
                                     int(v['current'] * 100), int(v['current'] * v['erpm'] / 2e5 * 100),
                                     0, 0, int(min(0.95, v['erpm'] / 60000) * 1000), int(v['erpm']),
                                     int(v['v_in'] * 10), 0, 0, 0, 0, v['tacho'], abs(v['tacho']))
                    self.rx += V.frame(pl + bytes([0]))
        return len(data)

    def read(self, n):
        time.sleep(0.001)
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out
