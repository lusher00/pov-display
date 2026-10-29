#!/usr/bin/env python3
"""VESC UART test (Flipsky 75200 or any VESC 5.x/6.x firmware).

Wiring: Pi TXD (pin 8) -> VESC RX, Pi RXD (pin 10) -> VESC TX, GND to GND.
VESC: App Settings -> General -> App to use = UART (or PPM+UART), baud 115200.

Usage:
    python3 vesc_test.py version                  # firmware + hw name
    python3 vesc_test.py values                   # print telemetry at 5 Hz
    python3 vesc_test.py rpm 3000 --seconds 5     # hold 3000 eRPM for 5 s, then coast
    python3 vesc_test.py duty 0.05 --seconds 3    # 5 % duty for 3 s
    python3 vesc_test.py current 2.0 --seconds 3  # 2 A motor current for 3 s
    python3 vesc_test.py stop                     # current 0 (coast)
    python3 vesc_test.py brake 5                  # 5 A regen brake, then release
    python3 vesc_test.py limits                   # write current limits (defaults below), RAM only
    python3 vesc_test.py limits --store           # same, and save to flash
    python3 vesc_test.py limits --batt_max 16 --store   # once the supplies are in series

limits defaults: motor_scale 1.0, batt_max 8 A, batt_min -1 A, erpm_max 30000,
duty_max 0.95, watt_max 1.5 MW (off). Without --store they last until the VESC
reboots. Only these fields change; Motor Current Max/Min and Absolute Max Current
are not reachable through this command and stay as set in VESC Tool.

eRPM = mechanical rpm * pole pairs. A 14-pole motor (7 pairs) at 1000 rpm = 7000 eRPM.
Any set command must be refreshed faster than the VESC timeout (default 1 s); this
script resends at 20 Hz for --seconds, then sends current 0.
"""
import argparse
import struct
import sys
import time

import serial

COMM_FW_VERSION = 0
COMM_GET_VALUES = 4
COMM_SET_DUTY = 5
COMM_SET_CURRENT = 6
COMM_SET_CURRENT_BRAKE = 7
COMM_SET_RPM = 8
COMM_ALIVE = 30
COMM_SET_MCCONF_TEMP = 48   # set the limit fields of the motor config, optionally store


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def packet(payload: bytes) -> bytes:
    n = len(payload)
    hdr = bytes([2, n]) if n < 256 else bytes([3, n >> 8, n & 0xFF])
    return hdr + payload + struct.pack(">H", crc16(payload)) + b"\x03"


class Vesc:
    def __init__(self, port, baud, timeout=0.2):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.buf = b""

    def send(self, payload: bytes):
        self.ser.write(packet(payload))

    def recv(self):
        """Return one payload or None. Resyncs on garbage."""
        deadline = time.monotonic() + self.ser.timeout
        while time.monotonic() < deadline:
            self.buf += self.ser.read(256)
            while self.buf:
                if self.buf[0] == 2:
                    if len(self.buf) < 2:
                        break
                    n, off = self.buf[1], 2
                elif self.buf[0] == 3:
                    if len(self.buf) < 3:
                        break
                    n, off = (self.buf[1] << 8) | self.buf[2], 3
                else:
                    self.buf = self.buf[1:]
                    continue
                end = off + n + 3
                if len(self.buf) < end:
                    break
                payload = self.buf[off:off + n]
                crc = struct.unpack(">H", self.buf[off + n:off + n + 2])[0]
                ok = crc == crc16(payload) and self.buf[end - 1] == 3
                self.buf = self.buf[end:] if ok else self.buf[1:]
                if ok:
                    return payload
        return None

    def fw_version(self):
        self.send(bytes([COMM_FW_VERSION]))
        p = self.recv()
        if not p or p[0] != COMM_FW_VERSION:
            return None
        major, minor = p[1], p[2]
        name_end = p.index(b"\x00", 3)
        hw = p[3:name_end].decode(errors="replace")
        return major, minor, hw

    def get_values(self):
        self.send(bytes([COMM_GET_VALUES]))
        p = self.recv()
        if not p or p[0] != COMM_GET_VALUES:
            return None
        f = ">hhiiiihihiiiiiiB"  # through fault code
        v = struct.unpack_from(f, p, 1)
        return {
            "temp_fet": v[0] / 10, "temp_motor": v[1] / 10,
            "i_motor": v[2] / 100, "i_in": v[3] / 100,
            "duty": v[6] / 1000, "erpm": v[7], "v_in": v[8] / 10,
            "ah": v[9] / 1e4, "wh": v[11] / 1e4,
            "tach": v[13], "tach_abs": v[14], "fault": v[15],
        }

    def set_duty(self, d):
        self.send(bytes([COMM_SET_DUTY]) + struct.pack(">i", int(d * 100000)))

    def set_current(self, a):
        self.send(bytes([COMM_SET_CURRENT]) + struct.pack(">i", int(a * 1000)))

    def set_brake(self, a):
        self.send(bytes([COMM_SET_CURRENT_BRAKE]) + struct.pack(">i", int(a * 1000)))

    def set_rpm(self, erpm):
        self.send(bytes([COMM_SET_RPM]) + struct.pack(">i", int(erpm)))

    def alive(self):
        self.send(bytes([COMM_ALIVE]))

    def set_limits(self, motor_scale, batt_max, batt_min, erpm_max, duty_max,
                   watt_max, store):
        """COMM_SET_MCCONF_TEMP: overwrite only the limit fields of the motor config.

        Payload, per commands.c in VESC fw 5.x/6.x:
            u8 store, u8 forward_can, u8 ack, u8 divide_by_controllers,
            f32 l_current_min_scale, f32 l_current_max_scale,   (0..1, scale on Motor Current Max/Min)
            f32 l_min_erpm, f32 l_max_erpm,
            f32 l_min_duty, f32 l_max_duty,
            f32 l_watt_min, f32 l_watt_max,
            f32 l_in_current_min, f32 l_in_current_max          (battery A, regen is negative)
        The absolute Motor Current Max/Min and Absolute Max Current are NOT in this
        command; set those in VESC Tool. Floats are IEEE754 big-endian.
        """
        hdr = bytes([COMM_SET_MCCONF_TEMP, 1 if store else 0, 0, 1, 0])
        vals = (motor_scale, motor_scale,
                -erpm_max, erpm_max,
                0.005, duty_max,
                -watt_max, watt_max,
                batt_min, batt_max)
        self.send(hdr + struct.pack(">10f", *vals))
        p = self.recv()
        return bool(p) and p[0] == COMM_SET_MCCONF_TEMP


FAULTS = ["NONE", "OVER_VOLTAGE", "UNDER_VOLTAGE", "DRV", "ABS_OVER_CURRENT",
          "OVER_TEMP_FET", "OVER_TEMP_MOTOR", "GATE_DRIVER_OVER_VOLTAGE",
          "GATE_DRIVER_UNDER_VOLTAGE", "MCU_UNDER_VOLTAGE", "BOOTING_FROM_WATCHDOG_RESET",
          "ENCODER_SPI", "ENCODER_SINCOS_BELOW_MIN_AMPLITUDE",
          "ENCODER_SINCOS_ABOVE_MAX_AMPLITUDE", "FLASH_CORRUPTION",
          "HIGH_OFFSET_CURRENT_SENSOR_1", "HIGH_OFFSET_CURRENT_SENSOR_2",
          "HIGH_OFFSET_CURRENT_SENSOR_3", "UNBALANCED_CURRENTS"]


def fmt(v):
    f = FAULTS[v["fault"]] if v["fault"] < len(FAULTS) else str(v["fault"])
    return (f"{v['erpm']:7d} erpm  duty {v['duty']:+.3f}  Im {v['i_motor']:6.2f} A  "
            f"Iin {v['i_in']:6.2f} A  Vin {v['v_in']:5.1f} V  fet {v['temp_fet']:4.1f} C  "
            f"motor {v['temp_motor']:4.1f} C  tach {v['tach']}  fault {f}")


def hold(vesc, fn, seconds, hz=20):
    t_end = time.monotonic() + seconds
    n = 0
    while time.monotonic() < t_end:
        fn()
        if n % 4 == 0:
            v = vesc.get_values()
            if v:
                print(fmt(v))
        n += 1
        time.sleep(1.0 / hz)
    vesc.set_current(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=3.0)
    # limits: current limits written with COMM_SET_MCCONF_TEMP (same names as VESC Tool)
    ap.add_argument("--motor_scale", type=float, default=1.0,
                    help="scale (0..1) applied to Motor Current Max/Min set in VESC Tool")
    ap.add_argument("--batt_max", type=float, default=8.0, help="Battery Current Max, A")
    ap.add_argument("--batt_min", type=float, default=-1.0, help="Battery Current Max Regen, A (negative)")
    ap.add_argument("--erpm_max", type=float, default=30000.0, help="Max ERPM")
    ap.add_argument("--duty_max", type=float, default=0.95, help="Max Duty Cycle")
    ap.add_argument("--watt_max", type=float, default=1500000.0, help="Max Wattage")
    ap.add_argument("--store", action="store_true", help="limits: also save to flash")
    ap.add_argument("cmd", choices=["version", "values", "rpm", "duty", "current", "brake", "stop", "limits"])
    ap.add_argument("value", nargs="?", type=float)
    a = ap.parse_args()

    v = Vesc(a.port, a.baud)

    if a.cmd == "limits":
        if a.batt_min > 0:
            sys.exit("batt_min is the regen limit and must be <= 0")
        if not 0.0 < a.motor_scale <= 1.0:
            sys.exit("motor_scale must be in (0, 1]")
        if not 0.0 < a.duty_max <= 0.95:
            sys.exit("duty_max must be in (0, 0.95]")
        ok = v.set_limits(a.motor_scale, a.batt_max, a.batt_min, a.erpm_max,
                          a.duty_max, a.watt_max, a.store)
        print(f"limits {'written' if ok else 'NOT acknowledged'}"
              f"{' and stored' if ok and a.store else ''}: "
              f"motor_scale {a.motor_scale}  batt_max {a.batt_max} A  batt_min {a.batt_min} A  "
              f"erpm_max {a.erpm_max:.0f}  duty_max {a.duty_max}  watt_max {a.watt_max:.0f}")
    elif a.cmd == "version":
        r = v.fw_version()
        print("no response" if r is None else f"fw {r[0]}.{r[1]}  hw {r[2]}")
    elif a.cmd == "values":
        try:
            while True:
                r = v.get_values()
                print(fmt(r) if r else "no response")
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
    elif a.cmd == "stop":
        v.set_current(0)
    else:
        if a.value is None:
            sys.exit(f"{a.cmd} needs a value")
        fn = {"rpm": lambda: v.set_rpm(a.value),
              "duty": lambda: v.set_duty(a.value),
              "current": lambda: v.set_current(a.value),
              "brake": lambda: v.set_brake(a.value)}[a.cmd]
        try:
            hold(v, fn, a.seconds)
        except KeyboardInterrupt:
            v.set_current(0)
    v.ser.close()


if __name__ == "__main__":
    main()
