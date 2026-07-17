# Tabbit Browser AI Unlock

一键解锁 Tabbit「必须默认浏览器才能用 AI」，并在浏览器**内嵌**与官方风格统一的 **AI 助手侧栏**（自有 OpenAI / Anthropic / 兼容接口）。

> 官方会员 AI 仍走美团/Google；侧栏使用你自己的 Key。两者并行，互不影响。

**Release：** 下载 [最新 Release](https://github.com/Zst0NE/tabbit-ai-unlock/releases/latest) → 解压 → 双击 `install.bat`

## 一键安装（推荐）

```bat
:: 1. 完全退出 Tabbit
:: 2. 双击
install.bat
```

或：

```bash
python tabbit_ai_unlock.py --one-click
```

会自动完成：

1. 解锁默认浏览器门控（结构定位补丁，兼容 1.1.x / 1.5.x）
2. 冻结 `setup.exe`，防止更新冲掉补丁
3. 安装 **Tabbit 风格** 侧栏扩展（美团金配色 + 中文交互）
4. 生成启动器 + 桌面快捷方式「Tabbit AI 助手」

### 首次使用

1. 完全退出 Tabbit（托盘也要退）
2. 双击桌面 **Tabbit AI 助手**（或 `launch_tabbit_byok.bat`）
3. 扩展图标右键 → **选项** → 填 API  
   或命令行：
   ```bash
   python tabbit_ai_unlock.py --set-api --provider openai-compatible \
     --base-url https://你的代理/v1 --api-key sk-xxx --model 模型名
   ```
4. 点工具栏金色 **AI 助手** 图标 → 侧栏打开

## 与 Tabbit 的统一性

| 维度 | 做法 |
|------|------|
| 嵌入位置 | Chromium Side Panel，在 Tabbit 窗口内 |
| 视觉 | 美团金主色、圆角侧栏、中文文案，贴近官方 AI 面板 |
| 交互 | 工具栏一键打开；Enter 发送 / Shift+Enter 换行 |
| 官方 AI | 保留，不劫持会员后端 |
| 自有接口 | OpenAI / Anthropic / 任意兼容代理 |

> 原生会员 AI 协议绑定美团/Glic，**无法**把官方入口直接改成 Chat Completions。详见 [RESEARCH_NATIVE_AI.md](RESEARCH_NATIVE_AI.md)。

## 其他命令

```bash
python tabbit_ai_unlock.py --status
python tabbit_ai_unlock.py --patch --block-updates
python tabbit_ai_unlock.py --install-extension
python tabbit_ai_unlock.py --restore --restore-updates
python tabbit_ai_unlock.py --byok          # 本地页备用
python tabbit_ai_unlock.py --embed-glic    # 实验：原生 Glic WebView 指向本地
```

## Requirements

- Windows + Python 3.6+（无第三方依赖）
- 打补丁时 **Tabbit 必须关闭**

## License

MIT
