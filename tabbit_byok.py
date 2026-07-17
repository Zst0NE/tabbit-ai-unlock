#!/usr/bin/env python3
"""
Tabbit native chat panel page (served for --glic-guest-url).

This page is intended to be loaded INSIDE Tabbit's official Glic / chat
side panel WebView, not as a separate extension side panel.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Upstream
# ---------------------------------------------------------------------------

def _http_json(method: str, url: str, headers: Dict[str, str], body: dict, timeout: int = 120) -> dict:
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


def chat_openai(cfg: dict, messages: List[dict]) -> str:
    base = cfg["base_url"].rstrip("/")
    url = base + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg["api_key"],
    }
    body = {"model": cfg["model"], "messages": messages, "stream": False}
    result = _http_json("POST", url, headers, body)
    try:
        return result["choices"][0]["message"]["content"]
    except Exception as e:
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
        converted.append({
            "role": "assistant" if role == "assistant" else "user",
            "content": content,
        })
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
    parts = result.get("content") or []
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "".join(texts) if texts else str(result)


def chat(cfg: dict, messages: List[dict]) -> str:
    if (cfg.get("provider") or "").lower() == "anthropic":
        return chat_anthropic(cfg, messages)
    return chat_openai(cfg, messages)


# ---------------------------------------------------------------------------
# Config on disk (shared with tabbit_ai_unlock.py)
# ---------------------------------------------------------------------------

def _default_config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "api_config.json")


def load_config(path: Optional[str] = None) -> dict:
    path = path or _default_config_path()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "provider": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
    }


def save_config(cfg: dict, path: Optional[str] = None) -> None:
    path = path or _default_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# UI — designed to fill Tabbit's official chat side panel
# ---------------------------------------------------------------------------

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AI 对话</title>
<style>
:root {
  --bg: #0f1114;
  --panel: #16191f;
  --border: rgba(255,255,255,.08);
  --text: #f3f4f6;
  --muted: #9aa0a6;
  --gold: #ffc300;
  --gold-dim: rgba(255,195,0,.14);
  --user: #2a2410;
  --bot: #1b1f27;
  --danger: #ff6b6b;
  --radius: 14px;
  font-family: "Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:#f5f6f8; --panel:#fff; --border:rgba(0,0,0,.08);
    --text:#1a1d24; --muted:#5f6368; --user:#fff7d6; --bot:#eef0f4;
  }
}
* { box-sizing: border-box; }
html, body { margin:0; height:100%; background:var(--bg); color:var(--text); }
body { display:flex; flex-direction:column; }

/* top bar like Tabbit chat */
.top {
  display:flex; align-items:center; justify-content:space-between;
  padding:10px 12px; background:var(--panel); border-bottom:1px solid var(--border);
  gap:8px;
}
.brand { display:flex; align-items:center; gap:8px; min-width:0; }
.dot {
  width:28px; height:28px; border-radius:9px;
  background:linear-gradient(145deg,#ffd84d,#ffb800);
  color:#1a1400; display:grid; place-items:center; font-weight:700; font-size:13px;
}
.titles { min-width:0; }
.titles strong { display:block; font-size:13.5px; }
.titles span { display:block; font-size:11px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px; }
.top-actions { display:flex; gap:6px; }
.top-actions button {
  border:1px solid var(--border); background:transparent; color:var(--text);
  border-radius:10px; height:30px; padding:0 10px; cursor:pointer; font-size:12px;
}
.top-actions button.primary {
  background:var(--gold); color:#1a1400; border-color:transparent; font-weight:600;
}

/* settings drawer — IN the chat panel */
#settings {
  display:none; padding:12px; border-bottom:1px solid var(--border);
  background:var(--panel);
}
#settings.open { display:block; }
#settings h3 { margin:0 0 10px; font-size:13px; }
label { display:block; font-size:11px; color:var(--muted); margin:8px 0 4px; }
input, select {
  width:100%; padding:9px 10px; border-radius:10px; border:1px solid var(--border);
  background:var(--bg); color:var(--text); font:inherit; font-size:13px;
}
.row { display:flex; gap:8px; margin-top:12px; }
.row button {
  flex:1; border:0; border-radius:10px; padding:10px; font-weight:600; cursor:pointer; font:inherit;
}
#btnSave { background:var(--gold); color:#1a1400; }
#btnCloseSet { background:transparent; color:var(--text); border:1px solid var(--border); }
#setStatus { margin-top:8px; font-size:12px; color:#3dd68c; min-height:1em; }

#log {
  flex:1; overflow-y:auto; padding:12px; display:flex; flex-direction:column; gap:10px;
}
.msg {
  max-width:92%; padding:10px 12px; border-radius:var(--radius);
  line-height:1.55; white-space:pre-wrap; word-break:break-word; font-size:13.5px;
  border:1px solid var(--border);
}
.msg.user { align-self:flex-end; background:var(--user); border-color:rgba(255,195,0,.25); }
.msg.assistant { align-self:flex-start; background:var(--bot); }
.msg.system { align-self:center; border:0; background:transparent; color:var(--muted); font-size:12px; text-align:center; max-width:100%; }
.msg.error { align-self:stretch; color:var(--danger); background:rgba(255,107,107,.08); border-color:rgba(255,107,107,.25); }

.composer-wrap { padding:10px 12px 12px; }
.composer {
  display:flex; gap:8px; align-items:flex-end; padding:8px;
  border-radius:16px; background:var(--panel); border:1px solid var(--border);
}
textarea {
  flex:1; border:0; outline:0; resize:none; min-height:40px; max-height:130px;
  background:transparent; color:var(--text); font:inherit; padding:8px 4px;
}
#send {
  width:36px; height:36px; border:0; border-radius:12px;
  background:var(--gold); color:#1a1400; font-weight:700; font-size:16px; cursor:pointer;
}
#send:disabled { opacity:.45; cursor:not-allowed; }
.hint { text-align:center; color:var(--muted); font-size:11px; margin-top:8px; }
</style>
</head>
<body>
  <div class="top">
    <div class="brand">
      <div class="dot">✦</div>
      <div class="titles">
        <strong>AI 对话</strong>
        <span id="meta">未配置接口</span>
      </div>
    </div>
    <div class="top-actions">
      <button type="button" id="btnNew">新对话</button>
      <button type="button" class="primary" id="btnCfg">接口设置</button>
    </div>
  </div>

  <div id="settings">
    <h3>自有接口（写在 Chat 侧栏内）</h3>
    <label>类型</label>
    <select id="provider">
      <option value="openai">OpenAI 官方</option>
      <option value="anthropic">Anthropic 官方</option>
      <option value="openai-compatible">OpenAI 兼容（NewAPI / 代理）</option>
    </select>
    <label>Base URL</label>
    <input id="base_url" placeholder="https://api.openai.com/v1"/>
    <label>API Key</label>
    <input id="api_key" type="password" placeholder="sk-..." autocomplete="off"/>
    <label>模型</label>
    <input id="model" placeholder="gpt-4o-mini"/>
    <div class="row">
      <button type="button" id="btnSave">保存到本机</button>
      <button type="button" id="btnCloseSet">收起</button>
    </div>
    <div id="setStatus"></div>
  </div>

  <div id="log"></div>

  <div class="composer-wrap">
    <div class="composer">
      <textarea id="input" rows="1" placeholder="输入消息，Enter 发送…"></textarea>
      <button type="button" id="send">↑</button>
    </div>
    <div class="hint">已嵌入官方 Chat 侧栏 · 使用你的自有接口</div>
  </div>

<script>
const log = document.getElementById('log');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const meta = document.getElementById('meta');
const settings = document.getElementById('settings');
const setStatus = document.getElementById('setStatus');
const messages = [];
let cfg = {};

function add(role, text, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + (cls || role);
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}
function autosize() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 130) + 'px';
}
function paintMeta() {
  const labels = {openai:'OpenAI', anthropic:'Anthropic', 'openai-compatible':'兼容接口'};
  const p = labels[cfg.provider] || cfg.provider || '-';
  const key = cfg.api_key ? '已配置 Key' : '未配置 Key';
  meta.textContent = `${p} · ${cfg.model || '-'} · ${key}`;
  meta.title = cfg.base_url || '';
}
function fillForm() {
  document.getElementById('provider').value = cfg.provider || 'openai-compatible';
  document.getElementById('base_url').value = cfg.base_url || '';
  document.getElementById('api_key').value = cfg.api_key || '';
  document.getElementById('model').value = cfg.model || '';
}
async function loadInfo() {
  const r = await fetch('/api/info');
  cfg = await r.json();
  paintMeta();
  fillForm();
  if (!cfg.api_key) {
    settings.classList.add('open');
    add('error', '请先在上方「接口设置」填写你的 OpenAI / Anthropic / 兼容代理。', 'error');
  } else {
    add('system', '已在官方 Chat 侧栏中加载自有接口。点「接口设置」可随时修改。');
  }
}
async function saveCfg() {
  const body = {
    provider: document.getElementById('provider').value,
    base_url: document.getElementById('base_url').value.trim().replace(/\/$/, ''),
    api_key: document.getElementById('api_key').value.trim(),
    model: document.getElementById('model').value.trim(),
  };
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) {
    setStatus.textContent = j.error || '保存失败';
    setStatus.style.color = '#ff6b6b';
    return;
  }
  cfg = j;
  paintMeta();
  setStatus.style.color = '#3dd68c';
  setStatus.textContent = '已保存，可直接在下方对话。';
}
async function send() {
  const text = input.value.trim();
  if (!text) return;
  if (!cfg.api_key) {
    settings.classList.add('open');
    add('error', '请先配置 API Key。', 'error');
    return;
  }
  input.value = '';
  autosize();
  messages.push({role:'user', content:text});
  add('user', text);
  sendBtn.disabled = true;
  try {
    const r = await fetch('/api/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({messages}),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    messages.push({role:'assistant', content:j.content});
    add('assistant', j.content);
  } catch (e) {
    add('error', 'Error: ' + e.message, 'error');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

document.getElementById('btnCfg').onclick = () => {
  settings.classList.toggle('open');
  fillForm();
};
document.getElementById('btnCloseSet').onclick = () => settings.classList.remove('open');
document.getElementById('btnSave').onclick = saveCfg;
document.getElementById('btnNew').onclick = () => {
  messages.length = 0;
  log.innerHTML = '';
  add('system', '已开始新对话。');
};
sendBtn.onclick = send;
input.addEventListener('input', autosize);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
loadInfo();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    cfg: dict = {}
    config_path: str = ""

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[chat-panel] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Allow embedding in Tabbit Glic webview
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/panel", "/glic"):
            self._send(200, CHAT_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/info":
            c = dict(self.cfg)
            # don't strip key - UI needs to know if set; redact in display only
            self._json(200, c)
            return
        if path == "/health":
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"error": "invalid json"})
            return

        if path == "/api/config":
            for k in ("provider", "base_url", "api_key", "model"):
                if k in payload and payload[k] is not None:
                    self.cfg[k] = str(payload[k]).strip()
            if self.cfg.get("base_url"):
                self.cfg["base_url"] = self.cfg["base_url"].rstrip("/")
            try:
                save_config(self.cfg, self.config_path)
            except Exception as e:
                self._json(500, {"error": str(e)})
                return
            self._json(200, self.cfg)
            return

        if path == "/api/chat":
            try:
                messages = payload.get("messages") or []
                if not self.cfg.get("api_key"):
                    raise RuntimeError("未配置 API Key")
                content = chat(self.cfg, messages)
                self._json(200, {"content": content})
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        self._json(404, {"error": "not found"})


def run_server(cfg: dict, host: str = "127.0.0.1", port: int = 8765, config_path: Optional[str] = None) -> None:
    _Handler.cfg = dict(cfg)
    _Handler.config_path = config_path or _default_config_path()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[chat-panel] http://{host}:{port}/  (Glic guest target)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[chat-panel] stopped.")
    finally:
        httpd.server_close()


def start_server_background(cfg: dict, host: str = "127.0.0.1", port: int = 8765, config_path: Optional[str] = None) -> ThreadingHTTPServer:
    _Handler.cfg = dict(cfg)
    _Handler.config_path = config_path or _default_config_path()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


if __name__ == "__main__":
    cfg = load_config()
    run_server(cfg)
