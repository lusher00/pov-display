"""Vibration analysis on one accelerometer axis.

one_x():  once-per-rev amplitude (g peak) and, with a once-per-rev pulse, phase relative to the mark.
          Phase convention: a(t) = Re(V * exp(j*theta(t))), theta = rotor angle from the mark.
spectrum(): amplitude spectrum (g peak), broadband RMS 2-200 Hz, largest non-synchronous peak.
"""
import math
import numpy as np


def rotor_angle(t, pulses):
    """Rotor angle (rad, unwrapped) at times t by linear interpolation between pulse times.
    Returns (theta, mask) where mask marks samples between the first and last pulse."""
    p = np.asarray(pulses)
    mask = (t >= p[0]) & (t <= p[-1])
    theta = np.interp(t, p, 2 * math.pi * np.arange(len(p)))
    return theta, mask


def lockin(x, theta):
    return 2.0 * np.mean(x * np.exp(-1j * theta))


def one_x(t, x, f_guess, pulses=None, search=True):
    """Returns dict(amp_g, phase_deg or None, f_hz, n_revs)."""
    x = x - np.mean(x)
    if pulses is not None and len(pulses) >= 3:
        theta, m = rotor_angle(t, pulses)
        if m.sum() > 50:
            # whole revolutions only
            V = lockin(x[m], theta[m])
            f = (len(pulses) - 1) / (pulses[-1] - pulses[0])
            return dict(amp_g=float(abs(V)), phase_deg=float(math.degrees(math.atan2(V.imag, V.real))),
                        f_hz=float(f), n_revs=len(pulses) - 1, V=V)
    if f_guess <= 0.5 or len(t) < 100:
        return dict(amp_g=0.0, phase_deg=None, f_hz=float(f_guess), n_revs=0, V=None)
    tt = t - t[0]
    T = tt[-1]
    best = (0.0, f_guess)
    cands = [f_guess] if not search else f_guess * (1 + np.linspace(-0.04, 0.04, 33))
    for f in cands:
        a = abs(lockin(x, 2 * math.pi * f * tt))
        if a > best[0]:
            best = (a, f)
    # refine around the best with a finer grid
    if search:
        df = f_guess * 0.0025
        for f in best[1] + np.linspace(-df, df, 11):
            a = abs(lockin(x, 2 * math.pi * f * tt))
            if a > best[0]:
                best = (a, f)
    return dict(amp_g=float(best[0]), phase_deg=None, f_hz=float(best[1]), n_revs=int(T * best[1]), V=None)


def spectrum(t, x, f1, fmax=100.0, nonsync_band=(1.0, 100.0)):
    x = x - np.mean(x)
    n = len(x)
    if n < 256:
        return None
    fs = (n - 1) / (t[-1] - t[0])
    w = np.hanning(n)
    X = np.fft.rfft(x * w)
    amp = np.abs(X) * 2.0 / w.sum()
    f = np.fft.rfftfreq(n, 1.0 / fs)
    # broadband RMS 2-200 Hz from the spectrum (Parseval with window power correction)
    band = (f >= 2.0) & (f <= 200.0)
    pw = np.abs(X) ** 2 / (w ** 2).sum() / n * 2
    rms = float(math.sqrt(pw[band].sum())) if band.any() else 0.0
    # non-synchronous: largest peak away from rotor harmonics
    df = f[1] - f[0]
    ok = (f >= nonsync_band[0]) & (f <= nonsync_band[1])
    if f1 > 0.5:
        for k in range(1, 6):
            ok &= np.abs(f - k * f1) > max(0.8, 4 * df)
    if ok.any():
        i = int(np.argmax(np.where(ok, amp, 0)))
        ns_amp, ns_f = float(amp[i]), float(f[i])
    else:
        ns_amp, ns_f = 0.0, 0.0
    keep = f <= fmax
    fk, ak = f[keep], amp[keep]
    if len(fk) > 400:                      # max-decimate for display
        step = int(math.ceil(len(fk) / 400))
        m = len(fk) // step * step
        fk = fk[:m].reshape(-1, step)[:, 0]
        ak = ak[:m].reshape(-1, step).max(1)
    return dict(rms_g=rms, ns_g=ns_amp, ns_hz=ns_f, f=fk.round(2).tolist(), a=ak.round(5).tolist(), fs=fs)


class Growth:
    """Exponential growth rate of a positive signal from a short history (log-linear fit)."""
    def __init__(self, span_s=1.5):
        self.span = span_s
        self.h = []

    def add(self, t, v):
        self.h.append((t, max(v, 1e-6)))
        while self.h and t - self.h[0][0] > self.span:
            self.h.pop(0)

    def rate(self):
        if len(self.h) < 4:
            return 0.0
        a = np.array(self.h)
        return float(np.polyfit(a[:, 0], np.log(a[:, 1]), 1)[0])


class SlopeVsRpm:
    """Exponent N in amp ~ rpm^N over the last `span_rpm` of a ramp."""
    def __init__(self, span_rpm=150.0):
        self.span = span_rpm
        self.h = []

    def reset(self):
        self.h = []

    def add(self, rpm, amp):
        if rpm < 100 or amp <= 0:
            return
        self.h.append((rpm, amp))
        while len(self.h) > 6 and rpm - self.h[0][0] > self.span:
            self.h.pop(0)

    def exponent(self):
        if len(self.h) < 5:
            return 0.0
        a = np.array(self.h)
        if a[-1, 0] - a[0, 0] < 50.0:
            return 0.0
        return float(np.polyfit(np.log(a[:, 0]), np.log(a[:, 1]), 1)[0])
