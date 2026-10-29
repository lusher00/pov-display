#!/usr/bin/env python3
"""Read the GY-521 (MPU-6050) on I2C1 and print accel/gyro.

Wiring: VCC -> 3V3 (pin 1), GND -> pin 9, SCL -> pin 5, SDA -> pin 3.
AD0 open -> address 0x68.

Usage:
    python3 mpu_watch.py              # 10 Hz, accel in g, gyro in deg/s
    python3 mpu_watch.py --hz 50
    python3 mpu_watch.py --raw        # raw 16-bit counts
    python3 mpu_watch.py --addr 0x69  # if AD0 is tied high

At rest on the bench one accel axis reads ~1.00 g, the others ~0, |a| ~1.00.
"""
import argparse
import struct
import sys
import time

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus  # python3-smbus, same call signatures used here

WHO_AM_I = 0x75
PWR_MGMT_1 = 0x6B
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_XOUT_H = 0x3B

ap = argparse.ArgumentParser()
ap.add_argument("--bus", type=int, default=1)
ap.add_argument("--addr", type=lambda s: int(s, 0), default=0x68)
ap.add_argument("--hz", type=float, default=10.0)
ap.add_argument("--raw", action="store_true")
ap.add_argument("--range", type=int, choices=[2, 4, 8, 16], default=2, help="accel full scale in g")
args = ap.parse_args()

bus = SMBus(args.bus)

who = bus.read_byte_data(args.addr, WHO_AM_I)
if who not in (0x68, 0x69, 0x70, 0x71, 0x72):  # 0x68 MPU-6050; others are MPU-9250/6500 variants
    print(f"WHO_AM_I = 0x{who:02X}: not an MPU-6050 at 0x{args.addr:02X}")
    sys.exit(1)
print(f"WHO_AM_I = 0x{who:02X} at 0x{args.addr:02X}")

bus.write_byte_data(args.addr, PWR_MGMT_1, 0x01)  # wake, clock from gyro X PLL
time.sleep(0.05)
afs = {2: 0, 4: 1, 8: 2, 16: 3}[args.range]
bus.write_byte_data(args.addr, ACCEL_CONFIG, afs << 3)
bus.write_byte_data(args.addr, GYRO_CONFIG, 0 << 3)   # +/-250 dps
bus.write_byte_data(args.addr, CONFIG, 0x03)          # DLPF ~44 Hz accel / 42 Hz gyro
bus.write_byte_data(args.addr, SMPLRT_DIV, 0)         # 1 kHz internal rate

acc_lsb = 16384.0 / (2 ** afs)   # LSB per g
gyr_lsb = 131.0                  # LSB per deg/s at +/-250

print("      ax      ay      az    |a|      gx      gy      gz    temp")
period = 1.0 / args.hz
try:
    while True:
        d = bus.read_i2c_block_data(args.addr, ACCEL_XOUT_H, 14)
        ax, ay, az, t, gx, gy, gz = struct.unpack(">hhhhhhh", bytes(d))
        if args.raw:
            print(f"{ax:7d} {ay:7d} {az:7d}         {gx:7d} {gy:7d} {gz:7d}  {t:6d}")
        else:
            a = (ax / acc_lsb, ay / acc_lsb, az / acc_lsb)
            mag = (a[0] ** 2 + a[1] ** 2 + a[2] ** 2) ** 0.5
            g = (gx / gyr_lsb, gy / gyr_lsb, gz / gyr_lsb)
            tc = t / 340.0 + 36.53
            print(f"{a[0]:7.3f} {a[1]:7.3f} {a[2]:7.3f} {mag:6.3f} {g[0]:7.1f} {g[1]:7.1f} {g[2]:7.1f}  {tc:5.1f}C")
        time.sleep(period)
except KeyboardInterrupt:
    pass
finally:
    bus.close()
