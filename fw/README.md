# povd firmware

ESP-IDF, ESP32-S3. Planned structure:

- LED output: LCD_CAM i80 peripheral, 8-bit bus, DMA from PSRAM column buffers. D0..D7 are the 8 strip data lines, PCLK is the shared strip clock.
- Angle: PCNT on ENC_A/ENC_B for counts, timer capture for edge period, index from the long high pulse. Column timer = edge period / N, phase re-aligned at each edge.
- Power: BUCK_EN low at boot, enable after self-test; brightness limited from I_IN.
- Wi-Fi: image upload and OTA.
