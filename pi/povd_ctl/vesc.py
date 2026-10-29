"""VESC UART protocol (bldc firmware 3.x - 6.x): framing, set_rpm / set_current / set_current_brake, get_values.

Packet: 0x02 len payload crc16_hi crc16_lo 0x03   (len <= 255)
        0x03 len_hi len_lo payload crc16 0x03     (len > 255)
CRC-16/XMODEM (poly 0x1021, init 0) over the payload.
"""
import struct, threading, time

COMM_FW_VERSION = 0
COMM_GET_VALUES = 4
COMM_SET_DUTY = 5
COMM_SET_CURRENT = 6
COMM_SET_CURRENT_BRAKE = 7
COMM_SET_RPM = 8
COMM_ALIVE = 30

FAULTS = {0: 'NONE', 1: 'OVER_VOLTAGE', 2: 'UNDER_VOLTAGE', 3: 'DRV', 4: 'ABS_OVER_CURRENT',
          5: 'OVER_TEMP_FET', 6: 'OVER_TEMP_MOTOR', 7: 'GATE_DRIVER_OVER_VOLTAGE',
          8: 'GATE_DRIVER_UNDER_VOLTAGE', 9: 'MCU_UNDER_VOLTAGE', 10: 'BOOTING_FROM_WATCHDOG_RESET',
          11: 'ENCODER_SPI', 12: 'ENCODER_SINCOS_BELOW_MIN_AMPLITUDE',
          13: 'ENCODER_SINCOS_ABOVE_MAX_AMPLITUDE', 14: 'FLASH_CORRUPTION'}


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def frame(payload):
    n = len(payload)
    head = bytes([2, n]) if n <= 255 else bytes([3, n >> 8, n & 0xFF])
    return head + payload + struct.pack('>H', crc16(payload)) + b'\x03'


class Deframer:
    """Feed bytes, yields complete payloads with a valid CRC."""
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            while self.buf and self.buf[0] not in (2, 3):
                del self.buf[0]
            if len(self.buf) < 3:
                break
            if self.buf[0] == 2:
                n, h = self.buf[1], 2
            else:
                n, h = (self.buf[1] << 8) | self.buf[2], 3
            total = h + n + 3
            if len(self.buf) < total:
                break
            payload = bytes(self.buf[h:h + n])
            crc = (self.buf[h + n] << 8) | self.buf[h + n + 1]
            if self.buf[total - 1] == 3 and crc16(payload) == crc:
                out.append(payload)
                del self.buf[:total]
            else:
                del self.buf[0]          # resync
        return out


def parse_values(p):
    """COMM_GET_VALUES reply (payload starts with the command byte)."""
    if not p or p[0] != COMM_GET_VALUES or len(p) < 54:
        return None
    i = 1
    def f16(scale):
        nonlocal i; v = struct.unpack_from('>h', p, i)[0] / scale; i += 2; return v
    def f32(scale):
        nonlocal i; v = struct.unpack_from('>i', p, i)[0] / scale; i += 4; return v
    d = {}
    d['temp_fet_c'] = f16(10)
    d['temp_motor_c'] = f16(10)
    d['motor_current_a'] = f32(100)
    d['input_current_a'] = f32(100)
    f32(100); f32(100)                       # id, iq
    d['duty'] = f16(1000)
    d['erpm'] = f32(1)
    d['v_in'] = f16(10)
    d['amp_hours'] = f32(1e4); d['amp_hours_charged'] = f32(1e4)
    d['watt_hours'] = f32(1e4); d['watt_hours_charged'] = f32(1e4)
    d['tacho'] = f32(1); d['tacho_abs'] = f32(1)
    d['fault'] = p[i] if i < len(p) else 0
    d['fault_name'] = FAULTS.get(d['fault'], str(d['fault']))
    return d


def cmd_rpm(erpm):
    return frame(struct.pack('>Bi', COMM_SET_RPM, int(erpm)))


def cmd_current(a):
    return frame(struct.pack('>Bi', COMM_SET_CURRENT, int(a * 1000)))


def cmd_brake(a):
    return frame(struct.pack('>Bi', COMM_SET_CURRENT_BRAKE, int(a * 1000)))


def cmd_get_values():
    return frame(bytes([COMM_GET_VALUES]))


class Vesc:
    """Background thread: every 1/keepalive_hz resend the current command, then poll values.

    command is one of ('rpm', erpm), ('current', A), ('brake', A). Sending it periodically is the
    keepalive: set the VESC app timeout (App Settings > General > Timeout) to ~500 ms so the motor
    stops if this program or the link dies."""
    def __init__(self, port, baud, rate_hz, transport=None):
        self.rate = rate_hz
        self.lock = threading.Lock()
        self.command = ('current', 0.0)
        self.values = None
        self.values_t = 0.0
        self.errors = 0
        if transport is None:
            import serial
            transport = serial.Serial(port, baud, timeout=0.02)
        self.ser = transport
        self.deframer = Deframer()
        self.running = True
        self.th = threading.Thread(target=self._run, daemon=True, name='vesc')

    def start(self):
        self.th.start()

    def stop(self):
        self.running = False

    def set_command(self, kind, value):
        with self.lock:
            self.command = (kind, float(value))

    def _send_command(self):
        kind, v = self.command
        if kind == 'rpm':
            self.ser.write(cmd_rpm(v))
        elif kind == 'brake':
            self.ser.write(cmd_brake(v))
        else:
            self.ser.write(cmd_current(v))

    def _run(self):
        period = 1.0 / self.rate
        nxt = time.monotonic()
        while self.running:
            try:
                with self.lock:
                    self._send_command()
                self.ser.write(cmd_get_values())
                t_end = time.monotonic() + min(0.04, period * 0.8)
                got = False
                while time.monotonic() < t_end and not got:
                    data = self.ser.read(256)
                    if data:
                        for p in self.deframer.feed(data):
                            v = parse_values(p)
                            if v:
                                self.values = v
                                self.values_t = time.monotonic()
                                got = True
                if not got:
                    self.errors += 1
            except Exception:
                self.errors += 1
                time.sleep(0.05)
            nxt += period
            dt = nxt - time.monotonic()
            if dt > 0:
                time.sleep(dt)
            else:
                nxt = time.monotonic()
        try:
            self.ser.write(cmd_current(0))
        except Exception:
            pass
