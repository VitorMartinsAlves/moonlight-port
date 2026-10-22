#!/usr/bin/env bash
set -euo pipefail
command -v ffmpeg >/dev/null || { echo 'Instale ffmpeg.'; exit 1; }
command -v ydotool >/dev/null || echo 'Aviso: instale/configure ydotool para enviar teclas em Wayland.'
# PipeWire input availability depends on how FFmpeg was built and on the capture node ID.
# Set MOONLIGHT_PIPEWIRE_SOURCE to the actual node ID if it is not 0.
python3 bridge.py --capture pipewire --pipewire-source "${MOONLIGHT_PIPEWIRE_SOURCE:-0}" --input-backend ydotool --port 8790
