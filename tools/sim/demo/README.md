# povd demo renders

Two ways to make a video from the simulator. Both need node, playwright and ffmpeg (see ../README.md).

- `screencast.js`: records the whole page in real time with a visible cursor operating the controls.
  The storyboard is the list of calls at the bottom of the file. Assets (photo, GIFs) go in `assets/`.

      node screencast.js ../povd-sim.html cast assets
      ffmpeg -ss 0.8 -i cast/screencast.webm -c:v libx264 -crf 24 -pix_fmt yuv420p -movflags +faststart screencast.mp4

- `render_demo.js`: renders only the rotor, frame by frame through `povd.step`, so it is exact
  regardless of machine speed. The timeline is `cfgAt(t)`.

      node render_demo.js ../povd-sim.html frames 30 text
      ffmpeg -framerate 30 -i frames/f%05d.jpg -c:v libx264 -crf 23 -pix_fmt yuv420p -movflags +faststart buildup.mp4
