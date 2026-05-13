"""
Remote API - embedded Flask web server for remote control.
Accessible from smartphone or any HTTP client.
"""
import threading
from typing import Optional, Callable
from flask import Flask, jsonify, request, render_template_string


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
    """Embedded Flask web server for remote control."""

    def __init__(self, port: int = 8080):
        self.port = port
        self._app = Flask(__name__)
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Callbacks set by main app
        self.on_play: Optional[Callable] = None
        self.on_stop: Optional[Callable] = None
        self.on_next: Optional[Callable] = None
        self.on_mute: Optional[Callable] = None
        self.on_source_switch: Optional[Callable] = None
        self.get_status: Optional[Callable] = None

        self._setup_routes()

    def _setup_routes(self):
        app = self._app

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

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_server, daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_server(self):
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
        except Exception as e:
            pass
