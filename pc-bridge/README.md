# PC bridge

See the parent kit's README. This helper captures the local desktop with FFmpeg, publishes HLS over HTTP on port 8790, and translates Roku remote keys into desktop keyboard events.

It does not connect to Sunshine nor implement the Moonlight/GameStream protocol. It is a practical, experimental alternative for the Roku runtime.

Quick start on Linux/X11:

```bash
sudo pacman -S ffmpeg xdotool
python3 bridge.py --capture x11 --port 8790
```

Quick start on Windows: install FFmpeg, ensure `ffmpeg` is in PATH, then run `run-windows.bat`.
