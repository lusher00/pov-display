#!/bin/sh
# Build the QEMU variant and run it with the console in this terminal.
# Run from an ESP-IDF terminal (VS Code: Command Palette -> "ESP-IDF: Open ESP-IDF Terminal").
# Quit with Ctrl+].
cd "$(dirname "$0")"
idf.py -B build_qemu -D SDKCONFIG=sdkconfig.qemu.full -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.qemu" qemu monitor
