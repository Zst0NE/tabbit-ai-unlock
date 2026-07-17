#!/usr/bin/env python3
"""
Tabbit BYOK (Bring Your Own Key) local chat panel.

Serves a minimal chat UI on localhost that calls OpenAI-compatible or Anthropic
APIs using the config saved by tabbit_ai_unlock.py --set-api.

Stdlib only — no pip dependencies.
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Upstream API clients
# ---------------------------------------------------------------------------

def _http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: dict,
    timeout: int = 120,
) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = {"error": err_body}
        raise RuntimeError(f"HTTP {e.code}: {parsed}") from e


def chat_openai_compatible(cfg: dict, messages: List[dict]) -> str:
    base = cfg["base_url"].rstrip("/")
    url = base + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    body = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
    }
    result = _http_json("POST", url, headers, body)
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected OpenAI response: {result}") from e


def chat_anthropic(cfg: dict, messages: List[dict]) -> str:
    base = cfg["base_url"].rstrip("/")
    url = base + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg["api_key"],
        "anthropic-version": "2023-06-01",
    }

    system = None
    converted = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system = content if system is None else f"{system}\n{content}"
            continue
        if role not in ("user", "assistant"):
            role = "user"
        converted.append({"role": role, "content": content})

    if not converted:
        converted = [{"role": "user", "content": "Hello"}]

    body: Dict[str, Any] = {
        "model": cfg["model"],
        "max_tokens": 4096,
        "messages": converted,
    }
    if system:
        body["system"] = system

    result = _http_json("POST", url, headers, body)
    try:
        parts = result.get("content") or []
        texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        return "".join(texts) if texts else str(result)
    except Exception as e:
        raise RuntimeError(f"Unexpected Anthropic response: {result}") from e


def chat(cfg: dict, messages: List[dict]) -> str:
    provider = (cfg.get("provider") or "openai").lower()
    if provider == "anthropic":
        return chat_anthropic(cfg, messages)
    return chat_openai_compatible(cfg, messages)


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Tabbit BYOK Chat</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --border: #2a2f3a;
    --text: #e8eaed;
    --muted: #9aa0a6;
    --accent: #6c8cff;
    --user: #1e3a5f;
    --bot: #1a1f2b;
    --danger: #ff6b6b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text); height: 100vh;
    display: flex; flex-direction: column;
  }
  header {
    padding: 12px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel); display: flex; align-items: center; gap: 12px;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .meta { color: var(--muted); font-size: 12px; }
  #log {
    flex: 1; overflow-y: auto; padding: 16px; display: flex;
    flex-direction: column; gap: 12px;
  }
  .msg {
    max-width: 820px; padding: 12px 14px; border-radius: 12px;
    line-height: 1.55; white-space: pre-wrap; word-break: break-word;
    border: 1px solid var(--border);
  }
  .msg.user { align-self: flex-end; background: var(--user); }
  .msg.assistant { align-self: flex-start; background: var(--bot); }
  .msg.system { align-self: center; color: var(--muted); font-size: 12px; border: none; }
  .msg.error { align-self: stretch; color: var(--danger); background: #2a1515; }
  footer {
    border-top: 1px solid var(--border); background: var(--panel);
    padding: 12px; display: flex; gap: 8px;
  }
  textarea {
    flex: 1; resize: none; min-height: 52px; max-height: 160px;
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 12px; font: inherit;
  }
  button {
    background: var(--accent); color: white; border: 0; border-radius: 10px;
    padding: 0 18px; font-weight: 600; cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
</head>
<body>
  <header>
    <h1>Tabbit BYOK</h1>
    <div class="meta" id="meta">loading…</div>
  </header>
  <div id="log"></div>
  <footer>
    <textarea id="input" rows="2" placeholder="输入消息，Enter 发送 / Shift+Enter 换行"></textarea>
    <button id="send">发送</button>
  </footer>
<script>
const log = document.getElementById('log');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const meta = document.getElementById('meta');
const messages = [];

function add(role, text, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + (cls || role);
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function loadInfo() {
  const r = await fetch('/api/info');
  const j = await r.json();
  meta.textContent = `${j.provider} · ${j.model} · ${j.base_url}`;
  add('system', '本地 BYOK 面板已就绪。内置 Tabbit AI 仍走美团/Google 后端；此面板使用你自己的 API。');
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  messages.push({role: 'user', content: text});
  add('user', text);
  sendBtn.disabled = true;
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({messages}),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    messages.push({role: 'assistant', content: j.content});
    add('assistant', j.content);
  } catch (e) {
    add('error', 'Error: ' + e.message, 'error');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

sendBtn.onclick = send;
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
loadInfo();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    cfg: dict = {}

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[byok] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/info":
            self._send_json(200, {
                "provider": self.cfg.get("provider"),
                "model": self.cfg.get("model"),
                "base_url": self.cfg.get("base_url"),
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            messages = payload.get("messages") or []
            if not isinstance(messages, list):
                raise ValueError("messages must be a list")
            content = chat(self.cfg, messages)
            self._send_json(200, {"content": content})
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def run_server(cfg: dict, host: str = "127.0.0.1", port: int = 8765) -> None:
    _Handler.cfg = cfg
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[byok] listening on http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[byok] stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    print("Use: python tabbit_ai_unlock.py --byok")
    sys.exit(1)
