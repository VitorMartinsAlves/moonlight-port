# Moonlight Roku Bridge (experimental)

A sideloadable Roku SceneGraph app and PC helper for viewing a PC desktop over a local network.

> **Latency limitation:** this is not a native Moonlight/GameStream client and does not connect to Sunshine. The helper captures the desktop with FFmpeg and serves HLS to Roku's native Video node. The updated encoder profile uses 720p60, short 0.5-second segments, a fixed GOP, low-delay H.264 encoding, explicit bitrate limits, and an approximately 32-second rolling playlist window. These changes reduce capture/encode/segmenting overhead, but **they cannot remove the Roku live-player delay**. Roku's media guidance says live playback should remain at least 30 seconds behind the live edge, and its general HLS recommendation is 4–6 second segments. The channel reports the live-edge distance exposed by Roku when available. Do not expect this to be suitable for FPS, racing, or other latency-sensitive games.

Official platform references:
- [Roku streaming media specifications](https://developer.roku.com/dev/docs/media)
- [Roku Video node](https://developer.roku.com/dev/docs/video)
- [FFmpeg HLS muxer](https://ffmpeg.org/ffmpeg-formats.html#hls-2)

## Repository layout

- `roku-channel/`: SceneGraph channel sources and icons. The ZIP needs `manifest` at its root.
- `pc-bridge/`: Python desktop capture, HLS server and keyboard-input bridge.
- TCP port `8790` by default.

## Run the PC bridge

Requirements: Python 3.10+ and FFmpeg available in PATH.

### Windows 10/11
1. Install FFmpeg and add `ffmpeg.exe` to PATH.
2. Run `pc-bridge/run-windows.bat`.

### Linux/X11 (CachyOS/Arch)
```bash
sudo pacman -S ffmpeg xdotool
cd pc-bridge
python3 bridge.py --capture x11 --port 8790
```

### Linux/KDE Wayland (experimental)
```bash
sudo pacman -S ffmpeg ydotool
cd pc-bridge
./run-linux-wayland.sh
```
Wayland capture depends on FFmpeg PipeWire support and the correct PipeWire node ID. Set `MOONLIGHT_PIPEWIRE_SOURCE` if the default source `0` is not correct.

### Experimental tuning
Defaults are `1280x720 @ 60 FPS`, H.264 at `5000k` (maximum `6000k`), `0.5s` HLS segments, and a `64`-segment playlist. This gives the Roku about 32 seconds of available live media while keeping each encoded chunk short.

If the Roku cannot sustain 720p60 or playback stalls, try the more compatible profile:

```bash
python3 bridge.py --capture x11 --width 1280 --height 720 --fps 30 --segment-seconds 1 --hls-list-size 64 --bitrate 3500k --maxrate 4000k --bufsize 1000k
```

The bridge prints a six-digit pairing PIN. Keep the terminal open. Allow inbound TCP 8790 only on a trusted private LAN; do not expose this bridge to the internet.

## Build the Roku sideload ZIP

From the repository root:

```bash
cd roku-channel
zip -r ../moonlight-roku-channel.zip manifest source components images
```

Upload `moonlight-roku-channel.zip` using the Roku Development Application Installer. The `manifest` must be at the ZIP root. See [Roku developer setup](https://developer.roku.com/dev/docs/developer-setup).

## Connect

1. Put the Roku and PC on the same trusted LAN.
2. Start the bridge and note the PC LAN IP and PIN.
3. Launch the Roku app and set the address to `PC-IP:8790`.
4. Test the connection, pair with the six-digit PIN, and start the stream.
5. During playback, the UI shows Roku's reported segment distance from the live edge, where the firmware exposes it. This is **not** a full glass-to-glass measurement.

## Troubleshooting

- Check `http://PC-IP:8790/api/status` from another device on the LAN. The response includes resolution, FPS, bitrate and segment settings.
- The bridge serves `/stream/live.m3u8` after capture starts.
- Check `ffmpeg.log` beside `bridge.py` if capture fails.
- For playback errors, try 30 FPS and 1-second segments. Keep the playlist large enough for Roku's live-playback window.

## Security and scope

The bridge uses a six-digit PIN for pairing and a generated token for stream-control/input commands. HLS segments are unauthenticated so Roku's native Video node can fetch them; only run the bridge on a trusted LAN.

This is an experimental desktop-to-Roku HLS bridge, not Moonlight. A real low-latency client would need a compatible realtime video/audio transport and direct input pipeline that ordinary SceneGraph APIs do not provide. The HLS route is useful as a proof of concept, not for competitive gaming.
