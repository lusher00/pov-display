"""Once-per-revolution pulse input on a GPIO with kernel edge timestamps (libgpiod v1 or v2).

Hall sensor + magnet on the hub, or reflective optical sensor + tape mark. 3.3 V logic into the Pi."""
import threading, time, collections


class PulseBuffer:
    """Hall edges -> once-per-rev index times and rpm.

    positions = magnet positions round the gear (equal spacing); missing = how many of them give no
    pulse (0 or 1). With 5 positions and 1 missing (4 south-out magnets + 1 north-out) the interval
    after the missing one is twice as long; the edge that ends that gap is the index.
    positions = 1 is the plain single-magnet case: every edge is the index."""
    def __init__(self, positions=1, missing=0, n=4000):
        self.positions = max(1, int(positions))
        self.missing = int(missing) if self.positions > 1 else 0
        self.t = collections.deque(maxlen=n)          # index times
        self.edges = collections.deque(maxlen=64)     # raw edge times
        self.normal = collections.deque(maxlen=4)     # recent normal intervals
        self.since_index = 0
        self.pattern_errors = 0
        self.lock = threading.Lock()

    def push(self, t):
        with self.lock:
            if self.edges and t - self.edges[-1] < 0.0005:      # glitch
                return
            prev = self.edges[-1] if self.edges else None
            self.edges.append(t)
            if self.positions == 1:
                self.t.append(t)
                return
            if prev is None:
                return
            dt = t - prev
            if dt > 1.0:                       # rotor was stopped: start the pattern over
                self.normal.clear()
                self.since_index = 0
                return
            if self.missing and len(self.normal) >= 2:
                ref = sorted(self.normal)[len(self.normal) // 2]
                if dt > 1.5 * ref:
                    # end of the gap: index
                    expect = self.positions - self.missing
                    if self.t and self.since_index != expect:
                        self.pattern_errors += 1
                    self.t.append(t)
                    self.since_index = 1
                    return
            self.normal.append(dt)
            self.since_index += 1
            if not self.missing and self.since_index >= self.positions:
                # no gap to find: count edges (index is arbitrary but fixed while running)
                self.t.append(t)
                self.since_index = 0

    def since(self, t0):
        with self.lock:
            return [x for x in self.t if x >= t0]

    def last(self):
        with self.lock:
            return self.edges[-1] if self.edges else None

    def last_index(self):
        with self.lock:
            return self.t[-1] if self.t else None

    def rpm(self, n=2):
        """Rotor rpm from the most recent normal edge intervals (fast), else from index pulses."""
        with self.lock:
            if self.positions > 1 and len(self.normal) >= 2:
                k = list(self.normal)[-min(n, len(self.normal)):]
                dt = sum(k) / len(k) * self.positions
                return 60.0 / dt if dt > 0 else 0.0
            if len(self.t) < 2:
                return 0.0
            ts = list(self.t)[-n - 1:]
        dt = (ts[-1] - ts[0]) / (len(ts) - 1)
        return 60.0 / dt if dt > 0 else 0.0


class OprGpio:
    def __init__(self, chip, line, edge, buf):
        self.chip, self.line, self.edge, self.buf = chip, line, edge, buf
        self.running = True
        self.th = threading.Thread(target=self._run, daemon=True, name='opr')

    def start(self):
        self.th.start()

    def stop(self):
        self.running = False

    def _run(self):
        import gpiod
        if hasattr(gpiod, 'request_lines'):            # libgpiod v2
            from gpiod.line import Edge, Bias
            edge = Edge.RISING if self.edge == 'rising' else Edge.FALLING
            req = gpiod.request_lines(self.chip, consumer='povd-opr', config={
                self.line: gpiod.LineSettings(edge_detection=edge, bias=Bias.PULL_UP)})
            # v2 event timestamps are CLOCK_MONOTONIC by default
            while self.running:
                if req.wait_edge_events(0.2):
                    for ev in req.read_edge_events():
                        self.buf.push(ev.timestamp_ns * 1e-9)
        else:                                          # libgpiod v1 (Raspberry Pi OS bookworm)
            chip = gpiod.Chip(self.chip.replace('/dev/', ''))
            ln = chip.get_line(self.line)
            typ = gpiod.LINE_REQ_EV_RISING_EDGE if self.edge == 'rising' else gpiod.LINE_REQ_EV_FALLING_EDGE
            flags = getattr(gpiod, 'LINE_REQ_FLAG_BIAS_PULL_UP', 0)
            ln.request(consumer='povd-opr', type=typ, flags=flags)
            while self.running:
                if ln.event_wait(sec=0, nsec=200_000_000):
                    ev = ln.event_read()
                    # v1 timestamps are CLOCK_MONOTONIC on kernels >= 5.7
                    self.buf.push(ev.sec + ev.nsec * 1e-9)
