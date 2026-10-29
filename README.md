# povd

Rotor POV LED display: two heli blades, up to 4 clocked LED strips per blade, ESP32-S3 (Waveshare ESP32-S3-Zero) on a hub board, 24 V in through a brush slip ring, quadrature encoder disk for angle.

## Layout

- `docs/hub-board.md`: hub board requirements, power budget, part selection, pin map
- `hw/povd-hub/`: KiCad project for the hub board
- `fw/`: ESP32-S3 firmware (ESP-IDF)
- `pi/`: Pi Zero controller: VESC speed ramp, vibration protection, balancing, web UI (see `pi/README.md`); bring-up results in `pi/BENCH_LOG.md`
- `tools/`: bench scripts for the Pi (hall sensor, MPU-6050, VESC UART, rotor speed loop) and the `hall_check` Arduino sketch
