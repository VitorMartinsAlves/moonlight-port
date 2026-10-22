# Moonlight Roku Bridge (experimental)

A Roku SceneGraph sideload prototype and PC helper to view the PC desktop over a local network.

> **Important:** this is not a native Moonlight/GameStream client and does not connect to Sunshine. It captures the PC desktop with FFmpeg and serves HLS, which the Roku Video node can play. HLS buffering adds latency and this does not provide a virtual gamepad, analog sticks, rumble, or audio.

## Repository layout

- `roku-channel/`: Roku SceneGraph channel sources and icons. Zip the *contents* of this directory with `manifest` at the ZIP root for sideloading.
- `pc-bridge/`: Python desktop capture and keyboard input bridge.
- The bridge listens on TCP port `8790` by default.

## Run the PC bridge

Requirements: Python 3.10+ and FFmpeg available in PATH. The platform-specific launcher scripts list optional input tools.

**Windows 10/11**
1. Install FFmpeg and add `ffmpeg.exe` to PATH.
2. Run `pc-bridge/run-windows.bat`.

**Linux/X11 (CachyOS/Arch)**
```bash
sudo pacman -S ffmpeg xdotool
cd pc-bridge
python3 bridge.py --capture x11 --port 8790
```

**Linux/KDE Wayland (experimental)**
```bash
sudo pacman -S ffmpeg ydotool
cd pc-bridge
./run-linux-wayland.sh
```
Wayland capture depends on FFmpeg PipeWire support and the correct PipeWire node ID. This path has not been verified across machines.

The helper prints a six-digit pairing PIN. Keep the terminal open. Permit inbound TCP 8790 only on a trusted private LAN; do not expose this bridge to the internet.

## Build the Roku sideload ZIP

From the repository root:
```bash
cd roku-channel
zip -r ../moonlight-roku-channel.zip manifest source components images
```
Upload `moonlight-roku-channel.zip` using the Roku Development Application Installer. The `manifest` must be at the ZIP root. See [Roku developer setup](https://developer.roku.com/dev/docs/developer-setup).

## Connect

1. Ensure the Roku and PC are on the same trusted LAN.
2. Start the PC bridge and note its LAN IP address and PIN.
3. Launch the Roku app and set the address to `PC-IP:8790`.
4. Test connectivity, pair with the six-digit PIN, and start the stream.
5. Roku remote arrows and OK forward keyboard events; Play/Pause, Rewind, Fast Forward and Replay map to keys.

## Troubleshooting

- Check `http://PC-IP:8790/api/status` from another device on the LAN.
- The bridge serves `/stream/live.m3u8` after streaming starts.
- Check `ffmpeg.log` beside `bridge.py` if capture fails.
- If playback remains black, verify FFmpeg, capture backend, display size and the PC firewall.

## Security and scope

The bridge uses a short PIN for pairing and a generated token for stream control/input commands. The HLS stream is unauthenticated so Roku's native Video node can request segments; run it only on a trusted network.

This is an experimental desktop-to-Roku HLS bridge, not Moonlight. A true client would need to implement the GameStream-compatible control/video/audio/input pipeline and low-latency decode support unavailable through ordinary SceneGraph APIs.