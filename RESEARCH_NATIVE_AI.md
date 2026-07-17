# Tabbit 原生 AI 面板接入自定义 OpenAI/Anthropic — 研究报告

日期：2026-07-17  
目标版本：Tabbit Browser **1.5.44.0**（`Tabbit.dll`）

## 问题

能否让 **Tabbit 自带的 AI 入口**（工具栏/侧栏会员 AI，而非额外扩展）直接使用用户自己的 OpenAI / Anthropic 接口？

## 结论（简版）

| 路径 | 是否可行 | 说明 |
|------|----------|------|
| 配置项/Preferences 改 base_url | **否** | 无用户级 OpenAI/Anthropic 配置 |
| 二进制改字符串指向自定义 API | **基本否** | 内置 AI 走美团/Google 专有协议与鉴权，不是 Chat Completions |
| 覆盖 Glic guest URL 加载本地页 | **半可行（实验）** | 有官方测试开关，能把原生 Glic WebView 指到 localhost；但宿主仍期望 Glic guest 协议 |
| 改写 Ai Overlay WebUI | **极难** | `chrome-untrusted://ai-overlay-dialog/` 本地 WebUI + mojom，资源未以明文落在 `resources.pak` |
| Chromium Side Panel 扩展 | **可行（已实现）** | 真正嵌在 Tabbit UI 内，走你自己的 API |

**一句话：**  
不能把美团原生会员 AI「改线」成标准 OpenAI/Anthropic；  
能做的是：① 侧栏扩展内嵌（稳妥）；② 用 `--glic-guest-url` 把原生 Glic 面板 WebView 指到本地页（实验，协议不完整）。

---

## 证据

### 1. 后端与白名单

DLL 内 Glic 配置字段：

- `glicGuestURL`
- `glicGuestAPISource`
- `glicAllowedOrigins` =
  - `https://web.tab-browser.com`
  - `https://web.tabbit.com`
  - `https://web.tabbit.ai`
  - `https://tabai-test.meituan.com`
  - `https://tab-browser-test-sg.meituan.com`
  - **`http://localhost`** ← 允许本地

Skills 域名簇：`skills.tabbit.ai` / `skills.tabbit.com` / `skills.tabbit-ai.com` / `tabai.meituan.com` 等。

未发现可用的 `openai` / `anthropic` / `chat/completions` 业务端点（仅有无关或第三方站点痕迹）。

### 2. 官方可覆盖 Guest URL（实验切入点）

Chromium / Tabbit 同源逻辑（`guest_util.cc`）：

```text
--glic-guest-url=<URL>          // chrome_switches: kGlicGuestURL
Feature GlicURLConfig 参数 glic-guest-url
  默认: https://gemini.google.com/glic

Feature GlicGuestUrlPresets（默认关）
  + Local State:
    glic.guest_url_preset_autopush / staging / preprod / prod
```

代码路径：若 switch 存在则用 switch；否则 feature 默认；若启用 presets 则用 pref 覆盖。

→ **原生 Glic 面板 WebView 可以被指到 `http://127.0.0.1:端口/`。**

限制：Guest 页需要实现 Glic Web Client 握手（`glicGuestAPISource`、host 消息通道等）。  
只放一个 OpenAI 聊天 HTML **可能能显示**，但不会获得完整标签上下文 / 工具调用 / 官方 UI 行为，也可能被 host 判定 unresponsive。

### 3. Ai Overlay（Tabbit 自研覆盖层）

- URL：`chrome-untrusted://ai-overlay-dialog/`
- 控制器：`ai_overlay_dialog_controller.cc`
- 资源名：`ai_overlay_dialog.html`, `api_session.js`, `conversation.js`, `persona.js`, `tools/tool_executor.js`, `*.mojom-webui.js`
- 工具桥：`AiOverlayTools_*`（OpenUrl / PerformSearch / InvokeGlic / …）→ **mojom 进原生**，不是浏览器直连 OpenAI

在 `resources.pak` 中按内容扫描 **0 hits**（资源可能以 grit/压缩形式链入，或运行时从其他 blob 映射），短期无法像改前端静态站那样换 base_url。

### 4. multiModel 偏好

`Preferences` 中有：

```json
"tab_user_prefs.pref_values.multiModel.selected": "1"
```

DLL 中无 `MultiModel` 符号；这是 **美团多模型 UI 状态**，不是用户 BYOK。

### 5. 默认浏览器门控（已解决）

与「自定义 API」正交。1.5.44.0 门控为：

```asm
test bl, bl
je   <skip SetIsDefault(true)>   ; file off 0x31A7DC6
```

NOP 后即可在不设默认浏览器时打开内置 AI（仍走美团后端）。

---

## 工程选型

1. **默认推荐：Side Panel 扩展**（`--install-extension`）  
   - 嵌在浏览器侧栏，标准 OpenAI / Anthropic / 兼容代理  
   - 不依赖 Glic 协议  

2. **实验：原生 Glic WebView 指到本地 BYOK**（`--embed-glic`）  
   - 启动本地服务 + `Tabbit Browser.exe --glic-guest-url=http://127.0.0.1:PORT/`  
   - 用于验证面板能否被替换；**不承诺**完整原生能力  

3. **不做：伪造 UserChoice / 完整逆向 Meituan 协议重放**  
   - 成本高、易失效、合规风险  

---

## 复现实验

```bash
# A. 稳妥内嵌
python tabbit_ai_unlock.py --set-api --provider openai-compatible \
  --base-url https://YOUR/v1 --api-key sk-xxx --model xxx
python tabbit_ai_unlock.py --install-extension
# 退出 Tabbit 后运行 launch_tabbit_byok.bat

# B. 实验：原生 Glic 加载本地页
python tabbit_ai_unlock.py --set-api ... 
python tabbit_ai_unlock.py --embed-glic
# 观察 Glic/AI 面板是否打开本地页；DevTools 看是否有 host 报错
```

---

## 总判

**「把官方 AI 面板直接变成 OpenAI/Anthropic 客户端」——当前版本不行（协议与后端绑定）。**  
**「在 Tabbit 里内嵌一个用自己 Key 的 AI 面板」——可以，且已实现（扩展侧栏）；原生 Glic URL 覆盖仅作实验增强。**
