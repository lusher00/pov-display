# Rotor bring-up — bench log

Every run, appended. Scripts are in `../tools/`.

Fixed across all of these unless noted: 29.2 V from one bench supply (30 V / 10 A),
Flipsky 7070 (7 pole pairs), 26T driver / 55T driven XL belt, rotor fitted with
blades, no fairing. VESC fw as reported by `vesc_test.py version`.

## 2026-10-28

Hardware checks, all passed:

| Check | Result |
|---|---|
| A3144 on GPIO4, 5 V supply, 4.7 k pull-up to 3.3 V | HIGH with no magnet; south pole at the branded face pulls LOW; north does nothing |
| Magnets in the 55T pulley | 4 of 5 pockets detected per revolution (index magnet north-out ignored), 31–32 pulses/s at 475 rpm, no missed pulses |
| GY-521 on I2C1 | `i2cdetect` shows 0x68 after `dtparam=i2c_arm=on`; WHO_AM_I 0x68 |
| VESC UART on `/dev/serial0` | `version` answers after `disable-bt`, console off cmdline.txt, getty disabled |

Open-loop and VESC speed-loop runs (`vesc_test.py`):

| cmd | eRPM | duty | Im (A) | Iin (A) | rotor rpm (hall) | note |
|---|---|---|---|---|---|---|
| duty 0.03 | 0 | 0.03 | 0 | 0 | 0 | under 1 V phase, does not start |
| duty 0.10 | 2850 ±100 | 0.10 | 10.8 | 0.49 | — | cogging/belt drag open loop |
| rpm 7000 | 7000 ±5 | 0.219 | 1.35 | 0.24 | 475 | eRPM/rotor = 14.74 = 7 × 2.105 → belt ratio confirmed 55/26 |

## 2026-10-29

Outer loop on rotor rpm (`rotor_speed.py`, kp 2, ki 4):

| target | ramp (rpm/s) | limits | result |
|---|---|---|---|
| 475 | 200 | VESC Tool defaults | at setpoint 260 → Im 17 → 49 A, Iin 4.3 A for a few ms, UNDER_VOLTAGE, VESC dropped the motor, loop recovered and held 475 (err −2 rpm after 15 s, 1.5 A, 8 W) |
| — | — | `limits --store` with wrong field order | max eRPM 8, max duty −30000 stored; motor would not spin. Rewritten with the `commands.c` order. |
| — | — | `limits --store`: batt_max 8, batt_min −1, erpm_max 30000, duty_max 0.95 | written and acknowledged |
| rpm 3000 (VESC loop) | — | as above | hunts 275–4175 eRPM, duty climbing to 0.21; tach rate steady, so the motor is at roughly constant speed and the VESC speed loop is cycling at low speed |
| duty 0.10 | — | as above | 2850 eRPM steady, same as yesterday: observer and motor fine |
| rpm 7000 (VESC loop) | — | as above | 7000 ±4, 1.55 A, 0.28 A in: clean |

## What the map says so far

**The supply, not the VESC, set the first limit.** A bench supply's regulation
loop is tens of ms and its output capacitance is small; a 0.3 → 4 A step sags the
bus until the loop catches up, and the VESC sees it within one PWM cycle. The
supply's meter never showed more than 2 A because it averages. Battery current
max 8 A keeps the VESC from asking for more than the supply has; a 2200–4700 µF
63 V electrolytic at the VESC input covers the supply's response time. Not yet
fitted.

**The VESC speed loop is not usable below about 4000 eRPM** with the current
PID and the sensorless observer. 7000 is clean. `rpm_start` in `povd.conf` is
150 rotor rpm = 2200 eRPM, inside the hunting band; either raise it to ~300 or
tune the VESC speed PID at low speed.

**Belt ratio and pole pairs are confirmed** from the hall count: 7000 eRPM gives
475 rotor rpm. `belt_ratio = 2.115` in `povd.conf`.

**At this ratio and 29.2 V:** 1000 rotor rpm = 14 700 eRPM ≈ 46 % duty; 1500 rpm
= 22 100 eRPM ≈ 69 %. Both fit on one supply; the series pair is for headroom.

## Rejected

- *The loop gains caused the first UNDER_VOLTAGE.* The eRPM command at that
  moment was 4021 against a measured 3080, a modest error; the current spike
  came from the VESC's own speed PID taking its full motor current allowance to
  follow a 200 rpm/s ramp. Same event would happen with `vesc_test.py rpm`
  alone.
