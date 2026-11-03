# POVD Rotor Simulator

`povd-sim.html` is a single-file model of the rotor display. Open it in a browser; no server,
no dependencies. It shows what a viewer sees from the front, one blade's strip layout, a readout
of resolution, timing, power and load, and can run a scripted sequence.

Every control is labelled with its config key. The same names are used here, in the readout and
in sequences.

## What it models

The rotor has `blades` identical blades, each carrying `strips_per_blade` LED strips of
`leds_per_strip` LEDs at `led_pitch_mm`, starting `r0_mm` from the axis. Each blade paints the
same image, so a column is painted `blades` times per revolution and the refresh rate is
`rpm / 60 * blades`.

The source image is a 512 x 512 canvas (test pattern, uploaded image, or animated GIF). It is
resampled into polar form once per geometry change: for each of `columns_per_rev` columns and each
LED, the source pixel at that radius and angle. The LED colour is read from the current source
frame at paint time, so GIFs animate without recomputing geometry.

The display is a persistence image: each frame the blades sweep some angle and every column they
crossed is painted; the whole image then decays with the viewer's eye time constant `persist_ms`.
The blades themselves are drawn on top with each LED lit in the colour it shows at its current
column.

Nothing here models the angle estimator, the data link or the power supply dynamics; those are
numbers in the readout, not simulated behaviour.

## Config keys

Rotor
- `blades`: number of blades, equally spaced.
- `blade_len_mm`: blade length from the hub.
- `chord_mm`: blade width; the strips must fit across it (the blade drawing warns if not).
- `r0_mm`: radius of the first LED.
- `rpm`: rotor speed.

Strips
- `strips_per_blade`, `leds_per_strip`, `led_pitch_mm`, `strip_w_mm`: strip geometry. A 0.5 m
  strip of 62 LEDs has an 8.06 mm pitch.
- `strip_g_per_m`: strip mass, for the load figures.
- `strip_mode`: what extra strips on a blade are used for.
  - `radial`: strips staggered along the blade by pitch/n; finer radial pixels.
  - `angular`: strips phased by a fraction of a column; more columns per revolution.
  - `duplicate`: strips carry the same pixels; brighter, no extra resolution.

Spin
- `spin`: animate. Off shows the complete image.
- `spin_slowdown`: playback divisor. 1 is real time; 250 shows 500 rpm at 2 rpm. The rotor speed
  the viewer sees is `rpm / spin_slowdown` (readout `rpm_shown`).
- `persist_ms`: the viewer's eye persistence in wall-clock milliseconds. About 60 for a human.
  Because it is in viewer time, slowing playback down with `spin_slowdown` shows the LEDs chasing,
  and speeding it up lets persistence of vision form the image, the same as watching the real
  rotor spin up. 0 means the trail never fades.
- `display_hz`: your monitor's refresh rate. 0 measures it from the browser's frame rate (the
  page watches requestAnimationFrame for a second and takes the median period). Set it only when
  the measurement is wrong, for example on a variable-rate display. The readout says which is in
  use: `(measured)`, `(set)`, or `(assumed)` if no measurement has completed yet (60 is assumed).

Timing
- `columns_per_rev`: angular resolution of the frame.
- `clk_mhz`: LED strip clock.
- `channels`: strip outputs per hub board.

Power
- `led_ma_full`: current per LED at full white.
- `img_avg_pct`: mean drive level of a typical image, for the "typical" figures.
- `boards`: hub boards on the rotor.
- `rail_a`: 5 V rating per board.
- `rotor_v`: voltage delivered through the slip ring.
- `buck_eff`: 5 V converter efficiency.
- `ring_a_max`: slip ring current rating.

## Readout

Orange means over a limit; green means inside it.

- `display_dia_mm`: 2 x (r0 + blade length).
- `refresh_hz`: rpm/60 x blades. Orange under 24.
- `rpm_shown`: rpm / spin_slowdown, the speed on screen.
- `display_hz_used`: refresh rate the simulation steps at, and where it came from.
- `deg_per_frame`: rotor degrees per display frame at the shown speed. Above about 10 the blade
  looks stroboscopic on screen; the painted image is still correct because every column swept
  between frames is painted.
- `radial_px`: distinct radii with an LED on them.
- `angular_cols`: columns per revolution after strip_mode.
- `tip_col_pitch_mm`: arc length of one column at the tip. Should be at or below the LED pitch.
- `radial_pitch_mm`: effective radial pixel pitch.
- `front_face_leds`: LEDs on the rotor.
- `strips_per_channel`: strips chained on one output when there are more strips than channels.
- `t_column_us`: time to clock one column out, against the time budget per column at this rpm.
  Orange when the chain can't keep up.
- `max_columns_at_rpm`: columns the chain could support at this rpm.
- `i5_full_white_a`, `i5_typical_a`: 5 V current at full white and at img_avg_pct.
- `rail_cap_a`: boards x rail_a.
- `brightness_cap_pct`: the global brightness the firmware would have to apply to keep a typical
  image under the rail rating.
- `p5_typical_w`: 5 V power of a typical image.
- `i_ring_typical_a`, `i_ring_at_cap_a`: slip ring current at typical load and at the rail cap.
- `strip_len_m`, `mass_per_blade_g`: strip length and strip mass per blade. Orange if the strip is
  longer than the blade.
- `g_at_tip`: centripetal acceleration at the tip, in g.
- `f_strip_pull_n`, `f_blade_pull_n`: centrifugal pull of one strip and of all strips on one blade,
  taken at the strip's mid radius.

## Images

`test grid`, `text`, `rings` are built-in patterns. `image` loads a file: JPEG and PNG are scaled
to cover the square; an animated GIF is decoded into frames (Chrome, Edge and Safari 17+) and
plays at its own frame delays. Only the circle the blades sweep is shown, so crop the subject to
the centre.

## Sequences

The Sequence card runs a timed list of changes, in wall-clock seconds from pressing `run`:

    [
     {"t":0,  "set":{"blades":2,"strips_per_blade":1,"spin_slowdown":250}, "pattern":"grid"},
     {"t":4,  "set":{"spin_slowdown":60}},
     {"t":10, "set":{"spin_slowdown":1}},
     {"t":14, "pattern":"rings"},
     {"t":20, "load":"assets/retriever.jpg"}
    ]

- `set`: any config keys, written as if typed into the fields. The image is kept; the geometry is
  rebuilt in place.
- `pattern`: `grid`, `text` or `rings`.
- `load`: an image or GIF by URL. Relative URLs work when the page is served over http (for
  example `python3 -m http.server` in this folder) or published; a page opened as a file can't
  fetch other files, so use the `image` button there instead.

`sequence file` loads a JSON file into the box. The default text in the box is the build-up
sequence (chasing LEDs, POV takes over, rings flicker, text, more strips, more blades).

The same runner is available to scripts as `window.povd`:

- `povd.set({key: value, ...})`: write config keys, keep the image and angle.
- `povd.pattern.grid()` / `.text()` / `.rings()`.
- `povd.load(url)`: image or GIF.
- `povd.run(entries)`, `povd.stopSequence()`.
- `povd.reset()`: clear the trail and angle.
- `povd.step(dt_ms)`: advance one frame by dt milliseconds of wall time, deterministic. Used by the
  frame renderer so a video can be produced faster or slower than real time.
- `povd.stop()`: stop the animation loop (so `step` can drive it).
- `window.POVD_INIT = {key: value, ...}` set before the page's script runs (for example from a
  Playwright `addInitScript`) presets the config before the first draw, so a recording starts in
  the wanted state with nothing typed on camera.

Field edits apply on commit (Enter, Tab or leaving the field) or 600 ms after the last keystroke,
never per keystroke, so typing `120` into a field does not pass through `1` and `12`. While the
rotor is spinning, an edit rebuilds the geometry in place and keeps the trail and angle.

## Rendering a video

`demo/render_demo.js` renders a timeline frame by frame through `povd.step` and writes JPEGs for
ffmpeg; the timeline is `cfgAt(t)` in the file. `demo/screencast.js` records the whole page in
real time with a visible cursor operating the controls; the storyboard is the list of `field`,
`click`, `file` and `divisor` calls at the bottom, and the start state is the `POVD_INIT` object
near the top. The storyboard as written: 2 blades, 1 strip, grid, divisor 250 (LEDs chasing);
strips 2, 3, 4, 1 while still slow; divisor stepped down to 1 (the grid appears); rings and
divisor 2, 4 (flicker); text and divisor 1; the retriever photo; three GIFs, each with the divisor
run up to 8 and back to 1; then at divisor 2.5: strips 2, blades 3, 4, 2, strips 3, 4, blades 3, 4. Both need node, playwright and ffmpeg:

    brew install node ffmpeg
    cd demo && npm init -y && npm install playwright && npx playwright install chromium
    node screencast.js ../povd-sim.html cast assets
    ffmpeg -ss 0.8 -i cast/screencast.webm -c:v libx264 -crf 24 -pix_fmt yuv420p -movflags +faststart screencast.mp4

A headless browser renders in software, so a heavy scene (4 blades, 4 strips, GIF source) can run
slower than real time and the recording stretches. On a Mac with a GPU the page itself keeps up.

## Internals, for editing

- `ledLayout(c)`: list of LEDs on one blade: radius, angular offset, chord position.
- `prepare()`: builds `frame`: per column, the source byte index and the pixel position of every
  LED. Called whenever a config key changes.
- `paintColumn(f, col)`: writes one column's LEDs into the trail pixel buffer.
- `fadeTrail(a)`: multiplies the trail by (1 - a).
- `step(dtReal)`: fade, advance the angle, paint the swept columns (each column at most once per
  frame), advance a GIF, compose trail + hub + blades.
- `tick(ts)`: requestAnimationFrame loop; measures the display rate, clamps a stalled tab to three
  frames, runs the sequence.
- `readout(c, L)`: the numbers.

Pixel budget: the trail is a 700 x 700 RGBA buffer; a column paint is leds x dot-area writes and
a fade is one pass over the buffer, so the worst case (4 blades, 4 strips, 700 rpm) is about
15 ms per frame in software rendering.
