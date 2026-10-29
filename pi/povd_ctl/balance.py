"""Single-plane rotor balancing.

Angles: degrees from the once-per-rev mark (or from blade 1 if no mark), in the direction of rotation.
Masses are at radius balance_radius_mm.

With a once-per-rev pulse (vector method, 2 runs):
    V0 = baseline 1x vector, V1 = with trial mass T (complex g*e^(j*angle))
    H = (V1 - V0) / T          influence coefficient, g of vibration per gram
    C = -V0 / H                correction mass (remove the trial first)

Without a pulse (4-run amplitude method):
    A0 baseline amplitude, A1..A3 with the same trial mass at three angles phi_i
    A_i^2 = A0^2 + P + 2 (qx cos phi_i + qy sin phi_i)   is linear in P, qx, qy
    u = (qx + j qy) / P,   C = -u * trial_g   (angle of -u)
"""
import cmath, math, json, os
import numpy as np


def pol(g, deg):
    return g * cmath.exp(1j * math.radians(deg))


def to_gdeg(c):
    return abs(c), (math.degrees(cmath.phase(c)) + 360.0) % 360.0


def vector_method(V0, V1, trial_g, trial_deg):
    T = pol(trial_g, trial_deg)
    dV = V1 - V0
    if abs(dV) < 1e-9:
        raise ValueError('trial mass made no change to the vibration; use a larger trial mass')
    H = dV / T
    C = -V0 / H
    keep = C - T                    # if the trial mass is left on
    return dict(H=H, correction=to_gdeg(C), with_trial_left=to_gdeg(keep),
                trial_effect_pct=100.0 * abs(dV) / max(abs(V0), 1e-9))


def trim(V, H):
    return to_gdeg(-V / H)


def four_run(A0, amps, trial_g, angles_deg):
    phi = np.radians(angles_deg)
    Aq = np.asarray(amps) ** 2 - A0 ** 2
    M = np.stack([np.ones_like(phi), 2 * np.cos(phi), 2 * np.sin(phi)], 1)
    (P, qx, qy), *_ = np.linalg.lstsq(M, Aq, rcond=None)
    if P <= 0:
        raise ValueError('inconsistent amplitudes (trial effect too small or rpm changed between runs)')
    u = complex(qx, qy) / P
    C = -u * trial_g
    resid = float(np.sqrt(np.mean((M @ np.array([P, qx, qy]) - Aq) ** 2)))
    return dict(correction=to_gdeg(C), g_per_gram=math.sqrt(P) / trial_g, fit_resid_g2=resid)


def split(c_g, c_deg, positions_deg):
    """Split a correction onto the two allowed positions that bracket it (positive masses)."""
    pos = sorted(p % 360 for p in positions_deg)
    if len(pos) < 2:
        return None
    C = pol(c_g, c_deg)
    best = None
    for i in range(len(pos)):
        a, b = pos[i], pos[(i + 1) % len(pos)]
        span = (b - a) % 360
        if span == 0 or span >= 180:
            continue
        if (c_deg - a) % 360 <= span:
            ea, eb = pol(1, a), pol(1, b)
            m = np.linalg.solve(np.array([[ea.real, eb.real], [ea.imag, eb.imag]]), np.array([C.real, C.imag]))
            if (m >= -1e-9).all():
                best = [(float(m[0]), a), (float(m[1]), b)]
    return best


class Store:
    """Persists balance runs and the influence coefficient."""
    def __init__(self, path):
        self.path = os.path.expanduser(path)
        self.d = dict(runs={}, H=None, H_rpm=None, H_radius_mm=None)
        if os.path.exists(self.path):
            try:
                self.d.update(json.load(open(self.path)))
            except Exception:
                pass

    def save(self):
        tmp = self.path + '.tmp'
        json.dump(self.d, open(tmp, 'w'), indent=1)
        os.replace(tmp, self.path)

    @property
    def H(self):
        h = self.d.get('H')
        return complex(*h) if h else None

    def set_H(self, H, rpm, radius):
        self.d['H'] = [H.real, H.imag]
        self.d['H_rpm'] = rpm
        self.d['H_radius_mm'] = radius
