"""povd rotor controller: python3 -m povd_ctl [--conf povd.conf] [--sim]"""
import argparse, asyncio, os, sys, signal, time
from .config import Config
from .imu import SampleBuffer, Mpu6050
from .opr import PulseBuffer, OprGpio
from .vesc import Vesc
from .controller import Controller
from .web import Server


def main():
    ap = argparse.ArgumentParser(description='povd rotor speed control, vibration protection and balancing')
    ap.add_argument('--conf', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'povd.conf'))
    ap.add_argument('--sim', action='store_true', help='simulated VESC, IMU and once-per-rev sensor')
    ap.add_argument('--port', type=int, help='override web_port')
    a = ap.parse_args()
    cfg = Config(a.conf)
    if not os.path.exists(cfg.path):
        cfg.save()
    imu_buf = SampleBuffer()
    opr_buf = PulseBuffer(cfg['opr_positions'], cfg['opr_missing'])
    sim = None
    if a.sim:
        from .sim import SimRotor, SimSerial
        sim = SimRotor(cfg, imu_buf, opr_buf if cfg['opr_line'] >= 0 else None)
        opr_enabled = cfg['opr_line'] >= 0
        vesc = Vesc(None, None, cfg['keepalive_hz'], transport=SimSerial(sim))
        sim.start()
    else:
        vesc = Vesc(cfg['vesc_port'], cfg['vesc_baud'], cfg['keepalive_hz'])
        imu = Mpu6050(cfg['imu_bus'], cfg['imu_addr'], cfg['imu_range_g'], imu_buf)
        who = imu.init()
        print('MPU WHO_AM_I 0x%02x' % who)
        imu.start()
        opr_enabled = cfg['opr_line'] >= 0
        if opr_enabled:
            OprGpio(cfg['opr_chip'], cfg['opr_line'], cfg['opr_edge'], opr_buf).start()
    vesc.start()
    ctl = Controller(cfg, vesc, imu_buf, opr_buf, opr_enabled, sim=sim)
    ctl.start()
    srv = Server(ctl, cfg)
    port = a.port or cfg['web_port']
    print('povd_ctl on http://0.0.0.0:%d %s' % (port, '(SIMULATION)' if sim else ''))

    def shutdown(*_):
        vesc.set_command('current', 0.0)
        time.sleep(0.2)            # let the VESC thread send it
        vesc.stop()
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        asyncio.run(srv.run(port))
    except KeyboardInterrupt:
        shutdown()


if __name__ == '__main__':
    main()
