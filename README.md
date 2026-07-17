# Tabbit Browser AI Unlock

Bypass the "must set as default browser" restriction for AI features in Tabbit Browser, and optionally run a **Bring-Your-Own-Key (BYOK)** chat panel with your own OpenAI / Anthropic API.

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant (Chrome Glic / Gemini side panel + Meituan backends). Tabbit hard-codes a native gate that **blocks AI unless Tabbit is the Windows default browser**. This tool removes that restriction via a binary patch.

> **Tested on:** Tabbit `1.1.39.0` (legacy pattern) and `1.5.44.0` (new pattern).

## Quick Start

```bash
# Close Tabbit Browser first!

# Apply patch + block auto-updates
python tabbit_ai_unlock.py --patch --block-updates

# Check current state
python tabbit_ai_unlock.py --status

# Undo everything
python tabbit_ai_unlock.py --restore --restore-updates
```

## Can native Tabbit AI use my OpenAI key?

**Short answer: no — not as a drop-in.** See [RESEARCH_NATIVE_AI.md](RESEARCH_NATIVE_AI.md).

- Built-in AI backends are Meituan (`web.tabbit.ai`, `skills.tabbit.*`) + Google Glic protocol.
- There is a test switch `--glic-guest-url=` that can point the **native Glic WebView** at localhost (`http://localhost` is allow-listed), but the host still expects the Glic guest protocol, so a plain OpenAI page is only an experiment.
- **Reliable embedded UI:** Chromium Side Panel extension (`--install-extension`).

```bash
# Experimental: native Glic WebView -> local BYOK page
python tabbit_ai_unlock.py --set-api --provider openai --api-key sk-xxx --model gpt-4o-mini
python tabbit_ai_unlock.py --embed-glic
```

## Custom OpenAI / Anthropic API (embedded side panel)

Tabbit's **built-in** AI panel talks to Meituan (`web.tabbit.ai`, `skills.tabbit.com`, …) and Google backends. There is **no** official preference for plugging in your own OpenAI/Anthropic base URL, so this repo ships an **embedded Chromium Side Panel extension** that lives inside Tabbit's UI.

```bash
# 1) Save your API config (optional but recommended)
python tabbit_ai_unlock.py --set-api --provider openai \
  --api-key sk-xxx --model gpt-4o-mini

# Anthropic
python tabbit_ai_unlock.py --set-api --provider anthropic \
  --api-key sk-ant-xxx --model claude-sonnet-4-6

# Any OpenAI-compatible proxy (DeepSeek, OneAPI, NewAPI, …)
python tabbit_ai_unlock.py --set-api --provider openai-compatible \
  --base-url https://your-proxy.example/v1 \
  --api-key sk-xxx --model deepseek-chat

# 2) Install the embedded side-panel extension + launcher
python tabbit_ai_unlock.py --install-extension

# 3) Fully quit Tabbit, then double-click launch_tabbit_byok.bat
# 4) Click the extension toolbar icon → side panel opens inside Tabbit
# 5) Right-click extension → Options to set/import API key
```

Fallback (standalone page, not embedded):

```bash
python tabbit_ai_unlock.py --byok   # http://127.0.0.1:8765/
```

CLI config is stored in `api_config.json` (gitignored). Extension config is in Chrome storage (Options page). See `api_config.example.json` and `extension/`.

## Requirements

- Python 3.6+ (stdlib only — no pip packages)
- Windows (Tabbit is Windows-only)
- Tabbit Browser must be **closed** when patching

## How the Unlock Works

Inside `Tabbit.dll`, a function:

1. Reads the current Windows default browser via `AssocQueryString`
2. Checks if the name contains "Tabbit"
3. Calls `SetIsDefaultBrowser(true)` only if it matches

Gate variants:

```asm
; v1.1.x
cmp  bpl, 1
jne  <skip SetIsDefault>

; v1.5.x
test bl, bl
je   <skip SetIsDefault>
```

The tool NOPs the 6-byte skip branch so execution always falls through to `SetIsDefaultBrowser(true)`.

### Version-resilient locating

1. Find anchor string `"Checking default browser: current="` in `.rdata`
2. Find `LEA RIP-relative` xref in `.text`
3. Resolve function bounds via `.pdata`
4. Locate `SetIsDefault(true)` (`mov dl,1; call`) and the jcc that skips it
5. Prefer known prefixes (`cmp bpl,1` / `test bl,bl`); NOP the jcc

## Options

| Flag | Description |
|------|-------------|
| `--patch` | Apply the AI unlock patch (auto-creates `.bak`) |
| `--restore` | Restore original DLL from backup |
| `--status` | Check current patch state |
| `--block-updates` | Rename `Installer/setup.exe` to freeze version |
| `--restore-updates` | Restore `setup.exe` |
| `--dll PATH` | Explicit path to `Tabbit.dll` |
| `--set-api` | Save OpenAI/Anthropic/compatible API config |
| `--show-api` | Show saved API config (key redacted) |
| `--clear-api` | Delete saved API config |
| `--install-extension` | Install **embedded** BYOK side-panel extension + launcher |
| `--byok` | Launch local BYOK chat panel (localhost fallback) |
| `--provider` | `openai` / `anthropic` / `openai-compatible` |
| `--base-url` | API base URL |
| `--api-key` | API key |
| `--model` | Model id |
| `--port` / `--bind` | BYOK listen address (default `127.0.0.1:8765`) |

## Why Block Updates?

Tabbit auto-updates frequently. Each update drops a fresh `Tabbit.dll` and wipes the patch. Use `--block-updates`.

## Limitations

- Built-in Tabbit AI UI **cannot** be retargeted to OpenAI/Anthropic — protocol and auth are proprietary Meituan/Google. BYOK is a separate local panel.
- If Tabbit rewrites the gate logic entirely, structural matching fails gracefully; re-analysis is needed.
- Patching invalidates the Authenticode signature of `Tabbit.dll` (no functional impact observed for user-installed apps).

## License

MIT
