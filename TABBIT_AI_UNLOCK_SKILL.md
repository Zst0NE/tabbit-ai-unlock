# Tabbit Browser AI Unlock — Technical Skill Guide

> For AI agents tasked with bypassing the "must set as default browser to use AI" restriction in Tabbit Browser, and/or configuring a BYOK OpenAI/Anthropic chat panel.

## Background

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant based on Chrome's **Glic** (Gemini side panel) plus Meituan backends (`web.tabbit.ai`, `skills.tabbit.com`, …). Tabbit added a **custom native gate** that blocks AI features unless Tabbit is the Windows default browser.

- The gate is **hard-coded in `Tabbit.dll`** (~280–290 MB), not configurable via preferences, feature flags, or command-line switches.
- It reads the default browser via `AssocQueryString` (Windows API), compares the result to "Tabbit", and sets an internal `IsDefaultBrowser` boolean that controls Glic enablement.
- Windows 10/11 protects the default browser `UserChoice` registry key with a hash — you cannot spoof it from outside.
- Native Tabbit AI does **not** expose user-facing OpenAI/Anthropic base URL settings.

**Unlock path:** binary patch of `Tabbit.dll`.  
**Custom API path:** local BYOK panel (`--byok`), not retargeting built-in AI.

---

## Patch Technique

### What we patch

Inside the gate function (symbols stripped), there is:

```asm
; --- v1.1.x ---
cmp  bpl, 1            ; did the default browser name contain "Tabbit"?
jne  <skip>            ; NO → skip SetIsDefaultBrowser(true)

; --- v1.5.x (e.g. 1.5.44.0) ---
test bl, bl
je   <skip>            ; bl==0 → skip SetIsDefaultBrowser(true)

; common tail
mov  rcx, rsi          ; this
mov  dl, 1             ; true
call SetIsDefaultBrowser
```

**Patch:** Replace the 6-byte conditional jump (`0F 84/85 xx xx xx xx`) with 6 NOPs (`90 90 90 90 90 90`).  
**Effect:** Always falls through to `SetIsDefaultBrowser(true)`.

### How to locate the patch point (version-resilient)

1. **Find the anchor string** `"Checking default browser: current="` in `.rdata`. Get its VA.
2. **Find the code xref** — scan `.text` for `LEA reg, [RIP+disp32]` whose target equals the string VA. Encoding: `48/4C 8D xx` where `(xx & 0xC7) == 0x05`.
3. **Find function boundaries** via `.pdata` (`RUNTIME_FUNCTION { BeginAddress, EndAddress, UnwindInfo }`).
4. **Find the gate branch** — within the function:
   - Prefer: `40 80 FD 01` + `0F 85 xx xx xx xx` (v1.1.x)
   - Prefer: `84 DB` + `0F 84 xx xx xx xx` (v1.5.x)
   - Fallback: find `B2 01 E8` (`mov dl,1; call`) and any `je/jne rel32` that lands exactly 7 bytes after it.
5. **Apply the patch** — overwrite the 6-byte jcc with NOPs.

### Known good points

| Version | File offset | Original | Pattern |
|---------|-------------|----------|---------|
| 1.1.39.0 | `0x30BAD21` | `0F 85 …` | `cmp bpl,1; jne` |
| 1.5.44.0 | `0x31A7DC6` | `0F 84 7C 01 00 00` | `test bl,bl; je` |

### Preventing auto-update wipe

Rename `<version>/Installer/setup.exe` → `setup.exe.disabled`.

---

## Automated Tool

**`tabbit_ai_unlock.py`** (+ **`tabbit_byok.py`** for BYOK UI)

### Unlock

```bash
python tabbit_ai_unlock.py --patch --block-updates
python tabbit_ai_unlock.py --status
python tabbit_ai_unlock.py --restore --restore-updates
```

### Custom OpenAI / Anthropic API (BYOK)

```bash
python tabbit_ai_unlock.py --set-api --provider openai --api-key sk-xxx --model gpt-4o-mini
python tabbit_ai_unlock.py --set-api --provider anthropic --api-key sk-ant-xxx --model claude-sonnet-4-6
python tabbit_ai_unlock.py --set-api --provider openai-compatible \
  --base-url https://proxy.example/v1 --api-key sk-xxx --model deepseek-chat
python tabbit_ai_unlock.py --byok   # http://127.0.0.1:8765/
```

Config file: `api_config.json` next to the script (do not commit secrets).

---

## Key Strings and Landmarks

| Artifact | Purpose |
|---|---|
| `Checking default browser: current=` | Gate function anchor |
| `Glic.ProfileEnablement.DisabledReason.` | Why AI is disabled histogram |
| `Glic.ProfileEnablement.IsEnabled.Startup` | Enablement re-checked every launch |
| `AssocQueryStringW` | Windows API for default browser |
| `web.tabbit.ai` / `skills.tabbit.com` | Meituan AI backends |
| `mov dl, 1; call` (`B2 01 E8`) | `SetIsDefaultBrowser(true)` site |

## Decision Tree for AI Agents

```
User wants Tabbit AI without setting default browser
  │
  ├─ Run: python tabbit_ai_unlock.py --patch --block-updates
  │
  ├─ FAIL: anchor string not found?
  │   └─ Manual RE: strings | grep default browser → new anchor
  │
  ├─ FAIL: could not locate skip-branch?
  │   └─ Dump gate function; find B2 01 E8; find jcc that skips past it; NOP it
  │
  └─ Restart Tabbit and verify AI panel

User wants custom OpenAI/Anthropic endpoint
  │
  ├─ Explain: built-in Tabbit AI cannot be retargeted (Meituan/Google protocol)
  └─ Run --set-api + --byok for local panel with their key
```

## Risks

- Version coupling if gate is fully rewritten
- Code signature invalidated (no practical impact observed)
- Browser must be closed while patching
- Updates wipe patch — use `--block-updates`
