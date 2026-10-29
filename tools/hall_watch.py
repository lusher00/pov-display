#!/usr/bin/env python3
"""Watch the A3144 hall sensor on a GPIO line and print every edge.

Wiring: A3144 VCC -> 5V (pin 2), GND -> GND, OUT -> GPIO4 (pin 7) with a
4.7k pull-up to 3V3. The output is open collector, so the line is HIGH with
no magnet and LOW while a south pole faces the branded side.

Usage:
    python3 hall_watch.py            # GPIO4, print edges + 1 s summary
    python3 hall_watch.py --line 17  # another GPIO
    python3 hall_watch.py --quiet    # summary only (use when spinning)

Hand test: bring a magnet to the branded face. South pole -> LOW, north -> nothing.
Spinning: 4 pulses + 1 gap per revolution with opr_positions=5, opr_missing=1.
"""
import argparse
import signal
import sys
import time

from gpiozero import DigitalInputDevice

ap = argparse.ArgumentParser()
ap.add_argument("--line", type=int, default=4, help="BCM GPIO number (default 4)")
ap.add_argument("--positions", type=int, default=5, help="magnet pockets per rev")
ap.add_argument("--quiet", action="store_true", help="no per-edge output")
args = ap.parse_args()

# pull_up=None: external pull-up, do not enable the SoC one.
# active_state=False: LOW on the pin means "active" (magnet present).
pin = DigitalInputDevice(args.line, pull_up=None, active_state=False)

last_fall = None
intervals = []        # seconds between consecutive falling edges
pulses = 0
total = 0


def on_fall():
    global last_fall, pulses, total
    now = time.monotonic()
    pulses += 1
    total += 1
    if last_fall is not None:
        dt = now - last_fall
        intervals.append(dt)
        if not args.quiet:
            print(f"LOW   dt={dt*1000:7.2f} ms  #{total}")
    elif not args.quiet:
        print(f"LOW   #{total}")
    last_fall = now


def on_rise():
    if not args.quiet:
        print("HIGH")


pin.when_activated = on_fall
pin.when_deactivated = on_rise

print(f"GPIO{args.line}: {'LOW (magnet)' if pin.is_active else 'HIGH (no magnet)'}  ctrl-c to stop")

stop = False
signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("stop", True))

while not stop:
    time.sleep(1.0)
    if intervals:
        n = len(intervals)
        # Shortest intervals are magnet-to-magnet; the gap is ~2x those.
        short = sorted(intervals)[: max(1, n // 2)]
        pitch = sum(short) / len(short)
        rpm = 60.0 / (pitch * args.positions)
        print(f"-- {pulses} pulses/s  pitch={pitch*1000:.2f} ms  ~{rpm:.0f} rpm  (total {total})")
    else:
        print(f"-- {pulses} pulses/s  (total {total})")
    pulses = 0
    intervals.clear()

pin.close()
sys.exit(0)
