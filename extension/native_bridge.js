/**
 * Tabbit Native Chat API Bridge
 * Injected into https://web.tabbit-ai.com/* only.
 * Keeps official Chat UI; optionally redirects /chat/send to user OpenAI/Anthropic.
 */
(function () {
  "use strict";
  if (window.__TABBIT_BYOK_BRIDGE__) return;
  window.__TABBIT_BYOK_BRIDGE__ = true;

  const STORAGE_KEY = "tabbit_byok_native_cfg";
  const DEFAULT_CFG = {
    enabled: false,
    provider: "openai-compatible",
    base_url: "https://api.openai.com/v1",
    api_key: "",
    model: "gpt-4o-mini",
  };

  function loadCfg() {
    try {
      return { ...DEFAULT_CFG, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
    } catch {
      return { ...DEFAULT_CFG };
    }
  }
  function saveCfg(cfg) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
  }

  let cfg = loadCfg();

  // ---------- minimal UI: gear on native chat, not a second sidebar ----------
  function ensureUi() {
    if (document.getElementById("tabbit-byok-fab")) return;
    const fab = document.createElement("button");
    fab.id = "tabbit-byok-fab";
    fab.type = "button";
    fab.title = "自有 API（原生 Chat 内）";
    fab.textContent = "API";
    Object.assign(fab.style, {
      position: "fixed",
      right: "12px",
      bottom: "88px",
      zIndex: "2147483646",
      border: "none",
      borderRadius: "999px",
      padding: "8px 12px",
      fontSize: "12px",
      fontWeight: "700",
      cursor: "pointer",
      background: cfg.enabled ? "#ffc300" : "rgba(0,0,0,.55)",
      color: cfg.enabled ? "#1a1400" : "#fff",
      boxShadow: "0 4px 16px rgba(0,0,0,.25)",
      fontFamily: "inherit",
    });

    const panel = document.createElement("div");
    panel.id = "tabbit-byok-panel";
    Object.assign(panel.style, {
      display: "none",
      position: "fixed",
      right: "12px",
      bottom: "130px",
      width: "300px",
      zIndex: "2147483646",
      background: "var(--panel-bg, #16191f)",
      color: "var(--foreground, #f3f4f6)",
      border: "1px solid rgba(255,255,255,.12)",
      borderRadius: "14px",
      padding: "12px",
      boxShadow: "0 12px 40px rgba(0,0,0,.35)",
      fontSize: "12px",
      fontFamily: "inherit",
    });
    panel.innerHTML = `
      <div style="font-weight:700;margin-bottom:8px">自有接口（原生 Chat）</div>
      <label style="display:flex;gap:6px;align-items:center;margin:6px 0">
        <input type="checkbox" id="tb-en"/> 启用：/chat/send 走自有 API
      </label>
      <label>类型</label>
      <select id="tb-prov" style="width:100%;margin:4px 0 8px;padding:6px;border-radius:8px">
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
        <option value="openai-compatible">OpenAI 兼容</option>
      </select>
      <label>Base URL</label>
      <input id="tb-url" style="width:100%;margin:4px 0 8px;padding:6px;border-radius:8px;box-sizing:border-box"/>
      <label>API Key</label>
      <input id="tb-key" type="password" style="width:100%;margin:4px 0 8px;padding:6px;border-radius:8px;box-sizing:border-box"/>
      <label>Model</label>
      <input id="tb-model" style="width:100%;margin:4px 0 8px;padding:6px;border-radius:8px;box-sizing:border-box"/>
      <button id="tb-save" type="button" style="width:100%;padding:8px;border:0;border-radius:10px;background:#ffc300;color:#1a1400;font-weight:700;cursor:pointer">保存</button>
      <div id="tb-msg" style="margin-top:6px;opacity:.8"></div>
    `;

    function fill() {
      cfg = loadCfg();
      panel.querySelector("#tb-en").checked = !!cfg.enabled;
      panel.querySelector("#tb-prov").value = cfg.provider || "openai-compatible";
      panel.querySelector("#tb-url").value = cfg.base_url || "";
      panel.querySelector("#tb-key").value = cfg.api_key || "";
      panel.querySelector("#tb-model").value = cfg.model || "";
      fab.style.background = cfg.enabled ? "#ffc300" : "rgba(0,0,0,.55)";
      fab.style.color = cfg.enabled ? "#1a1400" : "#fff";
    }

    fab.onclick = () => {
      const open = panel.style.display === "none";
      panel.style.display = open ? "block" : "none";
      if (open) fill();
    };
    panel.querySelector("#tb-save").onclick = () => {
      cfg = {
        enabled: panel.querySelector("#tb-en").checked,
        provider: panel.querySelector("#tb-prov").value,
        base_url: panel.querySelector("#tb-url").value.trim().replace(/\/$/, ""),
        api_key: panel.querySelector("#tb-key").value.trim(),
        model: panel.querySelector("#tb-model").value.trim(),
      };
      saveCfg(cfg);
      fill();
      panel.querySelector("#tb-msg").textContent = cfg.enabled
        ? "已启用：下一条消息走自有 API"
        : "已关闭：恢复官方后端";
    };

    document.documentElement.appendChild(fab);
    document.documentElement.appendChild(panel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureUi);
  } else {
    ensureUi();
  }
  // SPA route changes
  setInterval(ensureUi, 2000);

  // ---------- extract user text from Tabbit send body ----------
  function extractUserText(bodyObj) {
    if (!bodyObj || typeof bodyObj !== "object") return "";
    const keys = [
      "content",
      "plain_text",
      "plainText",
      "text",
      "query",
      "message",
      "user_message",
      "prompt",
      "input",
    ];
    for (const k of keys) {
      if (typeof bodyObj[k] === "string" && bodyObj[k].trim()) return bodyObj[k].trim();
    }
    if (typeof bodyObj.html_content === "string" && bodyObj.html_content.trim()) {
      const tmp = document.createElement("div");
      tmp.innerHTML = bodyObj.html_content;
      const t = (tmp.textContent || "").trim();
      if (t) return t;
    }
    if (Array.isArray(bodyObj.messages)) {
      for (let i = bodyObj.messages.length - 1; i >= 0; i--) {
        const m = bodyObj.messages[i];
        if (m && (m.role === "user" || !m.role) && m.content) {
          return typeof m.content === "string" ? m.content : JSON.stringify(m.content);
        }
      }
    }
    // last resort: stringify short fields
    try {
      const s = JSON.stringify(bodyObj);
      console.info("[tabbit-byok] send body (for reverse):", bodyObj);
      return "";
    } catch {
      return "";
    }
  }

  // ---------- SSE encoder matching Tabbit client ----------
  function sseEncode(event, dataObj) {
    return `event: ${event}\ndata: ${JSON.stringify(dataObj)}\n\n`;
  }

  async function openAIStream(cfg, userText, onChunk) {
    const base = (cfg.base_url || "").replace(/\/$/, "");
    const url = base + "/chat/completions";
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + cfg.api_key,
      },
      body: JSON.stringify({
        model: cfg.model,
        stream: true,
        messages: [{ role: "user", content: userText }],
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`OpenAI HTTP ${res.status}: ${t.slice(0, 300)}`);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        const s = line.trim();
        if (!s.startsWith("data:")) continue;
        const payload = s.slice(5).trim();
        if (payload === "[DONE]") return;
        try {
          const j = JSON.parse(payload);
          const delta = j.choices?.[0]?.delta?.content;
          if (delta) onChunk(delta);
        } catch {}
      }
    }
  }

  async function anthropicStream(cfg, userText, onChunk) {
    const base = (cfg.base_url || "https://api.anthropic.com").replace(/\/$/, "");
    const url = base + "/v1/messages";
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: cfg.model,
        max_tokens: 4096,
        stream: true,
        messages: [{ role: "user", content: userText }],
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`Anthropic HTTP ${res.status}: ${t.slice(0, 300)}`);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        const s = line.trim();
        if (!s.startsWith("data:")) continue;
        try {
          const j = JSON.parse(s.slice(5).trim());
          if (j.type === "content_block_delta" && j.delta?.text) onChunk(j.delta.text);
        } catch {}
      }
    }
  }

  function buildTabbitSseResponse(genPromise) {
    const stream = new ReadableStream({
      async start(controller) {
        const enc = new TextEncoder();
        const push = (ev, obj) => controller.enqueue(enc.encode(sseEncode(ev, obj)));
        try {
          push("ready", {});
          push("message_start", {});
          await genPromise((chunk) => {
            push("message_chunk", { content: chunk });
          });
          push("message_finish", {});
          push("finish", { model_name: loadCfg().model || "byok" });
          push("close", {});
          controller.close();
        } catch (e) {
          push("error", {
            error: String(e.message || e),
            details: String(e.message || e),
            isOffline: false,
            isHttpError: true,
          });
          controller.close();
        }
      },
    });
    return new Response(stream, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  }

  // ---------- fetch hook ----------
  const rawFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = (init?.method || (typeof input !== "string" && input?.method) || "GET").toUpperCase();
    const isSend =
      method === "POST" &&
      (url.includes("/chat/send") || /\/chat\/send(\?|$)/.test(url));

    cfg = loadCfg();
    if (!isSend || !cfg.enabled || !cfg.api_key) {
      return rawFetch(input, init);
    }

    let bodyText = init?.body || "";
    if (typeof bodyText !== "string") {
      try {
        bodyText = await new Response(bodyText).text();
      } catch {
        bodyText = "";
      }
    }
    let bodyObj = {};
    try {
      bodyObj = JSON.parse(bodyText || "{}");
    } catch {
      bodyObj = {};
    }
    console.info("[tabbit-byok] intercept /chat/send body keys:", Object.keys(bodyObj), bodyObj);

    const userText = extractUserText(bodyObj);
    if (!userText) {
      console.warn("[tabbit-byok] cannot extract user text; falling back to official API");
      return rawFetch(input, init);
    }

    const provider = (cfg.provider || "").toLowerCase();
    const gen = async (onChunk) => {
      if (provider === "anthropic") await anthropicStream(cfg, userText, onChunk);
      else await openAIStream(cfg, userText, onChunk);
    };
    return buildTabbitSseResponse(gen);
  };

  console.info("[tabbit-byok] native Chat bridge installed on", location.host);
})();
