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

async function refreshMeta() {
  const cfg = await chrome.storage.sync.get({
    provider: "openai",
    base_url: "https://api.openai.com/v1",
    api_key: "",
    model: "gpt-4o-mini",
  });
  const keyOk = cfg.api_key ? "已配置 Key" : "未配置 Key";
  meta.textContent = `${cfg.provider} · ${cfg.model} · ${keyOk}`;
  meta.title = cfg.base_url || "";
  return cfg;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  messages.push({ role: "user", content: text });
  add("user", text);
  sendBtn.disabled = true;
  try {
    const res = await chrome.runtime.sendMessage({ type: "chat", messages });
    if (!res?.ok) throw new Error(res?.error || "unknown error");
    messages.push({ role: "assistant", content: res.content });
    add("assistant", res.content);
  } catch (e) {
    add("error", "Error: " + e.message, "error");
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

sendBtn.addEventListener("click", send);
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
  add("system", "对话已清空。点击工具栏扩展图标可随时打开此侧栏。");
});

(async () => {
  const cfg = await refreshMeta();
  add(
    "system",
    "已内嵌到 Tabbit 侧栏。内置会员 AI 仍走美团/Google；此面板使用你自己的 OpenAI / Anthropic 接口。"
  );
  if (!cfg.api_key) {
    add("error", "尚未配置 API Key。点击右上角 ⚙ 打开设置页。", "error");
  }
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "sync") refreshMeta();
  });
})();
