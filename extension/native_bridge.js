/**
 * Tabbit Native Chat API Bridge
 * Injected into https://web.tabbit-ai.com/* (MAIN world).
 * Keeps official Chat UI; adds a model-style chip next to LongCat/etc
 * so you can SELECT your own OpenAI/Anthropic API from the Chat side panel.
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

  // ---------- find official model chip (LongCat-2.0 etc.) ----------
  function findModelSelectorEl() {
    const nodes = Array.from(document.querySelectorAll("button,div,span"));
    let best = null;
    let bestScore = -1;
    for (const el of nodes) {
      if (el.closest("#tabbit-byok-mount")) continue;
      const t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!t || t.length > 48) continue;
      if (t.includes("自有")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 12 || r.bottom < 0) continue;
      if (r.bottom < window.innerHeight * 0.5) continue;
      let score = 0;
      if (/LongCat|GPT|Claude|Qwen|DeepSeek|Gemini|豆包|通义|Moonshot|GLM|Haiku|Sonnet|Opus|Cat-/i.test(t))
        score += 10;
      if (/模型|Model/i.test(t)) score += 3;
      if (r.right > window.innerWidth * 0.4) score += 3;
      if (r.bottom > window.innerHeight * 0.7) score += 2;
      if (el.tagName === "BUTTON") score += 1;
      if (score > bestScore) {
        bestScore = score;
        best = el;
      }
    }
    return bestScore >= 5 ? best : null;
  }

  function findComposerBar() {
    const byData = document.querySelector("[data-chat-input]");
    if (byData) return byData;
    const tas = Array.from(document.querySelectorAll("textarea,[contenteditable='true']"));
    let best = null;
    let bestY = -1;
    for (const ta of tas) {
      const r = ta.getBoundingClientRect();
      if (r.width > 100 && r.bottom > bestY && r.bottom > window.innerHeight * 0.4) {
        bestY = r.bottom;
        best = ta;
      }
    }
    if (!best) return null;
    let p = best.parentElement;
    for (let i = 0; i < 8 && p; i++) {
      if (p.querySelector("button") && p.getBoundingClientRect().width > 180) return p;
      p = p.parentElement;
    }
    return best.parentElement;
  }

  function buildPanel() {
    const panel = document.createElement("div");
    panel.id = "tabbit-byok-panel";
    const field =
      "width:100%;margin:4px 0 10px;padding:9px 10px;border-radius:10px;" +
      "box-sizing:border-box;border:1px solid #98a2b3;background:#ffffff !important;" +
      "color:#1a1d24 !important;font-size:13px;font-family:inherit;opacity:1 !important;" +
      "caret-color:#1a1d24;";
    const lab =
      "display:block;margin:2px 0 0;color:#1d2939 !important;font-size:12px;font-weight:700;opacity:1 !important;";
    Object.assign(panel.style, {
      display: "none",
      position: "absolute",
      left: "0",
      bottom: "calc(100% + 8px)",
      zIndex: "2147483646",
      background: "#ffffff",
      color: "#1a1d24",
      border: "1px solid #c5cad3",
      borderRadius: "14px",
      padding: "12px",
      boxShadow: "0 12px 40px rgba(0,0,0,.22)",
      fontSize: "13px",
      fontFamily: '"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif',
      lineHeight: "1.45",
      width: "min(340px, 92vw)",
    });
    [
      ["background", "#ffffff"],
      ["color", "#1a1d24"],
      ["opacity", "1"],
      ["-webkit-text-fill-color", "#1a1d24"],
    ].forEach(([k, v]) => panel.style.setProperty(k, v, "important"));

    panel.innerHTML = `
      <div style="font-weight:800;margin-bottom:6px;color:#101828 !important;font-size:14px">Chat 侧栏 · 选择自有模型</div>
      <div style="font-size:12px;color:#475467 !important;margin-bottom:10px">像切换 LongCat 一样：选用后本侧栏消息走你的 API</div>
      <label style="display:flex;gap:8px;align-items:center;margin:0 0 10px;color:#101828 !important;font-weight:700">
        <input type="checkbox" id="tb-en" style="width:16px;height:16px;accent-color:#ffc300"/> 选用自有 API
      </label>
      <label style="${lab}">接口类型</label>
      <select id="tb-prov" style="${field}">
        <option value="openai">OpenAI 官方</option>
        <option value="anthropic">Anthropic 官方</option>
        <option value="openai-compatible">OpenAI 兼容</option>
      </select>
      <label style="${lab}">Base URL</label>
      <input id="tb-url" style="${field}" placeholder="https://api.openai.com/v1"/>
      <label style="${lab}">API Key</label>
      <input id="tb-key" type="password" style="${field}" placeholder="sk-..." autocomplete="off"/>
      <label style="${lab}">模型</label>
      <input id="tb-model" style="${field}" placeholder="gpt-4o-mini"/>
      <div style="display:flex;gap:8px">
        <button id="tb-save" type="button" style="flex:1;padding:10px;border:0;border-radius:10px;background:#ffc300 !important;color:#1a1400 !important;font-weight:800;cursor:pointer">选用此模型</button>
        <button id="tb-off" type="button" style="padding:10px 12px;border:1px solid #d0d5dd;border-radius:10px;background:#fff !important;color:#344054 !important;font-weight:700;cursor:pointer">官方模型</button>
      </div>
      <div id="tb-msg" style="margin-top:8px;color:#027a48 !important;font-size:12px;font-weight:700;min-height:1.2em"></div>
    `;
    return panel;
  }

  function paintChip(chip) {
    cfg = loadCfg();
    const on = !!cfg.enabled && !!cfg.api_key;
    chip.style.setProperty("background", on ? "#ffc300" : "#f2f4f7", "important");
    chip.style.setProperty("color", on ? "#1a1400" : "#344054", "important");
    chip.style.setProperty("border", on ? "1px solid #e6a800" : "1px solid #d0d5dd", "important");
    chip.style.setProperty("-webkit-text-fill-color", on ? "#1a1400" : "#344054", "important");
    chip.textContent = on ? `● ${cfg.model || "自有API"}` : "○ 自有API";
    chip.title = on
      ? `Chat 侧栏当前选用：${cfg.provider} / ${cfg.model}`
      : "在 Chat 侧栏选择自有 OpenAI/Anthropic 模型";
  }

  function fillPanel(panel) {
    cfg = loadCfg();
    panel.querySelector("#tb-en").checked = !!cfg.enabled;
    panel.querySelector("#tb-prov").value = cfg.provider || "openai-compatible";
    panel.querySelector("#tb-url").value = cfg.base_url || "";
    panel.querySelector("#tb-key").value = cfg.api_key || "";
    panel.querySelector("#tb-model").value = cfg.model || "";
    panel.querySelectorAll("input,select,label,div").forEach((el) => {
      el.style.setProperty("opacity", "1", "important");
      if (el.tagName === "INPUT" || el.tagName === "SELECT") {
        el.style.setProperty("color", "#1a1d24", "important");
        el.style.setProperty("background", "#ffffff", "important");
        el.style.setProperty("-webkit-text-fill-color", "#1a1d24", "important");
      } else if (el.id !== "tb-msg") {
        el.style.setProperty("color", "#1a1d24", "important");
        el.style.setProperty("-webkit-text-fill-color", "#1a1d24", "important");
      }
    });
  }

  function ensureUi() {
    if (!document.documentElement) return;

    let mount = document.getElementById("tabbit-byok-mount");
    if (!mount) {
      mount = document.createElement("div");
      mount.id = "tabbit-byok-mount";
      Object.assign(mount.style, {
        display: "inline-flex",
        alignItems: "center",
        position: "relative",
        zIndex: "2147483646",
        margin: "0 6px 0 0",
        verticalAlign: "middle",
        fontFamily: '"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif',
      });

      const chip = document.createElement("button");
      chip.id = "tabbit-byok-chip";
      chip.type = "button";
      Object.assign(chip.style, {
        display: "inline-flex",
        alignItems: "center",
        borderRadius: "999px",
        padding: "5px 11px",
        fontSize: "12px",
        fontWeight: "700",
        cursor: "pointer",
        lineHeight: "1.2",
        whiteSpace: "nowrap",
      });
      paintChip(chip);

      const panel = buildPanel();

      chip.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const hidden = getComputedStyle(panel).display === "none";
        panel.style.display = hidden ? "block" : "none";
        if (hidden) fillPanel(panel);
      };

      panel.querySelector("#tb-save").onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const enabled = true;
        cfg = {
          enabled,
          provider: panel.querySelector("#tb-prov").value,
          base_url: panel.querySelector("#tb-url").value.trim().replace(/\/$/, ""),
          api_key: panel.querySelector("#tb-key").value.trim(),
          model: panel.querySelector("#tb-model").value.trim(),
        };
        panel.querySelector("#tb-en").checked = true;
        if (!cfg.api_key) {
          panel.querySelector("#tb-msg").style.color = "#b42318";
          panel.querySelector("#tb-msg").textContent = "请先填写 API Key";
          cfg.enabled = false;
          saveCfg(cfg);
          paintChip(chip);
          return;
        }
        saveCfg(cfg);
        paintChip(chip);
        fillPanel(panel);
        panel.querySelector("#tb-msg").style.color = "#027a48";
        panel.querySelector("#tb-msg").textContent = `已在侧栏选用：${cfg.model}`;
      };

      panel.querySelector("#tb-off").onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        cfg = loadCfg();
        cfg.enabled = false;
        saveCfg(cfg);
        panel.querySelector("#tb-en").checked = false;
        paintChip(chip);
        panel.querySelector("#tb-msg").style.color = "#344054";
        panel.querySelector("#tb-msg").textContent = "已切回官方模型";
        panel.style.display = "none";
      };

      mount.appendChild(panel);
      mount.appendChild(chip);
      document.documentElement.appendChild(mount);
    }

    const chip = document.getElementById("tabbit-byok-chip");
    const panel = document.getElementById("tabbit-byok-panel");
    if (chip) paintChip(chip);

    // 1) Prefer: next to official model selector (LongCat-2.0)
    const modelEl = findModelSelectorEl();
    if (modelEl && modelEl.parentElement) {
      const parent = modelEl.parentElement;
      if (mount.parentElement !== parent || mount.nextSibling !== modelEl) {
        try {
          const cs = getComputedStyle(parent);
          if (cs.position === "static") parent.style.position = "relative";
          parent.insertBefore(mount, modelEl);
          mount.style.position = "relative";
          mount.style.right = "";
          mount.style.bottom = "";
          mount.style.left = "";
          if (panel) {
            panel.style.left = "0";
            panel.style.right = "auto";
            panel.style.bottom = "calc(100% + 8px)";
          }
        } catch (_) {}
      }
      return;
    }

    // 2) Composer toolbar
    const bar = findComposerBar();
    if (bar && mount.parentElement !== bar) {
      try {
        bar.appendChild(mount);
        mount.style.position = "relative";
      } catch (_) {}
      return;
    }

    // 3) Fallback: bottom-right of chat area (side panel region)
    Object.assign(mount.style, {
      position: "fixed",
      right: "28px",
      bottom: "92px",
      left: "auto",
      zIndex: "2147483646",
    });
    if (panel) {
      panel.style.left = "auto";
      panel.style.right = "0";
      panel.style.bottom = "calc(100% + 8px)";
    }
    if (mount.parentElement !== document.documentElement) {
      document.documentElement.appendChild(mount);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureUi);
  } else {
    ensureUi();
  }
  setInterval(ensureUi, 1000);
  try {
    new MutationObserver(() => ensureUi()).observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  } catch (_) {}

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
    try {
      console.info("[tabbit-byok] send body (for reverse):", bodyObj);
    } catch (_) {}
    return "";
  }

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

  // ---------- fetch hook: only when user SELECTED 自有 API ----------
  const rawFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = (init?.method || (typeof input !== "string" && input?.method) || "GET").toUpperCase();
    const isSend =
      method === "POST" && (url.includes("/chat/send") || /\/chat\/send(\?|$)/.test(url));

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

  console.info("[tabbit-byok] Chat-side model selector installed on", location.host);
})();
