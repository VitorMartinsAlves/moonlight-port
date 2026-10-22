#!/usr/bin/env python3
"""Experimental LAN-to-Roku HLS bridge. This is not a native GameStream client."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STREAM_DIR = ROOT / "stream"
CONFIG_FILE = ROOT / ".bridge-token"

class BridgeState:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.stderr_file = None
        self.started_at: float | None = None
        self.token = self._load_token()
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        self.last_error = ""

    def _load_token(self) -> str:
        if CONFIG_FILE.exists():
            token = CONFIG_FILE.read_text(encoding="utf-8").strip()
            if len(token) >= 32:
                return token
        token = secrets.token_urlsafe(36)
        CONFIG_FILE.write_text(token, encoding="utf-8")
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass
        return token

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def capture_name(self) -> str:
        mode = self.args.capture
        if mode == "auto":
            if os.name == "nt":
                mode = "windows"
            elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
                mode = "pipewire"
            else:
                mode = "x11"
        return mode

    def detect_x11_size(self) -> tuple[int, int]:
        if self.args.capture_width and self.args.capture_height:
            return self.args.capture_width, self.args.capture_height
        xrandr = shutil.which("xrandr")
        if xrandr:
            try:
                result = subprocess.run([xrandr, "--current"], capture_output=True, text=True, timeout=2)
                match = re.search(r"Screen\\s+\\d+:.*?current\\s+(\\d+)\\s+x\\s+(\\d+)", result.stdout, re.S)
                if result.returncode == 0 and match:
                    return int(match.group(1)), int(match.group(2))
            except (OSError, subprocess.SubprocessError):
                pass
        # Fallback keeps explicit user settings usable even without xrandr.
        return self.args.capture_width or self.args.width, self.args.capture_height or self.args.height

    def ffmpeg_input(self) -> list[str]:
        mode = self.capture_name()
        fps = str(self.args.fps)
        if mode == "windows":
            if os.name != "nt":
                raise RuntimeError("O modo windows/gdigrab só funciona no Windows.")
            return ["-f", "gdigrab", "-framerate", fps, "-draw_mouse", "1", "-i", "desktop"]
        if mode == "x11":
            display = os.environ.get("DISPLAY")
            if not display:
                raise RuntimeError("DISPLAY não está definido. Em KDE Wayland, teste a opção pipewire ou entre numa sessão X11.")
            capture_width, capture_height = self.detect_x11_size()
            return ["-f", "x11grab", "-framerate", fps, "-video_size", f"{capture_width}x{capture_height}", "-i", display]
        if mode == "pipewire":
            source = self.args.pipewire_source or os.environ.get("MOONLIGHT_PIPEWIRE_SOURCE", "0")
            return ["-f", "pipewire", "-framerate", fps, "-video_size", f"{self.args.width}x{self.args.height}", "-i", str(source)]
        raise RuntimeError(f"Modo de captura não suportado: {mode}")

    def start(self) -> tuple[bool, str]:
        with self.lock:
            if self.running:
                return True, "Captura já está ativa."
            ffmpeg = shutil.which(self.args.ffmpeg)
            if not ffmpeg:
                return False, f"Não encontrei FFmpeg ('{self.args.ffmpeg}'). Instale-o e confirme se está no PATH."
            STREAM_DIR.mkdir(parents=True, exist_ok=True)
            for old in STREAM_DIR.glob("*.*"):
                try:
                    old.unlink()
                except OSError:
                    pass
            try:
                input_args = self.ffmpeg_input()
            except RuntimeError as exc:
                self.last_error = str(exc)
                return False, self.last_error
            fps = self.args.fps
            # Fixed GOP must align with the target segment duration, otherwise HLS
            # waits for the next keyframe and silently produces longer segments.
            gop = max(1, round(fps * self.args.segment_seconds))
            output = [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                "-fflags", "nobuffer", *input_args,
                "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-vf", f"scale={self.args.width}:{self.args.height}:flags=fast_bilinear",
                "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-b:v", self.args.bitrate, "-maxrate", self.args.maxrate, "-bufsize", self.args.bufsize,
                "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                "-force_key_frames", f"expr:gte(t,n_forced*{self.args.segment_seconds})",
                "-flush_packets", "1",
                "-f", "hls", "-hls_time", str(self.args.segment_seconds),
                "-hls_list_size", str(self.args.hls_list_size),
                "-hls_delete_threshold", "1",
                "-hls_flags", "delete_segments+omit_endlist+independent_segments+program_date_time+temp_file",
                "-hls_allow_cache", "0",
                "-hls_segment_filename", str(STREAM_DIR / "seg_%06d.ts"), str(STREAM_DIR / "live.m3u8")
            ]
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                log_path = ROOT / "ffmpeg.log"
                self.stderr_file = open(log_path, "wb")
                self.proc = subprocess.Popen(output, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=self.stderr_file, creationflags=creationflags)
            except OSError as exc:
                self.last_error = f"Falha ao executar FFmpeg: {exc}"
                self.proc = None
                return False, self.last_error
            self.started_at = time.time()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if not self.running:
                stderr = ""
                try:
                    if self.stderr_file:
                        self.stderr_file.flush()
                    log_path = ROOT / "ffmpeg.log"
                    if log_path.exists():
                        stderr = log_path.read_text(encoding="utf-8", errors="replace")[-1200:]
                except Exception:
                    pass
                self.last_error = "FFmpeg encerrou antes de gerar o HLS. Consulte ffmpeg.log. " + stderr[-700:]
                self.stop()
                return False, self.last_error
            playlist = STREAM_DIR / "live.m3u8"
            if playlist.exists() and any(STREAM_DIR.glob("seg_*.ts")):
                return True, "Captura iniciada."
            time.sleep(0.2)
        self.stop()
        self.last_error = "FFmpeg não gerou o primeiro segmento HLS em 12 segundos. Verifique a captura de tela e o log."
        return False, self.last_error

    def stop(self) -> None:
        with self.lock:
            proc = self.proc
            self.proc = None
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if self.stderr_file is not None:
                try:
                    self.stderr_file.close()
                except OSError:
                    pass
                self.stderr_file = None
            self.started_at = None

    def send_key(self, key: str, action: str) -> tuple[bool, str]:
        names = {
            "up": ("Up", 0x26, 103), "down": ("Down", 0x28, 108),
            "left": ("Left", 0x25, 105), "right": ("Right", 0x27, 106),
            "ok": ("Return", 0x0D, 28), "play": ("space", 0x20, 57),
            "rewind": ("Escape", 0x1B, 1), "tab": ("Tab", 0x09, 15),
            "backspace": ("BackSpace", 0x08, 14),
        }
        if key not in names or action not in ("down", "up", "tap"):
            return False, "Tecla ou ação não suportada."
        xkey, vk, evdev = names[key]
        if action == "tap":
            if os.name == "nt":
                self._windows_key(vk, True); time.sleep(0.025); self._windows_key(vk, False)
                return True, ""
            backend = self.args.input_backend
            if backend == "none": return False, "Entrada remota está desativada."
            if backend in ("auto", "xdotool") and shutil.which("xdotool"):
                result = subprocess.run(["xdotool", "key", "--clearmodifiers", xkey], capture_output=True, text=True, timeout=2)
                return result.returncode == 0, result.stderr.strip()
            if backend in ("auto", "ydotool") and shutil.which("ydotool"):
                result = subprocess.run(["ydotool", "key", f"{evdev}:1", f"{evdev}:0"], capture_output=True, text=True, timeout=2)
                return result.returncode == 0, result.stderr.strip()
            return False, "Instale xdotool (X11/XWayland) ou ydotool (Wayland), ou use --input-backend none."
        down = action == "down"
        if os.name == "nt":
            self._windows_key(vk, down)
            return True, ""
        backend = self.args.input_backend
        if backend == "none": return False, "Entrada remota está desativada."
        if backend in ("auto", "xdotool") and shutil.which("xdotool"):
            result = subprocess.run(["xdotool", "keydown" if down else "keyup", xkey], capture_output=True, text=True, timeout=2)
            return result.returncode == 0, result.stderr.strip()
        if backend in ("auto", "ydotool") and shutil.which("ydotool"):
            result = subprocess.run(["ydotool", "key", f"{evdev}:{1 if down else 0}"], capture_output=True, text=True, timeout=2)
            return result.returncode == 0, result.stderr.strip()
        return False, "Entrada remota indisponível: instale xdotool ou ydotool."

    @staticmethod
    def _windows_key(vk: int, down: bool) -> None:
        import ctypes
        flags = 0 if down else 2
        ctypes.windll.user32.keybd_event(vk, 0, flags, 0)

state: BridgeState | None = None

class Handler(BaseHTTPRequestHandler):
    server_version = "MoonlightRokuBridge/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str, no_cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if no_cache: self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        else: self.send_header("Cache-Control", "public, max-age=1")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", True)

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536: raise ValueError("corpo muito grande")
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Bridge-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, state.token)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            html = f"""<!doctype html><html lang='pt-br'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Moonlight Roku Bridge</title><style>body{{background:#0b1020;color:#eef3ff;font:18px system-ui;max-width:760px;margin:7vh auto;padding:24px}}code{{color:#8eb7ff}}.box{{background:#131d32;padding:24px;border-radius:16px}}</style><div class='box'><h1>Moonlight Roku Bridge</h1><p>PIN de pareamento deste processo:</p><h2><code>{state.pin}</code></h2><p>Endereço do PC: <code>http://{self.server.server_address[0]}:{self.server.server_address[1]}</code></p><p>Estado de captura: <code>{'ativa' if state.running else 'parada'}</code></p><p>Esta é uma ponte experimental HLS, não um cliente nativo do protocolo Moonlight/GameStream.</p></div></html>""".encode()
            self._send(200, html, "text/html; charset=utf-8", True); return
        if path == "/api/status":
            self._json(200, {"ok": True, "name": "Moonlight Roku Bridge", "capture": state.capture_name(),
                             "streaming": state.running, "platform": platform.system(),
                             "inputBackend": state.args.input_backend, "width": state.args.width,
                             "height": state.args.height, "fps": state.args.fps,
                             "segmentSeconds": state.args.segment_seconds,
                             "playlistSegments": state.args.hls_list_size,
                             "bitrate": state.args.bitrate, "maxrate": state.args.maxrate,
                             "error": state.last_error})
            return
        if path.startswith("/stream/"):
            name = path.removeprefix("/stream/")
            if name != "live.m3u8" and not (name.startswith("seg_") and name.endswith(".ts") and name[4:-3].isdigit()):
                self._json(404, {"ok": False, "error": "Arquivo não encontrado"}); return
            file = STREAM_DIR / name
            if not file.is_file():
                self._json(404, {"ok": False, "error": "O stream ainda não foi gerado"}); return
            ctype = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
            try: body = file.read_bytes()
            except OSError: self._json(404, {"ok": False, "error": "Segmento indisponível"}); return
            self._send(200, body, ctype, name.endswith(".m3u8")); return
        self._json(404, {"ok": False, "error": "Rota inexistente"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._json_body()
        if path == "/api/pair":
            pin = str(body.get("pin", ""))
            if not hmac.compare_digest(pin, state.pin):
                self._json(403, {"ok": False, "error": "PIN incorreto"}); return
            self._json(200, {"ok": True, "token": state.token}); return
        if path in ("/api/start", "/api/stop", "/api/input") and not self._authorized():
            self._json(401, {"ok": False, "error": "Não autorizado. Pareie novamente com o PIN atual."}); return
        if path == "/api/start":
            ok, message = state.start()
            self._json(200 if ok else 500, {"ok": ok, "error": message, "streamUrl": f"http://{self.server.server_address[0]}:{self.server.server_address[1]}/stream/live.m3u8"})
            return
        if path == "/api/stop":
            state.stop(); self._json(200, {"ok": True}); return
        if path == "/api/input":
            ok, message = state.send_key(str(body.get("key", "")), str(body.get("action", "tap")))
            self._json(200 if ok else 400, {"ok": ok, "error": message}); return
        self._json(404, {"ok": False, "error": "Rota inexistente"})

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            body = b""
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
        else:
            self.send_error(404)

def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge de desktop para Roku via HLS (experimental)")
    parser.add_argument("--host", default="0.0.0.0", help="Interface de rede (padrão: 0.0.0.0 para o Roku acessar)")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--capture", choices=["auto", "windows", "x11", "pipewire"], default="auto")
    parser.add_argument("--width", type=int, default=1280, help="Largura de saída do stream; padrão 720p")
    parser.add_argument("--height", type=int, default=720, help="Altura de saída do stream; padrão 720p")
    parser.add_argument("--capture-width", type=int, default=None, help="Largura de origem X11; por padrão detecta o tamanho virtual com xrandr")
    parser.add_argument("--capture-height", type=int, default=None, help="Altura de origem X11; por padrão detecta o tamanho virtual com xrandr")
    parser.add_argument("--fps", type=int, default=60, help="FPS alvo, entre 10 e 60")
    parser.add_argument("--segment-seconds", type=float, default=0.5, help="Duração experimental dos segmentos HLS; não remove o buffer interno do Roku")
    parser.add_argument("--hls-list-size", type=int, default=64, help="64 segmentos de 0,5s mantêm janela de cerca de 32s para o player Roku")
    parser.add_argument("--bitrate", default="5000k", help="Bitrate de vídeo H.264")
    parser.add_argument("--maxrate", default="6000k", help="Teto de bitrate")
    parser.add_argument("--bufsize", default="1000k", help="Buffer VBV do encoder; menor reduz latência do encoder, mas pode reduzir qualidade")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--pipewire-source", default=None, help="ID do node PipeWire; depende da compilação do FFmpeg e do desktop")
    parser.add_argument("--input-backend", choices=["auto", "xdotool", "ydotool", "none"], default="auto")
    args = parser.parse_args()
    if args.port < 1 or args.port > 65535 or args.fps < 10 or args.fps > 60:
        parser.error("porta deve estar entre 1 e 65535; FPS entre 10 e 60")
    if args.width < 320 or args.height < 240 or args.width % 2 or args.height % 2:
        parser.error("width/height precisam ser pares, no mínimo 320x240")
    if (args.capture_width is None) != (args.capture_height is None):
        parser.error("--capture-width e --capture-height devem ser usados juntos")
    if args.capture_width is not None and (args.capture_width < 320 or args.capture_height < 240):
        parser.error("resolução de captura deve ser pelo menos 320x240")
    if not 0.25 <= args.segment_seconds <= 4.0:
        parser.error("--segment-seconds deve estar entre 0.25 e 4.0")
    if not 2 <= args.hls_list_size <= 180:
        parser.error("--hls-list-size deve estar entre 2 e 180")
    global state
    state = BridgeState(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    ip_text = "IP_DO_PC"
    try:
        import socket
        ip_text = socket.gethostbyname(socket.gethostname())
    except OSError:
        pass
    print("\nMoonlight Roku Bridge — experimental")
    print("Não é um cliente nativo do protocolo Moonlight/GameStream; captura o desktop e entrega HLS.")
    print(f"Endereço: http://{ip_text}:{args.port} (se houver várias interfaces, use o IP da LAN)")
    print(f"PIN de pareamento: {state.pin}")
    print(f"Captura selecionada: {state.capture_name()} | entrada: {args.input_backend}")
    print(f"Perfil experimental: {args.width}x{args.height}@{args.fps} FPS, HLS {args.segment_seconds:g}s, janela {args.hls_list_size} segmentos, bitrate {args.bitrate} (máx. {args.maxrate})")
    print("A Roku pode manter pelo menos ~30s de distância do live edge; isto só reduz a parte de captura/encode/segmentação.")
    print("Pressione Ctrl+C para encerrar. Mantenha o PC e a Roku na mesma LAN confiável.\n")
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop(); server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
