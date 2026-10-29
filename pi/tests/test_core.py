import math, cmath, struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from povd_ctl import vesc as V, balance as B, analysis as A


def test_crc():
    assert V.crc16(b'123456789') == 0x31C3          # CRC-16/XMODEM check value


def test_frame_roundtrip():
    d = V.Deframer()
    pkts = d.feed(b'\x00\xff' + V.cmd_rpm(12345) + V.cmd_current(-2.5)[:4])
    assert len(pkts) == 1 and pkts[0][0] == V.COMM_SET_RPM
    assert struct.unpack('>i', pkts[0][1:5])[0] == 12345
    long = bytes(300)
    assert d.feed(V.cmd_current(-2.5)[4:] + V.frame(long))[-1] == long


def test_parse_values():
    pl = struct.pack('>Bhhiiiihihiiiiii', 4, 455, 312, 1234, 56, 0, 0, 512, 21000, 241, 0, 0, 0, 0, 77, 77) + b'\x05'
    v = V.parse_values(pl)
    assert abs(v['temp_fet_c'] - 45.5) < 1e-9 and abs(v['motor_current_a'] - 12.34) < 1e-9
    assert v['erpm'] == 21000 and abs(v['v_in'] - 24.1) < 1e-9 and v['fault_name'] == 'OVER_TEMP_FET'


def test_vector_method():
    H = 0.004 * cmath.exp(1j * math.radians(-130))       # g per gram
    U = B.pol(3.0, 70)                                   # actual unbalance as an equivalent mass
    V0 = H * U
    T = B.pol(1.5, 200)
    V1 = H * (U + T)
    r = B.vector_method(V0, V1, 1.5, 200)
    g, deg = r['correction']
    assert abs(g - 3.0) < 1e-9 and abs(((deg - 250) + 180) % 360 - 180) < 1e-6
    keep = B.pol(*r['with_trial_left'][:1], r['with_trial_left'][1]) if False else None


def test_four_run():
    H = 0.004 * cmath.exp(1j * math.radians(40))
    U = B.pol(2.2, 315)
    A0 = abs(H * U)
    angs = [10, 130, 250]
    amps = [abs(H * (U + B.pol(1.0, a))) for a in angs]
    r = B.four_run(A0, amps, 1.0, angs)
    g, deg = r['correction']
    assert abs(g - 2.2) < 1e-6 and abs(((deg - 135) + 180) % 360 - 180) < 1e-4


def test_split():
    s = B.split(2.0, 45, [0, 90, 180, 270])
    assert abs(s[0][0] - math.sqrt(2)) < 1e-9 and s[0][1] == 0 and s[1][1] == 90


def test_one_x_with_pulses():
    fs, f = 1000.0, 20.0
    t = np.arange(0, 3, 1 / fs)
    theta = 2 * math.pi * f * t
    Vtrue = 0.12 * cmath.exp(1j * math.radians(37))
    x = (Vtrue * np.exp(1j * theta)).real + np.random.default_rng(0).normal(0, 0.01, len(t))
    pulses = np.arange(0, 3.0001, 1 / f)
    o = A.one_x(t, x, f, pulses)
    assert abs(o['amp_g'] - 0.12) < 0.003 and abs(o['phase_deg'] - 37) < 2


def test_one_x_search_without_pulses():
    fs = 1000.0
    t = np.arange(0, 2, 1 / fs)
    x = 0.08 * np.cos(2 * math.pi * 21.3 * t + 1)
    o = A.one_x(t, x, 21.0)
    assert abs(o['amp_g'] - 0.08) < 0.004 and abs(o['f_hz'] - 21.3) < 0.1


def test_spectrum_rms_and_nonsync():
    fs = 1000.0
    t = np.arange(0, 2, 1 / fs)
    x = 0.1 * np.cos(2 * math.pi * 20 * t) + 0.05 * np.cos(2 * math.pi * 12.4 * t)
    s = A.spectrum(t, x, 20.0)
    assert abs(s['rms_g'] - math.sqrt(0.1 ** 2 / 2 + 0.05 ** 2 / 2)) < 0.005
    assert abs(s['ns_hz'] - 12.4) < 0.6 and abs(s['ns_g'] - 0.05) < 0.01


def test_pulse_pattern_4_plus_gap():
    from povd_ctl.opr import PulseBuffer
    pb = PulseBuffer(5, 1)
    rev = 60 / 1500.0
    t, idx = 0.0, []
    for k in range(5 * 20):
        pos = k % 5
        if pos == 4:
            continue                    # north-out magnet
        t = (k // 5) * rev + pos * rev / 5 + 1e-5 * ((k * 7) % 3)   # small jitter
        pb.push(t)
        if pos == 0:
            idx.append(t)
    got = list(pb.t)
    assert len(got) >= 18 and all(abs(g - i) < 1e-9 for g, i in zip(got, idx[-len(got):]))
    assert pb.pattern_errors == 0
    assert abs(pb.rpm() - 1500) < 15


def test_pulse_single_magnet():
    from povd_ctl.opr import PulseBuffer
    pb = PulseBuffer(1, 0)
    for k in range(10):
        pb.push(k * 0.05)
    assert len(pb.t) == 10 and abs(pb.rpm() - 1200) < 1e-6
