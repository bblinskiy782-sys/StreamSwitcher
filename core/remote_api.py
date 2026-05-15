"""Remote API — embedded Flask web server for remote control.

Accessible from a smartphone or any HTTP client. Supports optional Bearer-token
authentication and an extended set of endpoints (playlist, volume, EQ,
history) on top of the original control surface.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from flask import Flask, jsonify, render_template_string, request

REMOTE_UI_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StreamSwitcher Remote</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 20px;
    min-height: 100vh;
  }
  h1 { color: #00d4ff; margin-bottom: 20px; font-size: 1.5rem; }
  .status-box {
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 12px;
    padding: 16px;
    width: 100%;
    max-width: 400px;
    margin-bottom: 20px;
  }
  .status-row { display: flex; justify-content: space-between; margin: 6px 0; }
  .label { color: #888; font-size: 0.85rem; }
  .value { color: #00d4ff; font-weight: bold; }
  .btn-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    width: 100%;
    max-width: 400px;
  }
  .btn {
    background: #0f3460;
    border: none;
    border-radius: 10px;
    color: #fff;
    font-size: 1rem;
    padding: 18px;
    cursor: pointer;
    transition: background 0.2s;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
  }
  .btn:hover { background: #1a5276; }
  .btn:active { background: #00d4ff; color: #000; }
  .btn.danger { background: #7b241c; }
  .btn.danger:hover { background: #a93226; }
  .btn.success { background: #1e8449; }
  .btn.success:hover { background: #27ae60; }
  .icon { font-size: 1.8rem; }
  .source-btns {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
    max-width: 400px;
    margin-top: 16px;
  }
  .src-btn {
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    color: #ccc;
    font-size: 0.95rem;
    padding: 14px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .src-btn:hover { border-color: #00d4ff; color: #00d4ff; }
  .src-btn.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
  #msg { margin-top: 16px; color: #27ae60; min-height: 20px; }
</style>
</head>
<body>
<h1>🎙 StreamSwitcher</h1>
<div class="status-box" id="status">
  <div class="status-row"><span class="label">Источник</span><span class="value" id="src">—</span></div>
  <div class="status-row"><span class="label">Аптайм</span><span class="value" id="uptime">—</span></div>
  <div class="status-row"><span class="label">Слушатели</span><span class="value" id="listeners">—</span></div>
  <div class="status-row"><span class="label">Трек</span><span class="value" id="track">—</span></div>
</div>

<div class="btn-grid">
  <button class="btn success" onclick="cmd('play')"><span class="icon">▶</span>Play</button>
  <button class="btn danger" onclick="cmd('stop')"><span class="icon">⏹</span>Stop</button>
  <button class="btn" onclick="cmd('next')"><span class="icon">⏭</span>Next</button>
  <button class="btn" onclick="cmd('mute')"><span class="icon">🔇</span>Mute</button>
</div>

<div class="source-btns">
  <button class="src-btn" onclick="switchSrc('live_input')">🎤 Живой вход</button>
  <button class="src-btn" onclick="switchSrc('mp3_file')">🎵 MP3 файл</button>
  <button class="src-btn" onclick="switchSrc('internet_radio')">📻 Интернет-радио</button>
</div>

<div id="msg"></div>

<script>
async function cmd(action) {
  const r = await fetch('/api/control', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action})
  });
  const d = await r.json();
  document.getElementById('msg').textContent = d.status || d.error;
  setTimeout(() => document.getElementById('msg').textContent = '', 2000);
}

async function switchSrc(source) {
  const r = await fetch('/api/source', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({source})
  });
  const d = await r.json();
  document.getElementById('msg').textContent = d.status || d.error;
  setTimeout(() => document.getElementById('msg').textContent = '', 2000);
  updateStatus();
}

async function updateStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('src').textContent = d.source || '—';
    document.getElementById('uptime').textContent = d.uptime || '—';
    document.getElementById('listeners').textContent = d.listeners ?? '—';
    document.getElementById('track').textContent = d.track || '—';
  } catch(e) {}
}

setInterval(updateStatus, 3000);
updateStatus();
</script>
</body>
</html>
"""


class RemoteAPI:
    """Embedded Flask web server for remote control.

    Authentication is **optional**: if ``api_key`` is empty, all endpoints
    are publicly accessible (preserving the pre-Auth behaviour). When set,
    every ``/api/*`` request must include the header
    ``Authorization: Bearer <api_key>``.

    Callbacks are intentionally late-bound (set on the instance after
    construction) to keep the wiring loose and testable.
    """

    def __init__(self, port: int = 8080, api_key: str = "") -> None:
        self.port = port
        self.api_key = api_key
        self._app = Flask(__name__)
        self._thread: threading.Thread | None = None
        self._running = False

        # Control callbacks set by the main app.
        self.on_play: Callable[[], None] | None = None
        self.on_stop: Callable[[], None] | None = None
        self.on_next: Callable[[], None] | None = None
        self.on_mute: Callable[[], None] | None = None
        self.on_source_switch: Callable[[str], None] | None = None
        self.get_status: Callable[[], dict[str, Any]] | None = None

        # Extended callbacks. Each is optional; if missing, the endpoint
        # returns 501 Not Implemented (rather than crashing).
        self.on_volume: Callable[[float], None] | None = None
        self.get_playlist: Callable[[], list[dict[str, Any]]] | None = None
        self.set_playlist: Callable[[list[str]], None] | None = None
        self.on_playlist_add: Callable[[str], None] | None = None
        self.on_playlist_remove: Callable[[int], None] | None = None
        self.get_eq: Callable[[], dict[str, Any]] | None = None
        self.set_eq: Callable[[dict[str, float]], None] | None = None
        self.get_history: Callable[[int], list[dict[str, Any]]] | None = None

        self._setup_routes()

    # ------------------------------------------------------------------ #
    #  Auth
    # ------------------------------------------------------------------ #

    def _check_auth(self) -> bool:
        if not self.api_key:
            return True
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        token = header[len("Bearer "):].strip()
        return token == self.api_key

    # ------------------------------------------------------------------ #
    #  Routes
    # ------------------------------------------------------------------ #

    def _setup_routes(self) -> None:
        app = self._app

        @app.before_request
        def _auth_gate():
            # The HTML root and static assets are public; only /api/* is gated.
            if not request.path.startswith("/api/"):
                return None
            if self._check_auth():
                return None
            return jsonify({"error": "unauthorized"}), 401

        @app.route("/")
        def index():
            return render_template_string(REMOTE_UI_HTML)

        @app.route("/api/status")
        def status():
            if self.get_status:
                try:
                    return jsonify(self.get_status())
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            return jsonify({"source": "unknown"})

        @app.route("/api/control", methods=["POST"])
        def control():
            data = request.get_json(silent=True) or {}
            action = data.get("action", "")
            try:
                if action == "play" and self.on_play:
                    self.on_play()
                elif action == "stop" and self.on_stop:
                    self.on_stop()
                elif action == "next" and self.on_next:
                    self.on_next()
                elif action == "mute" and self.on_mute:
                    self.on_mute()
                else:
                    return jsonify({"error": f"Unknown action: {action}"}), 400
                return jsonify({"status": f"OK: {action}"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/source", methods=["POST"])
        def source():
            data = request.get_json(silent=True) or {}
            src = data.get("source", "")
            try:
                if self.on_source_switch:
                    self.on_source_switch(src)
                return jsonify({"status": f"Switched to {src}"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/volume", methods=["POST"])
        def volume():
            data = request.get_json(silent=True) or {}
            try:
                value = float(data.get("master", data.get("value", 0.0)))
            except (TypeError, ValueError):
                return jsonify({"error": "invalid volume"}), 400
            value = max(0.0, min(1.0, value))
            if self.on_volume is None:
                return jsonify({"error": "volume not wired"}), 501
            self.on_volume(value)
            return jsonify({"status": "ok", "master": value})

        @app.route("/api/playlist", methods=["GET", "POST"])
        def playlist():
            if request.method == "GET":
                if self.get_playlist is None:
                    return jsonify({"error": "playlist not wired"}), 501
                return jsonify({"tracks": self.get_playlist()})
            data = request.get_json(silent=True) or {}
            tracks = data.get("tracks", [])
            if not isinstance(tracks, list):
                return jsonify({"error": "tracks must be list"}), 400
            if self.set_playlist is None:
                return jsonify({"error": "playlist not wired"}), 501
            self.set_playlist([str(t) for t in tracks])
            return jsonify({"status": "ok", "count": len(tracks)})

        @app.route("/api/playlist/add", methods=["POST"])
        def playlist_add():
            data = request.get_json(silent=True) or {}
            path = str(data.get("path", "")).strip()
            if not path:
                return jsonify({"error": "path required"}), 400
            if self.on_playlist_add is None:
                return jsonify({"error": "playlist not wired"}), 501
            self.on_playlist_add(path)
            return jsonify({"status": "ok"})

        @app.route("/api/playlist/remove", methods=["POST"])
        def playlist_remove():
            data = request.get_json(silent=True) or {}
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                return jsonify({"error": "invalid index"}), 400
            if index < 0:
                return jsonify({"error": "index required"}), 400
            if self.on_playlist_remove is None:
                return jsonify({"error": "playlist not wired"}), 501
            self.on_playlist_remove(index)
            return jsonify({"status": "ok"})

        @app.route("/api/eq", methods=["GET", "POST"])
        def eq():
            if request.method == "GET":
                if self.get_eq is None:
                    return jsonify({"error": "eq not wired"}), 501
                return jsonify(self.get_eq())
            data = request.get_json(silent=True) or {}
            bands = data.get("bands", {})
            if not isinstance(bands, dict):
                return jsonify({"error": "bands must be object"}), 400
            try:
                normalised = {str(int(k)): float(v) for k, v in bands.items()}
            except (TypeError, ValueError):
                return jsonify({"error": "invalid band values"}), 400
            if self.set_eq is None:
                return jsonify({"error": "eq not wired"}), 501
            self.set_eq({int(k): v for k, v in normalised.items()})
            return jsonify({"status": "ok", "bands": normalised})

        @app.route("/api/history")
        def history():
            try:
                limit = int(request.args.get("limit", "50"))
            except ValueError:
                limit = 50
            limit = max(1, min(500, limit))
            if self.get_history is None:
                return jsonify({"error": "history not wired"}), 501
            return jsonify({"entries": self.get_history(limit)})

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run_server(self) -> None:
        import logging

        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)
        try:
            self._app.run(
                host="0.0.0.0",
                port=self.port,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Testing hooks
    # ------------------------------------------------------------------ #

    def wsgi_app(self) -> Flask:
        """Return the underlying Flask app (for use with ``app.test_client()``)."""
        return self._app
