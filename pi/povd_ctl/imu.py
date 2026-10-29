"""MPU-6050 accelerometer through its FIFO at 1 kHz, with sample timestamps on time.monotonic().

Sample times come from a running linear fit of (FIFO read time, total samples read). That removes the
MPU's own clock error (~1-2 %) and the poll jitter, so samples can be lined up with the once-per-rev
pulse timestamps. Any fixed latency left is the same in every run and cancels in the balance maths."""
import threading, time, collections
import numpy as np

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_FIFO_EN = 0x23
REG_INT_STATUS = 0x3A
REG_USER_CTRL = 0x6A
REG_PWR_MGMT_1 = 0x6B
REG_FIFO_COUNT_H = 0x72
REG_FIFO_R_W = 0x74
REG_WHO_AM_I = 0x75

ODR = 1000.0
RANGES = {2: (0, 16384.0), 4: (1, 8192.0), 8: (2, 4096.0), 16: (3, 2048.0)}


class SampleBuffer:
    """Ring buffer of (sample index, ax, ay, az) plus the index->time fit. Shared by real IMU and sim."""
    def __init__(self, seconds=30, odr=ODR):
        self.n = int(seconds * odr)
        self.data = np.zeros((self.n, 3), np.float32)
        self.total = 0                       # samples ever written since last reset
        self.lock = threading.Lock()
        self.fit_pts = collections.deque(maxlen=400)     # (t_read, total)
        self.a, self.b = 0.0, 1.0 / odr      # t = a + b * index
        self.last_t = 0.0
        self.resets = 0
        self.odr_nom = odr

    def reset(self):
        with self.lock:
            self.total = 0
            self.fit_pts.clear()
            self.resets += 1

    def push(self, samples, t_read):
        """samples: (k,3) in g; t_read: monotonic time when the FIFO count was read."""
        k = len(samples)
        with self.lock:
            if k:
                idx = (self.total + np.arange(k)) % self.n
                self.data[idx] = samples
                self.total += k
            self.fit_pts.append((t_read, self.total))
            self.last_t = t_read
            if len(self.fit_pts) >= 10:
                p = np.array(self.fit_pts)
                t, c = p[:, 0], p[:, 1]
                b = np.polyfit(c, t, 1)[0] if c[-1] - c[0] > 100 else 1.0 / self.odr_nom
                # anchor: the newest sample (index total-1) was taken just before the read
                resid = t - b * (c - 1)
                self.b = b
                self.a = float(np.min(resid))     # earliest-arriving read = least latency
            else:
                self.b = 1.0 / self.odr_nom
                self.a = t_read - self.b * (self.total - 1)

    def window(self, seconds):
        """Return (t, acc[k,3]) for the most recent `seconds`."""
        with self.lock:
            k = min(int(seconds / self.b), self.total, self.n)
            if k <= 0:
                return np.zeros(0), np.zeros((0, 3), np.float32)
            idx0 = self.total - k
            idx = (idx0 + np.arange(k)) % self.n
            acc = self.data[idx].copy()
            t = self.a + self.b * np.arange(idx0, self.total)
            return t, acc

    @property
    def rate(self):
        return 1.0 / self.b if self.b else 0.0


class Mpu6050:
    def __init__(self, bus, addr, range_g, buf):
        from smbus2 import SMBus, i2c_msg
        self.i2c_msg = i2c_msg
        self.bus = SMBus(bus)
        self.addr = addr
        self.sel, self.lsb = RANGES[range_g]
        self.buf = buf
        self.overflows = 0
        self.errors = 0
        self.running = True
        self.th = threading.Thread(target=self._run, daemon=True, name='imu')

    def _w(self, reg, val):
        self.bus.write_byte_data(self.addr, reg, val)

    def _r(self, reg, n):
        return bytes(self.bus.read_i2c_block_data(self.addr, reg, n))

    def init(self):
        who = self._r(REG_WHO_AM_I, 1)[0]
        self._w(REG_PWR_MGMT_1, 0x80); time.sleep(0.1)          # reset
        self._w(REG_PWR_MGMT_1, 0x01); time.sleep(0.05)         # PLL with gyro X clock
        self._w(REG_CONFIG, 0x01)            # DLPF 1: accel 184 Hz BW, internal rate 1 kHz
        self._w(REG_SMPLRT_DIV, 0)           # 1 kHz
        self._w(REG_ACCEL_CONFIG, self.sel << 3)
        self._fifo_reset()
        return who

    def _fifo_reset(self):
        self._w(REG_FIFO_EN, 0x00)
        self._w(REG_USER_CTRL, 0x04)         # FIFO reset
        time.sleep(0.002)
        self._w(REG_USER_CTRL, 0x40)         # FIFO enable
        self._w(REG_FIFO_EN, 0x08)           # accel XYZ into FIFO
        self.buf.reset()

    def start(self):
        self.th.start()

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            try:
                t = time.monotonic()
                st = self._r(REG_INT_STATUS, 1)[0]
                cnt = int.from_bytes(self._r(REG_FIFO_COUNT_H, 2), 'big')
                if st & 0x10 or cnt >= 1020:
                    self.overflows += 1
                    self._fifo_reset()
                    continue
                cnt -= cnt % 6
                raw = bytearray()
                while len(raw) < cnt:
                    n = min(cnt - len(raw), 480)
                    w = self.i2c_msg.write(self.addr, [REG_FIFO_R_W])
                    r = self.i2c_msg.read(self.addr, n)
                    self.bus.i2c_rdwr(w, r)
                    raw += bytes(r)
                s = np.frombuffer(bytes(raw), '>i2').reshape(-1, 3).astype(np.float32) / self.lsb
                self.buf.push(s, t)
            except Exception:
                self.errors += 1
                time.sleep(0.05)
            time.sleep(0.015)
