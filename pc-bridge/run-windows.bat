@echo off
setlocal
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg nao encontrado no PATH. Instale FFmpeg e reabra este terminal.
  pause
  exit /b 1
)
py -3 bridge.py --capture windows --port 8790
pause
