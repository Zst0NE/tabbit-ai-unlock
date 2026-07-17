const DEFAULTS = {
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  anthropic: { base_url: "https://api.anthropic.com", model: "claude-sonnet-4-6" },
  "openai-compatible": { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
};

const el = (id) => document.getElementById(id);

async function load() {
  const cfg = await chrome.storage.sync.get({
    provider: "openai",
    base_url: DEFAULTS.openai.base_url,
    api_key: "",
    model: DEFAULTS.openai.model,
  });
  el("provider").value = cfg.provider;
  el("base_url").value = cfg.base_url;
  el("api_key").value = cfg.api_key;
  el("model").value = cfg.model;
}

el("provider").addEventListener("change", () => {
  const p = el("provider").value;
  const d = DEFAULTS[p] || DEFAULTS.openai;
  if (!el("base_url").value || Object.values(DEFAULTS).some((x) => x.base_url === el("base_url").value)) {
    el("base_url").value = d.base_url;
  }
  if (!el("model").value || Object.values(DEFAULTS).some((x) => x.model === el("model").value)) {
    el("model").value = d.model;
  }
});

el("save").addEventListener("click", async () => {
  const cfg = {
    provider: el("provider").value,
    base_url: el("base_url").value.trim().replace(/\/$/, ""),
    api_key: el("api_key").value.trim(),
    model: el("model").value.trim(),
  };
  await chrome.storage.sync.set(cfg);
  el("status").textContent = "已保存。打开侧栏即可使用。";
});

el("import").addEventListener("click", async () => {
  const text = prompt("粘贴 api_config.json 内容：");
  if (!text) return;
  try {
    const cfg = JSON.parse(text);
    el("provider").value = cfg.provider || "openai";
    el("base_url").value = (cfg.base_url || "").replace(/\/$/, "");
    el("api_key").value = cfg.api_key || "";
    el("model").value = cfg.model || "";
    await chrome.storage.sync.set({
      provider: el("provider").value,
      base_url: el("base_url").value,
      api_key: el("api_key").value,
      model: el("model").value,
    });
    el("status").textContent = "已从 JSON 导入并保存。";
  } catch (e) {
    el("status").textContent = "JSON 解析失败: " + e.message;
  }
});

load();
