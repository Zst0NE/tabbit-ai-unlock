const log = document.getElementById("log");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const meta = document.getElementById("meta");
const messages = [];

function add(role, text, cls) {
  const el = document.createElement("div");
  el.className = "msg " + (cls || role);
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

async function refreshMeta() {
  const cfg = await chrome.storage.sync.get({
    provider: "openai",
    base_url: "https://api.openai.com/v1",
    api_key: "",
    model: "gpt-4o-mini",
  });
  const keyOk = cfg.api_key ? "已配置" : "未配置密钥";
  const providerLabel = {
    openai: "OpenAI",
    anthropic: "Anthropic",
    "openai-compatible": "兼容接口",
  }[cfg.provider] || cfg.provider;
  meta.textContent = `${providerLabel} · ${cfg.model} · ${keyOk}`;
  meta.title = cfg.base_url || "";
  return cfg;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autosize();
  messages.push({ role: "user", content: text });
  add("user", text);
  sendBtn.disabled = true;
  try {
    const res = await chrome.runtime.sendMessage({ type: "chat", messages });
    if (!res?.ok) throw new Error(res?.error || "unknown error");
    messages.push({ role: "assistant", content: res.content });
    add("assistant", res.content);
  } catch (e) {
    add("error", "出错了：" + e.message, "error");
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

sendBtn.addEventListener("click", send);
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.getElementById("btnSettings").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById("btnClear").addEventListener("click", () => {
  messages.length = 0;
  log.innerHTML = "";
  add("system", "已开始新对话。点击工具栏「AI 助手」图标可随时打开本侧栏。");
});

(async () => {
  const cfg = await refreshMeta();
  add(
    "system",
    "已内嵌到 Tabbit 侧栏，视觉与交互对齐官方 AI 面板风格。\n官方会员 AI 仍走美团/Google；这里使用你自己的接口。"
  );
  if (!cfg.api_key) {
    add("error", "还没有配置 API Key。点右上角 ⚙ 打开设置，填入 OpenAI / Anthropic / 兼容代理。", "error");
  }
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "sync") refreshMeta();
  });
  input.focus();
})();
