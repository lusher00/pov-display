# povd_ctl: rotor controller on the Pi

Runs on the Pi Zero 2 W next to the rotor:

- Speed control: ramps the VESC in rpm mode from the web UI.
- Protection: watches vibration from an MPU-6050 plus the VESC telemetry, and cuts the ramp or the run when something goes wrong.
- Balancing: single-plane balancing with a vector method (once-per-rev sensor fitted) or a 4-run method (no sensor).
- Web UI: live plots on port 8080.

```
python3 -m povd_ctl                 # real hardware, config in ./povd.conf
python3 -m povd_ctl --sim           # simulated rotor, VESC, IMU and once-per-rev sensor
python3 -m pytest -q tests          # protocol, analysis and balance maths
```

Every setting is a key in `povd.conf`. The same key names are used as labels in the UI, in the CSV log headers and in the websocket messages.

## Wiring

| Pi pin | To |
|---|---|
| GPIO14 TXD (pin 8) | VESC UART RX |
| GPIO15 RXD (pin 10) | VESC UART TX |
| GND (pin 6) | VESC GND (UART connector) |
| 3.3 V (pin 1) | GY-521 (MPU-6050) VCC |
| GPIO2 SDA (pin 3) / GPIO3 SCL (pin 5) | GY-521 SDA / SCL |
| GND (pin 9) | GY-521 GND |
| 5 V (pin 2), GND | A3144 hall sensor VCC, GND (needs 4.5 V minimum; 100 nF across it at the sensor) |
| GPIO4 (pin 7) | A3144 OUT (open collector), 4.7 k pull-up to **3.3 V** (pin 1), never to 5 V; `opr_line = 4`, `opr_edge = falling` |

Pin 1 is the square pad at the SD-card end of the header, inner row; even pins are the outer (board-edge) row.

- The VESC UART is 3.3 V logic. Use no level shifter.
- GY-521: leave XDA, XCL, AD0 and INT open (AD0 open = address 0x68). The on-board regulator accepts 3.3 V or 5 V on VCC; the I2C pull-ups are to 3.3 V either way.
  - Mount it on the bearing or motor plate, not the base.
  - One axis must lie in the rotor plane, perpendicular to the shaft; set that axis in `imu_axis`. `tools/mpu_watch.py` shows which axis moves.
  - Keep its wires short.
- A3144: output goes low when a **south** pole faces the branded (flat, printed) side; a north pole does nothing. GPIO4 is also the default 1-Wire pin, so `dtoverlay=w1-gpio` must not be in config.txt.
- Once-per-rev: the big gear (`beltsolve/55ToothXL.scad`) has five 6 × 3 mm magnet pockets in the rim on its back face.
  - Fit four magnets south pole out, and the index pocket's magnet north pole out. The A3144 ignores the north-out one, so each revolution gives 4 pulses and one double-length gap (confirmed on the bench: 4 of 5 pockets detected).
  - The pulse that ends the gap is the once-per-rev index. `opr_positions = 5` and `opr_missing = 1` tell the software this.
  - A single magnet also works: set `opr_positions = 1` and `opr_missing = 0`.
  - Mount the sensor, branded side toward the gear, facing the back face at the pocket radius (echoed by OpenSCAD), 1–3 mm from it. Twist the three wires together and route them away from the motor phase wires.
  - `opr_pattern_errors` in the UI counts revolutions whose pulse count was wrong. It should stay at 0.

## Pi setup (Raspberry Pi OS bookworm, rp0-pov-0)

```
sudo apt install python3-numpy python3-aiohttp python3-serial python3-smbus2 python3-libgpiod python3-gpiozero i2c-tools
```

`/boot/firmware/config.txt` (above any `[pi4]`-style section header, or under `[all]`):

```
dtparam=i2c_arm=on
dtparam=i2c_arm_baudrate=400000
enable_uart=1
dtoverlay=disable-bt
```

Take the login console off the UART, then reboot:

```
sudo sed -i 's/console=serial0,115200 //' /boot/firmware/cmdline.txt
sudo systemctl disable --now serial-getty@ttyS0 serial-getty@ttyAMA0
sudo systemctl disable hciuart
sudo reboot
```

Check: `ls -l /dev/serial0` points at `ttyAMA0` (not `ttyS0`), `sudo fuser -v /dev/ttyAMA0` prints nothing, `i2cdetect -y 1` shows `68`.

`disable-bt` gives the GPIO header the full UART, and turns off Bluetooth; Wi-Fi is not affected. On the Zero the full UART otherwise belongs to Bluetooth, and `/dev/serial0` is a mini UART whose baud rate moves with the CPU clock. A getty left on the port shows up in pyserial as "device reports readiness to read but returned no data".

Run at boot:

```
sudo cp systemd/povd-ctl.service /etc/systemd/system/
sudo systemctl enable --now povd-ctl
```

The unit assumes the repo is at `/home/pi/povd` and the user is `pi`; edit it if not.

## Bench scripts (`../tools/`)

Stand-alone checks for each piece of hardware, no `povd_ctl` needed. `scp` them to the Pi's home directory; `rotor_speed.py` imports `vesc_test.py` from the same directory. Results are logged in `BENCH_LOG.md`.

| Script | |
|---|---|
| `hall_watch.py [--quiet]` | prints every A3144 edge, then once a second pulses/s, magnet pitch and rotor rpm; hand test for magnet polarity |
| `mpu_watch.py [--hz 50] [--range 8]` | WHO_AM_I check, accel in g, gyro in °/s, temperature |
| `vesc_test.py version \| values \| duty D \| rpm E \| current A \| brake A \| stop \| limits` | raw VESC UART protocol (no pyvesc); timed holds resend at 20 Hz and finish with current 0 |
| `rotor_speed.py RPM --seconds S [--ramp_rpm_s R]` | outer loop: rotor rpm from the magnets, eRPM command to the VESC; feedforward `pole_pairs × belt_ratio` plus PI trim; stops on loss of hall pulses |

`vesc_test.py limits [--store]` writes the VESC's limit fields over UART with `COMM_SET_MCCONF_TEMP`: motor-current scale (0–1 on the Motor Current Max set in VESC Tool), battery current max / regen, max eRPM, max duty, max watts. Defaults: `batt_max 8`, `batt_min -1`, `erpm_max 30000`, `duty_max 0.95`. Try without `--store` first; the field order is from `commands.c` and a wrong payload stored to flash leaves the motor unable to spin until it's rewritten.

## VESC Tool settings

- **App Settings > General > App to Use:** UART. **UART baud:** 115200 (= `vesc_baud`).
- **App Settings > General > Timeout:** 500 ms; **Timeout Brake Current:** 0 A. The Pi resends the rpm command `keepalive_hz` times a second. If the Pi, the program or the UART stops, the VESC releases the motor after 500 ms.
- **Motor Settings > General > Max ERPM:** set to `rpm_max × belt_ratio × motor_pole_pairs` plus a margin. This is a hard ceiling that doesn't depend on the Pi.
- **Battery current min (regen):** if the VESC runs from a power supply rather than a battery, set this close to 0 (`tools/vesc_test.py limits --batt_min -1 --store` does it over UART). Regen on a stop or a trip will otherwise push the supply voltage up. Leave `trip_action` and `trip_hard_action` as `ramp_down` / `coast` unless the supply can absorb regen.
- **Battery current max:** below the bench supply's current limit (8 A for a 10 A supply) so the VESC limits itself before the supply folds back and the bus sags into UNDER_VOLTAGE.
- Tune the speed PID (Motor Settings > PID Controllers) so the rotor follows `ramp_rate_rpm_s` without overshoot.

## Speed and protection

**Modes:** `idle`, `run`, `stop`, `trip`.

- **Run** ramps `rpm_cmd` toward `rpm_target`:
  - starts from `rpm_start`;
  - goes up at `ramp_rate_rpm_s` and down at `decel_rpm_s`.
- **Stop** ramps down to `rpm_release`, then sets 0 A so the rotor coasts.

| Condition | Key | Action |
|---|---|---|
| 1x vibration amplitude | `vib_1x_limit_g` | soft trip |
| Broadband RMS 2–200 Hz | `vib_rms_limit_g` / `vib_hard_limit_g` | soft / hard trip |
| Largest non-synchronous peak (ground resonance, flutter, loose parts) | `vib_nonsync_limit_g` | soft trip |
| Non-synchronous peak growing exponentially | `vib_growth_limit_s` | soft trip |
| 1x rising faster than rpm^N while ramping (resonance ahead) | `vib_1x_slope_limit` | ramp pauses: Resume (pause disabled until next Run) or Stop |
| rpm not following the command | `rpm_track_err_pct`, `rpm_track_time_s` | soft trip |
| Motor current for 0.5 s | `motor_current_limit_a` | soft trip |
| FET / motor temperature | `temp_fet_limit_c`, `temp_motor_limit_c` | soft trip |
| VESC fault code, VESC telemetry lost | | hard trip |
| Accelerometer data lost | `sensor_timeout_s` | soft trip |
| Once-per-rev pulses missing | `opr_timeout_revs` | soft trip |
| No browser connected while running | `ui_deadman_s` | soft trip |
| E-STOP button | | hard trip |

**Trip actions:**
- Soft trips use `trip_action`:
  - `ramp_down` (default): decelerate at `decel_rpm_s`, then coast.
  - `coast`: 0 A.
  - `brake`: `brake_current_a`.
- Hard trips use `trip_hard_action`: `coast` (default) or `brake`.
- A trip latches. Reset trip is accepted once the rotor is below `rpm_release`.

Use **Stop** or **E-STOP** to leave a resonance. Ground resonance is limited to a speed band, so dropping rpm ends it; holding speed inside it does not.

Every run writes a CSV to `log_dir`, at 4 rows/s. The columns are the same keys as the UI.

## Balancing

Masses go at `balance_radius_mm`. Angles are in degrees, measured in the direction of rotation:
- with a once-per-rev sensor: from the magnet;
- without one: from any reference you choose (e.g. blade 1), used the same way every time.

All runs are made at `balance_rpm`. The sequence for each run:
1. spin up;
2. wait `balance_settle_s`;
3. average `balance_avg_s`;
4. stop so you can fit masses.

After fitting or removing any mass, enter it under **Record fitted**, so the record of what was on the rotor stays correct.

**With once-per-rev (vector method):**
1. Run baseline.
2. Fit a trial mass (`trial_g` at `trial_deg`) and record it.
3. Run trial. The trial should change the 1x vector by 20–100 %; the result shows this.
4. Compute. Either remove the trial and fit the correction, or leave the trial on and fit the alternative mass shown.
5. Run check.
6. The influence coefficient is saved in `balance.json`. From then on, one Run check plus Trim gives the next correction directly. This stays valid while `balance_rpm` and the mount don't change.

**Without once-per-rev (4-run method):**
1. Run baseline.
2. With the same trial mass at `trial_deg`, `trial_deg+120` and `trial_deg+240`, run trial_a, trial_b and trial_c.
3. Remove the trial and Compute.

`balance_positions_deg` (e.g. `0,90,180,270`) splits the correction onto the two fixed positions on either side of it.

In simulation, Record fitted applies the mass to the simulated rotor. The simulated unbalance is 1.2 g at 250° (at 100 mm) to cancel.

## Simulator

`--sim` replaces the hardware with a model:
- 1.2 g unbalance at 100 mm;
- a 4 Hz rigid-body mount mode and a 27.5 Hz structural mode, peaking near 1650 rpm;
- an unstable non-synchronous mode between 1700 and 1850 rpm;
- 9 mg sensor noise.

The simulated VESC is driven through the real UART protocol code. Use it to try the trip limits and the balance procedure before the rotor is built.

## Files

| File | |
|---|---|
| `povd_ctl/vesc.py` | VESC UART protocol and poll / keepalive thread |
| `povd_ctl/imu.py` | MPU-6050 FIFO reader, sample timestamps |
| `povd_ctl/opr.py` | once-per-rev GPIO edges (libgpiod v1 and v2) |
| `povd_ctl/analysis.py` | 1x lock-in, spectrum, RMS, non-synchronous peak, growth and slope estimators |
| `povd_ctl/balance.py` | vector and 4-run balancing, split onto fixed positions |
| `povd_ctl/controller.py` | modes, ramp, trips, balance-run sequencing, CSV log |
| `povd_ctl/web.py`, `static/index.html` | aiohttp server and the UI |
| `povd_ctl/sim.py` | simulator |
