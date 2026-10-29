"""Flat key = value config (povd.conf). Keys are the names used everywhere: UI labels, logs, websocket."""
import os, re

# key: (default, type, description)
DEFAULTS = {
    # --- hardware ---
    'vesc_port':            ('/dev/serial0', str,   'VESC UART device'),
    'vesc_baud':            (115200,         int,   'VESC UART baud rate (VESC Tool: App Settings > UART)'),
    'motor_pole_pairs':     (7,              int,   'Motor pole pairs (Flipsky 7070: 14 poles = 7)'),
    'belt_ratio':           (1.0,            float, 'Motor rpm / rotor rpm'),
    'imu_bus':              (1,              int,   'I2C bus number of the MPU-6050'),
    'imu_addr':             (0x68,           int,   'MPU-6050 I2C address (0x68 or 0x69)'),
    'imu_range_g':          (4,              int,   'Accelerometer full scale: 2, 4, 8 or 16 g'),
    'imu_axis':             ('x',            str,   'Accelerometer axis in the rotor plane used for balancing: x, y or z'),
    'opr_chip':             ('/dev/gpiochip0', str, 'GPIO chip for the once-per-rev sensor'),
    'opr_line':             (-1,             int,   'GPIO line (BCM number) of the once-per-rev sensor; -1 = not fitted'),
    'opr_edge':             ('falling',      str,   'Once-per-rev edge: rising or falling'),
    'opr_positions':        (5,              int,   'Magnet positions round the gear (5 = one per spoke; 1 = single magnet)'),
    'opr_missing':          (1,              int,   'Positions with no pulse (1 = one magnet fitted north-out to mark the index; 0 = none)'),
    # --- speed control ---
    'rpm_max':              (2000.0,         float, 'Highest rotor rpm that can be commanded'),
    'rpm_start':            (150.0,          float, 'Rotor rpm the ramp starts from (VESC sensorless start)'),
    'ramp_rate_rpm_s':      (50.0,           float, 'Speed-up rate, rotor rpm per second'),
    'decel_rpm_s':          (100.0,          float, 'Slow-down rate for stop and soft trips, rotor rpm per second'),
    'rpm_release':          (120.0,          float, 'Below this rotor rpm a stopping rotor is released (motor current 0) to coast'),
    'keepalive_hz':         (20.0,           float, 'Rate the rpm command is resent to the VESC (also its keepalive)'),
    # --- trip limits ---
    'vib_1x_limit_g':       (0.50,           float, 'Soft trip: once-per-rev vibration amplitude (g)'),
    'vib_rms_limit_g':      (1.00,           float, 'Soft trip: broadband vibration RMS 2-200 Hz (g)'),
    'vib_hard_limit_g':     (2.00,           float, 'Hard trip: broadband RMS (g) -> trip_hard_action'),
    'vib_nonsync_limit_g':  (0.30,           float, 'Soft trip: largest non-synchronous peak (g), e.g. ground resonance or flutter'),
    'vib_growth_limit_s':   (2.0,            float, 'Soft trip: non-synchronous peak growing by e (x2.7) in less than this many seconds'),
    'vib_1x_slope_limit':   (3.0,            float, 'Hold the ramp: 1x amplitude rising faster than rpm^N (N = this); 2 = pure unbalance, larger = approaching a resonance'),
    'rpm_track_err_pct':    (15.0,           float, 'Soft trip: rpm error vs command, percent'),
    'rpm_track_time_s':     (2.0,            float, 'Soft trip: rpm error must persist this long'),
    'motor_current_limit_a': (40.0,          float, 'Soft trip: motor current (A)'),
    'temp_fet_limit_c':     (80.0,           float, 'Soft trip: VESC MOSFET temperature (C)'),
    'temp_motor_limit_c':   (90.0,           float, 'Soft trip: motor temperature (C), if the VESC has a sensor'),
    'sensor_timeout_s':     (0.5,            float, 'Soft trip: VESC or IMU data older than this (s)'),
    'opr_timeout_revs':     (3.0,            float, 'Soft trip: once-per-rev pulses missing for this many revolutions (only if opr_line set)'),
    'ui_deadman_s':         (10.0,           float, 'Soft trip: no browser connected for this long while running (0 = off)'),
    'trip_action':          ('ramp_down',    str,   'Soft trip action: ramp_down, coast or brake'),
    'trip_hard_action':     ('coast',        str,   'Hard trip action: coast or brake'),
    'brake_current_a':      (5.0,            float, 'Brake current for the brake action (A); check your supply can absorb regen'),
    # --- analysis / balancing ---
    'analysis_window_s':    (2.0,            float, 'Length of vibration window for the 1x / RMS / spectrum estimate (s)'),
    'balance_settle_s':     (5.0,            float, 'Wait after reaching balance_rpm before averaging (s)'),
    'balance_avg_s':        (10.0,           float, 'Averaging time for each balance run (s)'),
    'balance_rpm':          (800.0,          float, 'Rotor rpm for balance runs'),
    'balance_radius_mm':    (100.0,          float, 'Radius at which trial and correction masses are fitted (mm)'),
    'balance_positions_deg': ('',            str,   'Angles where masses can be fitted, e.g. 0,90,180,270 (empty = any angle)'),
    # --- server ---
    'web_port':             (8080,           int,   'Web UI port'),
    'log_dir':              ('~/povd-logs',  str,   'CSV run logs'),
}

LIVE_KEYS = [k for k in DEFAULTS if not k.startswith(('vesc_', 'imu_', 'opr_chip', 'opr_line', 'opr_edge', 'opr_positions', 'opr_missing', 'web_', 'log_'))]


def _parse(v, typ):
    if typ is int:
        return int(v, 0) if isinstance(v, str) else int(v)
    if typ is float:
        return float(v)
    return str(v)


class Config(dict):
    def __init__(self, path):
        super().__init__({k: d for k, (d, _, _) in DEFAULTS.items()})
        self.path = os.path.expanduser(path)
        if os.path.exists(self.path):
            for line in open(self.path):
                line = line.split('#', 1)[0].strip()
                if not line or '=' not in line:
                    continue
                k, v = (s.strip() for s in line.split('=', 1))
                if k in DEFAULTS:
                    self[k] = _parse(v, DEFAULTS[k][1])

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self[key] = _parse(value, DEFAULTS[key][1])
        return self[key]

    def save(self):
        """Rewrite values in place, keeping comments; append keys not yet in the file."""
        lines = open(self.path).read().splitlines() if os.path.exists(self.path) else []
        seen = set()
        out = []
        for line in lines:
            m = re.match(r'^(\s*)([a-z0-9_]+)(\s*=\s*)([^#]*?)(\s*#.*)?$', line)
            if m and m.group(2) in DEFAULTS:
                k = m.group(2); seen.add(k)
                out.append('%s%s%s%s%s' % (m.group(1), k, m.group(3), self._fmt(k), m.group(5) or ''))
            else:
                out.append(line)
        for k in DEFAULTS:
            if k not in seen:
                out.append('%s = %s    # %s' % (k, self._fmt(k), DEFAULTS[k][2]))
        tmp = self.path + '.tmp'
        open(tmp, 'w').write('\n'.join(out) + '\n')
        os.replace(tmp, self.path)

    def _fmt(self, k):
        v = self[k]
        if k == 'imu_addr':
            return '0x%02x' % v
        return str(v)

    def describe(self):
        return [dict(key=k, value=self[k], type=DEFAULTS[k][1].__name__, desc=DEFAULTS[k][2],
                     live=k in LIVE_KEYS) for k in DEFAULTS]
