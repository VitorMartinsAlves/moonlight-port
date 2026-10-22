#!/usr/bin/env bash
set -euo pipefail
command -v ffmpeg >/dev/null || { echo 'Instale ffmpeg.'; exit 1; }
command -v xdotool >/dev/null || echo 'Aviso: xdotool não encontrado; vídeo pode funcionar sem controle remoto.'
python3 bridge.py --capture x11 --port 8790
