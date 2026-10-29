"""Web UI: static page + one websocket carrying telemetry out and commands in."""
import asyncio, json, os, time, math
from aiohttp import web

STATIC = os.path.join(os.path.dirname(__file__), 'static')


def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else round(o, 5)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


class Server:
    def __init__(self, ctl, cfg):
        self.ctl, self.cfg = ctl, cfg
        self.app = web.Application()
        self.app.router.add_get('/', self.index)
        self.app.router.add_get('/ws', self.ws)
        self.app.router.add_static('/static', STATIC)
        self.socks = set()

    async def index(self, req):
        return web.FileResponse(os.path.join(STATIC, 'index.html'))

    def _update_clients(self):
        self.ctl.clients = len(self.socks)
        if not self.socks:
            self.ctl.no_client_since = time.monotonic()

    async def ws(self, req):
        ws = web.WebSocketResponse(heartbeat=5.0)
        await ws.prepare(req)
        self.socks.add(ws)
        self._update_clients()
        try:
            await self._send(ws, dict(type='config', items=self.cfg.describe()))
            await self._send(ws, dict(type='hist', points=list(self.ctl.hist), full=True))
            await self._send(ws, dict(type='events', items=list(self.ctl.events)))
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                    r = self.handle(m)
                except Exception as e:
                    r = dict(error=repr(e))
                await self._send(ws, dict(type='reply', id=m.get('id') if isinstance(m, dict) else None, result=r))
        finally:
            self.socks.discard(ws)
            self._update_clients()
        return ws

    def handle(self, m):
        c, ctl = m.get('cmd'), self.ctl
        if c == 'run':
            return ctl.start_run(m['rpm_target'], m.get('ramp_rate_rpm_s'))
        if c == 'hold':
            return ctl.hold()
        if c == 'resume':
            return ctl.resume()
        if c == 'stop':
            return ctl.stop()
        if c == 'estop':
            return ctl.estop()
        if c == 'reset':
            return ctl.reset()
        if c == 'set':
            with ctl.lock:
                v = self.cfg.set(m['key'], m['value'])
            if m.get('save', True):
                self.cfg.save()
            asyncio.get_event_loop().create_task(self.broadcast(dict(type='config', items=self.cfg.describe())))
            return dict(key=m['key'], value=v)
        if c == 'bal_run':
            return ctl.bal_start(m['label'])
        if c == 'bal_fit':
            return ctl.bal_fit(float(m['grams']), float(m['deg']), m.get('remove', False))
        if c == 'bal_compute':
            return ctl.bal_compute(float(m['trial_g']), float(m['trial_deg']))
        if c == 'bal_trim':
            return ctl.bal_trim()
        if c == 'bal_clear':
            return ctl.bal_clear()
        return dict(error='unknown cmd %r' % c)

    async def _send(self, ws, obj):
        try:
            await ws.send_str(json.dumps(_clean(obj), separators=(',', ':')))
        except Exception:
            pass

    async def broadcast(self, obj):
        for ws in list(self.socks):
            await self._send(ws, obj)

    async def pump(self):
        last_hist_t = self.ctl.hist[-1]['t'] if self.ctl.hist else 0
        last_ev_t = self.ctl.events[-1][0] if self.ctl.events else 0
        k = 0
        while True:
            await asyncio.sleep(0.1)
            k += 1
            with self.ctl.lock:
                snap = self.ctl.snapshot() if self.socks else None
                new = [h for h in list(self.ctl.hist)[-20:] if h['t'] > last_hist_t]
                evs = [e for e in list(self.ctl.events) if e[0] > last_ev_t]
                spec = self.ctl.spec if k % 5 == 0 else None
            if new:
                last_hist_t = new[-1]['t']
            if evs:
                last_ev_t = evs[-1][0]
            if not self.socks:
                continue
            await self.broadcast(dict(type='snap', **snap))
            if new:
                await self.broadcast(dict(type='hist', points=new))
            if evs:
                await self.broadcast(dict(type='events', items=evs))
            if spec:
                await self.broadcast(dict(type='spec', **spec))

    async def run(self, port):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        await self.pump()
