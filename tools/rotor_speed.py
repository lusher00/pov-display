#!/usr/bin/env python3
"""Closed-loop rotor speed: hall magnets on the driven pulley -> VESC eRPM.

The VESC already holds eRPM. This outer loop holds *rotor* rpm measured from the
magnets, so belt ratio, pole pairs and slip don't matter: a feedforward eRPM is
computed from the nominal ratio, then an integrator trims it until measured
rotor rpm equals the target.

Config keys (same names as the CLI flags):
    rotor_rpm_target   setpoint, rotor rpm
    pole_pairs         7 for the 7070
    belt_ratio         driven/driver, 55/26 = 2.115
    opr_line           GPIO for the A3144 (4)
    opr_positions      magnet pockets per rev (5)
    opr_missing        pockets with no pulse (1)
    ramp_rpm_s         setpoint slew limit, rpm per second
    kp, ki             outer-loop gains, eRPM per rpm of error
    erpm_max           hard cap on commanded eRPM

Usage:
    python3 rotor_speed.py 600 --seconds 20
    python3 rotor_speed.py 1000 --seconds 30 --ramp_rpm_s 100
    Ctrl-C at any time -> current 0.

Needs vesc_test.py in the same directory (Vesc class) and gpiozero.
"""
import argparse
import collections
import signal
import time

from gpiozero import DigitalInputDevice
from vesc_test import Vesc, fmt

ap = argparse.ArgumentParser()
ap.add_argument("rotor_rpm_target", type=float)
ap.add_argument("--seconds", type=float, default=20.0)
ap.add_argument("--pole_pairs", type=int, default=7)
ap.add_argument("--belt_ratio", type=float, default=55 / 26)  # 2.115, confirmed: 7000 eRPM -> 475 rotor rpm
ap.add_argument("--opr_line", type=int, default=4)
ap.add_argument("--opr_positions", type=int, default=5)
ap.add_argument("--opr_missing", type=int, default=1)
ap.add_argument("--ramp_rpm_s", type=float, default=200.0)
ap.add_argument("--kp", type=float, default=2.0)
ap.add_argument("--ki", type=float, default=4.0)
ap.add_argument("--erpm_max", type=float, default=25000.0)
ap.add_argument("--port", default="/dev/serial0")
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--hz", type=float, default=20.0)
args = ap.parse_args()

PULSES_PER_REV = args.opr_positions - args.opr_missing
K_FF = args.pole_pairs * args.belt_ratio          # eRPM per rotor rpm, nominal

# --- hall: rotor rpm from the time between pulse i and pulse i+PULSES_PER_REV ---
# That span is exactly one revolution no matter where the missing pulse falls.
stamps = collections.deque(maxlen=PULSES_PER_REV + 1)
pin = DigitalInputDevice(args.opr_line, pull_up=None, active_state=False)


def on_fall():
    stamps.append(time.monotonic())


pin.when_activated = on_fall


def rotor_rpm():
    if len(stamps) < PULSES_PER_REV + 1:
        return 0.0
    period = stamps[-1] - stamps[0]
    return 60.0 / period if period > 0 else 0.0


def last_pulse_age():
    return time.monotonic() - stamps[-1] if stamps else 1e9


# --- vesc ---
vesc = Vesc(args.port, args.baud)

stop = False
signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("stop", True))

dt = 1.0 / args.hz
setpoint = 0.0
integ = 0.0
t_end = time.monotonic() + args.seconds
n = 0
print(f"target {args.rotor_rpm_target:.0f} rpm  ff {K_FF:.3f} eRPM/rpm  "
      f"kp {args.kp} ki {args.ki}  ramp {args.ramp_rpm_s} rpm/s")
print("   set   meas    err    erpm_cmd  | vesc")

try:
    while not stop and time.monotonic() < t_end:
        # slew-limited setpoint
        step = args.ramp_rpm_s * dt
        if setpoint < args.rotor_rpm_target:
            setpoint = min(setpoint + step, args.rotor_rpm_target)
        else:
            setpoint = max(setpoint - step, args.rotor_rpm_target)

        meas = rotor_rpm()

        # loss-of-feedback guard: commanding speed but no pulses -> stop
        if setpoint > 50 and last_pulse_age() > 1.0 and n > int(2 * args.hz):
            print("no hall pulses for 1 s while commanding speed - stopping")
            break

        err = setpoint - meas
        # only integrate once the rotor is actually turning (avoid windup at start)
        if meas > 20:
            integ += args.ki * err * dt
            integ = max(-0.3 * K_FF * setpoint, min(0.3 * K_FF * setpoint, integ))

        erpm_cmd = K_FF * setpoint + args.kp * err + integ
        erpm_cmd = max(0.0, min(args.erpm_max, erpm_cmd))
        vesc.set_rpm(erpm_cmd)

        if n % int(args.hz / 4) == 0:
            v = vesc.get_values()
            tail = fmt(v) if v else "no response"
            print(f"{setpoint:6.0f} {meas:6.0f} {err:+6.0f} {erpm_cmd:10.0f}  | {tail}")
        n += 1
        time.sleep(dt)
finally:
    vesc.set_current(0)
    vesc.ser.close()
    pin.close()
