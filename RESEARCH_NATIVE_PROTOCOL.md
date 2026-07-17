# Tabbit 官方 Chat 协议（逆向笔记）

日期：2026-07-18  
目标：原生 UI + 自有 OpenAI/Anthropic Key  

## 架构

```
Tabbit 侧栏 WebView
  └─ https://web.tabbit-ai.com/...  (Next.js 前端)
       └─ createChatClient(baseURL)
            ├─ GET  /proxy/v1/model_config/models?a=0|1&scene=chat
            ├─ POST ${baseURL}/chat/send   ← 主对话（SSE）
            ├─ POST /proxy/v0/chat/stop/
            └─ GET  /chat/sign-key         ← HMAC 签名密钥
```

`baseURL` 来源：`NEXT_PUBLIC_DEBUG_API_URL || NEXT_API_URL || ""`  
（见 `cdn .../2245-2d6801c43d0942f3.js`）

## 请求签名（HMAC）

发送前对 body 计算：

```
x-timestamp: Date.now()
x-nonce:     random (a.l())
x-signature: HMAC-SHA256(key, `${timestamp}.${nonce}.${sha256(body)}`) 的 hex
             或 key 来自 /chat/sign-key；内置 fallback key 见 JS 常量 n
```

headers 另含 `Content-Type: application/json`，`Accept: text/event-stream`。

## POST /chat/send

- Method: POST  
- Body: JSON（具体字段由 UI 组装后 `JSON.stringify(e)`）  
- 已知相关字段（来自周边代码，非完整 schema）：
  - `chat_session_id`
  - `html_content` / 纯文本
  - `references`
  - 单模型 / 多模型：`selected_models`（multiModel 模式）
  - `message_id` / `parallel_message_id`（fork 等）

完整 body 需在登录会话下抓一次真实请求确认。

## SSE 响应（text/event-stream）

解析逻辑（同 chunk）：

| event | 含义 | data 要点 |
|-------|------|-----------|
| `ready` | 就绪 | JSON |
| `title` | 会话标题 | JSON |
| `message_start` | 消息开始 | JSON |
| `message_chunk` | 增量文本 | `{ content: string }`（默认 event 名） |
| `message_finish` | 单条结束 | JSON |
| `finish` | 流结束；若含 `model_name` 则多模型分支 | JSON |
| `thinking` | 思考过程 | JSON |
| `error` | 错误 | JSON + traceId |
| `close` | 关闭 | |
| `switch_model` / `tool_*` / `rag_*` / `browser_use_start` | 工具/多模态 | JSON |

空行分隔事件；`data:` 行 JSON 解析失败时当作 `{ content: raw }`。

## 模型列表

`GET /proxy/v1/model_config/models?a={0|1}&scene=chat`  
`a=1` 表示 Moa 证书。  
**均为美团侧模型**，非用户 OpenAI 列表。

## multiModel / directApiMode

- `multiModel*`：Pro 多模型对比文案，不是自定义 API  
- `directApiMode`：「ask/script 的 Direct API」产品文案，不是用户 Base URL  

## 拦截策略（原生 UI 保留）

1. **不**替换侧栏页面（不用 glic-guest-url 换壳）  
2. **不**用第三方侧栏 UI  
3. 在 `web.tabbit-ai.com` 页面上下文 **hook `window.fetch`**：  
   - 匹配 `**/chat/send`  
   - 若用户开启「自有接口」：读 body 中的用户文本 → 调 OpenAI/Anthropic → 按上表 SSE 回灌  
   - 否则原样转发美团  

配置可存在 `localStorage`（同源 `web.tabbit-ai.com`），在原生界面注入极简设置入口（不改变聊天交互主路径）。

## 风险

- body schema / 鉴权 / SSE 字段随版本变化  
- 工具调用、browser_use、多模型并行需后续补全  
- 登录态与签名在 BYOK 模式下可旁路（不再打美团 send）  

## 关键 chunk

- `2245-2d6801c43d0942f3.js` — ChatClient、SSE、签名  
- `9752-52fe271bab775591.js` — LightChatInput、onSend 参数  
- webpack `i.u` 映射 — 动态 chunk 列表  
