# povd_fw: hub board firmware (ESP32-S3-Zero)

ESP-IDF project. Builds with ESP-IDF v5.3 and v6.1.

First-light firmware: reads the rotor angle from ENC_A, renders a built-in pattern into polar
columns, and clocks all 8 strip channels together by DMA through the LCD_CAM peripheral. Every
setting is a console command with the same name as its config key, and the same keys are on a
web page served over your WiFi. Image upload, OTA and current-based brightness limiting are not
in this version.

## Build and flash from VS Code

1. Install the ESP-IDF extension (Espressif Systems) and run its installer (EIM). Then run
   "ESP-IDF: Select Current ESP-IDF Version".
2. File > Open Folder: `povd/fw/povd_fw`.
3. In the status bar: set the target to `esp32s3`, set the port to the S3-Zero's USB port
   (/dev/cu.usbmodem...), then Build, Flash (UART method), Monitor.

From an ESP-IDF terminal instead:

    idf.py set-target esp32s3        # first time only
    idf.py build flash monitor

The console is on the S3-Zero's USB-C port. Leave the monitor with Ctrl+].

## WiFi and the web page

Join your network once from the console (quote names with spaces); it is saved in flash:

    wifi "MyNetwork" "password"

When it connects the console prints the address. The page is at `http://povd.local` (mDNS;
`hostname` changes the name) or at the IP shown by `wifi` or `status`. On the home network the
board has a reserved address: http://192.168.1.116

The page shows the live status (refreshed every second) and every config key under its own name.
A field applies when you press Enter or leave it, the same as typing the command; the field
outline flashes green when the board accepted it and turns orange with the reason when it did
not. `buck` toggles the strip supply, `save` stores the config in flash. `wifi_pass` is
write-only: it is never sent back to the page.

API, for scripts and the Pi:

    GET  /api/config                 all keys except wifi_pass: [{"k","t","v","lo","hi"}, ...]
    GET  /api/status                 {"rpm","synced","revs",...,"ip"}
    POST /api/set    k=<key>&v=<value>   (also k=buck, k=time)
    POST /api/save

    curl -d 'k=pattern&v=rings' http://192.168.1.116/api/set

Leaving `wifi_ssid` empty turns WiFi off. The web server runs on core 0; the strip output keeps
core 1 to itself.

## Pins

From `hw/povd-hub/povd-hub.kicad_pcb`, U5:

| GPIO | Net | Use |
|---|---|---|
| IO1 | I_IN | INA240 output, ADC1 ch0 (`i`, `status`) |
| IO2 | ENC_B | edge count only (`status`) |
| IO3 | ENC_A | angle pulses, falling edge |
| IO4 | BUCK_EN | 5 V / 15 A strip supply, low at boot |
| IO5 | LCD_PCLK | strip clock, buffered by U7 to CLK1..CLK8 |
| IO6..IO13 | LCD_D0..D7 | strip data, buffered by U6 to DAT1..DAT8 |
| IO14 | (none) | i80 D/C signal the driver requires; not connected on the hub |
| IO43/IO44 | OPT_TX/OPT_RX | UART1 (`uart` loopback test) |

D0 is channel 1 (J2 DAT1) through D7 = channel 8 (J3 DAT8). If `pattern chan` shows the channels
in a different order, the U6 mapping differs from this assumption.

## Console

`help` lists commands. Every config key is a command: `blades` prints it, `blades 4` sets it.
Changes apply at once; `save` stores them in flash, otherwise they are lost at reset.

Commands:

- `show`: all config keys
- `save`, `defaults`, `restart`
- `buck 0|1`: strip supply off/on (BUCK_EN). Off at boot unless `buck_boot 1` is saved.
- `status`: rpm, sync, revs, ENC_A/ENC_B edge counts, columns sent and skipped per second
  (since the last `status`), column period vs bus time, buck state, I_IN
- `i`: I_IN in mV
- `wifi`: network, IP and page address; `wifi <ssid> [password]` joins and saves
- `uart`: sends a string on OPT_TX and checks it arrives on OPT_RX (jumper TP16 to TP17)
- `time hh:mm[:ss]`: sets the time for `pattern clock`
- `view`: prints the rendered image (blade 1, strip 1) as coloured blocks in the terminal

## Config keys

Rotor and strips
- `blades` (4): blades, equally spaced.
- `strips_per_blade` (2): channel c (0-based) is blade c / strips_per_blade, strip
  c % strips_per_blade. With 4 x 2: channels 1-2 blade 1, 3-4 blade 2, 5-6 blade 3, 7-8 blade 4.
  Channels beyond blades x strips_per_blade stay dark.
- `leds_per_strip` (62): LEDs on one channel; chained strips count together.
- `led_pitch_mm` (8.06), `r0_mm` (100): LED i of strip k is at
  r0_mm + (i + k / strips_per_blade) x led_pitch_mm. Extra strips on a blade fill in radially
  between the first strip's LEDs. Set `r0_mm` to the measured radius of the first LED.
- `strip_rev` (0): 1 when the data enters at the tip.

Output
- `columns_per_rev` (360): angular resolution.
- `clk_mhz` (10): strip clock. One column takes (4 + 4 x leds + end bytes) x 8 bus clocks;
  62 LEDs at 10 MHz is 211 us (`t_column_us` in `status`). The column period at the rotor speed
  is 60e6 / rpm / columns_per_rev (`column_period_us`) and must be longer: 500 rpm with 360
  columns gives 333 us. Raise `clk_mhz` or lower `columns_per_rev` when `columns_skipped/s`
  is not 0.
- `bright` (3): SK9822 global brightness, 0..31.
- `pattern` (index): `off`, `index`, `chan`, `rings`, `spokes`, `grid`, `wheel`, `solid`, `clock`.
- `color` (ffffff): RRGGBB for `solid`.

Angle
- `slots` (1): pulse positions per revolution on ENC_A.
- `missing` (0): 1 when one position has no magnet. The gap (a period more than 1.5 x the slot
  period) marks the index; the pulse after it is angle 0. The pulley's 5-1 pattern is
  `slots 5`, `missing 1`.
  With `missing 0`, slot 0 is wherever counting started; `slots 1` is one index pulse per rev.
- `phase_deg` (0): rotates the image. Use `pattern index` (one radial line at angle 0) to line up.
- `mirror` (0): 1 flips the rotation sense if the image comes out mirrored.
- `sim_rpm` (0): above 0, ENC_A pulses are generated internally at this rpm (the real input is
  ignored). On the bench this makes the strips step through columns as if spinning.

Network
- `wifi_ssid`, `wifi_pass`: network to join; empty ssid = WiFi off. `show` prints `(set)` for the
  password.
- `hostname` (povd): mDNS and DHCP name.

The display blanks the strips when there is no sync: no pulse for 3 slot periods, below 30 rpm,
or (with `missing 1`) before the first gap.

## Patterns

- `index`: one radial line at angle 0 (for `phase_deg`)
- `chan`: channel n lights its first n LEDs in its own colour (checks channel order and
  `strip_rev`)
- `rings`: colour bands every 40 mm of radius
- `spokes`: 12 spokes and the rim
- `grid`: 100 mm Cartesian grid, green vertical axis, red horizontal axis
- `wheel`: hue by angle
- `solid`: `color` everywhere
- `clock`: hour ticks and three hands; set the time with `time`

## Bench bring-up order

1. Flash, open the monitor. `status`: buck 0. Meter +5V_LOGIC and +3V3.
2. `buck 1`: D3 lights, TP9 reads 5.0-5.1 V.
3. `sim_rpm 60`, `pattern chan`, `bright 2`, one short strip on channel 1. Scope TP12 (CLK1) and
   TP13 (DAT1): bursts at the column rate.
4. Hall sensor on ENC_A, `sim_rpm 0`, turn the rotor by hand: `status` shows `enc_a_edges`
   counting.

## QEMU (emulator)

Espressif's QEMU runs the firmware on a PC with the console in the terminal. It is for checking
the console, config keys and rendering (`view`), not timing or output:

- QEMU has no LCD_CAM, ADC, PSRAM or WiFi model. The QEMU build (`CONFIG_POVD_QEMU`) leaves WiFi
  and the web page off, builds each column but does not send it, reads I_IN as 0, keeps the image in internal RAM (so `columns_per_rev`
  defaults to 90) and puts the console on UART0.
- QEMU's timers do not run in real time, so `rpm`, `synced` and the column counts in `status`
  are not meaningful there.

Install QEMU once:

    python $IDF_PATH/tools/idf_tools.py install qemu-xtensa
    brew install libgcrypt glib pixman sdl2 libslirp     # macOS libraries QEMU needs

Run it from an ESP-IDF terminal (VS Code: "ESP-IDF: Open ESP-IDF Terminal"):

    ./qemu.sh

which is

    idf.py -B build_qemu -D SDKCONFIG=sdkconfig.qemu.full \
           -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.qemu" qemu monitor

It uses its own build directory and sdkconfig, so it does not disturb the hardware build. Try:

    pattern clock
    time 10:08:30
    view

The QEMU button in the VS Code status bar runs the hardware build, which stops at startup in
QEMU (no LCD_CAM, ADC or PSRAM); use `qemu.sh`.

## Files

- `main/main.c`: startup order (buck off first, config, angle, output, render, console)
- `main/config.c`: config keys, ranges, defaults, NVS storage
- `main/angle.c`: ENC_A pulse handling, missing-pulse index, angle extrapolation, `sim_rpm`
- `main/leds.c`: i80 bus, DMA buffers, column output task (core 1, never blocks while
  displaying), 8x8 bit transpose
- `main/render.c`: patterns and polar mapping, `view`
- `main/board.c`: BUCK_EN, I_IN ADC, OPT UART
- `main/console.c`: commands, and `povd_set()` which the console and the web page both use to
  set and apply a key
- `main/status.c`: status snapshot as console text and JSON
- `main/wifi.c`: station mode, reconnect, mDNS
- `main/web.c`: HTTP server and API; `main/index.html` is the page, embedded at build time
- `components/mdns`: Espressif's mDNS component (v1.15.1, from esp-protocols), copied in so the
  build needs no component download
- `sdkconfig.defaults`: S3-Zero (4 MB flash, 2 MB quad PSRAM), 240 MHz, USB console, 1.5 MB app
  partition (the app with WiFi is about 1 MB). `sdkconfig.defaults` only applies when there is
  no `sdkconfig`: delete `sdkconfig` after changing it.
- `sdkconfig.qemu`: overrides for the QEMU build

## Internals

The image is stored as [column][SK9822 frame byte][channel]: for every byte of the LED frame,
one 64-bit word holds that byte for all 8 channels. The output task watches the angle, and when
it reaches a new column (and the previous DMA transfer has finished) it transposes that column
into an internal-RAM DMA buffer (64 bits in, 8 bus bytes out, MSB first) and starts the transfer.
Columns the rotor passes during a transfer are skipped and counted.

Angle: each ENC_A pulse records its time and slot; between pulses the angle is extrapolated
from the last slot period, capped at the next slot (two slots before the missing one).
