// Open side panel when toolbar icon is clicked.
chrome.runtime.onInstalled.addListener(() => {
  if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab?.windowId) return;
  try {
    await chrome.sidePanel.open({ windowId: tab.windowId });
  } catch (e) {
    console.warn("sidePanel.open failed", e);
  }
});

// Proxy chat requests so host_permissions apply from the service worker.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "chat") return false;
  (async () => {
    try {
      const cfg = await chrome.storage.sync.get({
        provider: "openai",
        base_url: "https://api.openai.com/v1",
        api_key: "",
        model: "gpt-4o-mini",
      });
      if (!cfg.api_key) {
        sendResponse({ ok: false, error: "未配置 API Key。请右键扩展图标 → 选项。" });
        return;
      }
      const content = await callUpstream(cfg, msg.messages || []);
      sendResponse({ ok: true, content });
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
    }
  })();
  return true; // async
});

async function callUpstream(cfg, messages) {
  const provider = (cfg.provider || "openai").toLowerCase();
  if (provider === "anthropic") {
    return chatAnthropic(cfg, messages);
  }
  return chatOpenAI(cfg, messages);
}

async function chatOpenAI(cfg, messages) {
  const base = (cfg.base_url || "https://api.openai.com/v1").replace(/\/$/, "");
  const url = base + "/chat/completions";
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + cfg.api_key,
    },
    body: JSON.stringify({
      model: cfg.model,
      messages,
      stream: false,
    }),
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("HTTP " + res.status + ": " + text.slice(0, 300));
  }
  if (!res.ok) {
    throw new Error("HTTP " + res.status + ": " + JSON.stringify(data).slice(0, 400));
  }
  const content = data?.choices?.[0]?.message?.content;
  if (content == null) throw new Error("Unexpected response: " + text.slice(0, 300));
  return content;
}

async function chatAnthropic(cfg, messages) {
  const base = (cfg.base_url || "https://api.anthropic.com").replace(/\/$/, "");
  const url = base + "/v1/messages";
  let system = null;
  const converted = [];
  for (const m of messages) {
    if (m.role === "system") {
      system = system ? system + "\n" + m.content : m.content;
      continue;
    }
    converted.push({
      role: m.role === "assistant" ? "assistant" : "user",
      content: m.content,
    });
  }
  if (!converted.length) converted.push({ role: "user", content: "Hello" });
  const body = {
    model: cfg.model,
    max_tokens: 4096,
    messages: converted,
  };
  if (system) body.system = system;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": cfg.api_key,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("HTTP " + res.status + ": " + text.slice(0, 300));
  }
  if (!res.ok) {
    throw new Error("HTTP " + res.status + ": " + JSON.stringify(data).slice(0, 400));
  }
  const parts = (data.content || []).filter((p) => p.type === "text").map((p) => p.text);
  return parts.join("") || JSON.stringify(data);
}
