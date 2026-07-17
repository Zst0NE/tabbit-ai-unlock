# Tabbit Browser AI Unlock — Technical Skill Guide

> For AI agents tasked with bypassing the "must set as default browser to use AI" restriction in Tabbit Browser.

## Background

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant based on Chrome's **Glic** (Gemini side panel). Tabbit added a **custom native gate** that blocks AI features unless Tabbit is the Windows default browser.

- The gate is **hard-coded in `Tabbit.dll`** (~285 MB), not configurable via preferences, feature flags, or command-line switches.
- It reads the default browser via `AssocQueryString` (Windows API), compares the result to "Tabbit", and sets an internal `IsDefaultBrowser` boolean that controls Glic enablement.
- Windows 10/11 protects the default browser `UserChoice` registry key with a hash — you cannot spoof it from outside.

**The only viable bypass is a binary patch of Tabbit.dll.**

---

## Patch Technique

### What we patch

Inside the function `GetDefaultBrowserNameAndCheck` (not its real name — symbols are stripped), there is:

```asm
cmp  bpl, 1            ; did the fetched default browser name contain "Tabbit"?
jne  <epilogue>        ; NO → skip SetIsDefaultBrowser(true), AI stays locked
; ... (VLOG logging) ...
mov  rcx, rsi          ; this
mov  dl, 1             ; true
call SetIsDefaultBrowser
```

**Patch:** Replace the 6-byte `jne` (`0F 85 xx xx xx xx`) with 6 NOPs (`90 90 90 90 90 90`).  
**Effect:** Always falls through to `SetIsDefaultBrowser(true)`, regardless of actual default.

### How to locate the patch point (version-resilient)

The offset changes between versions. Use these structural landmarks:

1. **Find the anchor string** `"Checking default browser: current="` in `.rdata` section. This is a custom Tabbit string (not in stock Chromium). Get its VA.

2. **Find the code xref** — scan `.text` for a `LEA reg, [RIP+disp32]` instruction whose computed target equals the string's VA. Encoding: `48/4C 8D xx` where `(xx & 0xC7) == 0x05`, followed by a 4-byte signed displacement. `target = instruction_VA + 7 + disp32`.

3. **Find the function boundaries** — look up the xref's RVA in the `.pdata` section (array of `RUNTIME_FUNCTION { BeginAddress:u32, EndAddress:u32, UnwindInfo:u32 }`). Find the entry where `BeginAddress <= xref_RVA < EndAddress`.

4. **Find the gate branch** — within the function bytes, search for:
   - `40 80 FD 01` (`cmp bpl, 1`)
   - Immediately followed by `0F 85 xx xx xx xx` (`jne rel32`)
   - Verify: the jne jumps FORWARD, and between the jne and its target there exists `B2 01 E8` (`mov dl, 1; call` — the SetIsDefaultBrowser(true) call).

5. **Apply the patch** — overwrite the 6-byte `jne` with `90 90 90 90 90 90`.

### Preventing auto-update wipe

Tabbit auto-updates frequently (versions 1.1.13 → 1.1.39+ observed). Each update creates a new version folder with a fresh `Tabbit.dll`, wiping the patch.

**Block updates:** Rename `<version>/Installer/setup.exe` to `setup.exe.disabled`. The built-in Omaha client may download an update, but cannot install it without the installer binary.

---

## Automated Tool

A self-contained Python script is provided: **`tabbit_ai_unlock.py`**

### Requirements
- Python 3.6+ (no external dependencies — uses only `struct`, `os`, `shutil`, `argparse`)
- Write access to the Tabbit Browser installation directory
- Tabbit Browser must NOT be running when patching

### Usage

```bash
# Apply patch + block updates (recommended)
python tabbit_ai_unlock.py --patch --block-updates

# Check current state
python tabbit_ai_unlock.py --status

# Undo everything
python tabbit_ai_unlock.py --restore --restore-updates

# Specify DLL path explicitly (non-standard install)
python tabbit_ai_unlock.py --patch --dll "D:\Tabbit\1.2.0.0\Tabbit.dll"
```

### What the script does

1. Auto-detects the latest Tabbit version folder under `%LOCALAPPDATA%\Tabbit Browser\Application\`
2. Parses the PE headers (no `pefile` dependency — built-in parser)
3. Locates the patch point using the structural method described above
4. Creates a `.bak` backup of the original DLL (only once, never overwrites existing backup)
5. Applies the 6-byte NOP patch
6. Verifies the patch was written correctly
7. Optionally renames `Installer/setup.exe` to block auto-updates

### Rollback

```bash
python tabbit_ai_unlock.py --restore --restore-updates
```

Or manually:
- Copy `Tabbit.dll.bak` over `Tabbit.dll`
- Rename `Installer/setup.exe.disabled` back to `setup.exe`

---

## Key Strings and Landmarks (for manual analysis)

| Artifact | Purpose |
|---|---|
| `Checking default browser: current=` | Custom log in the gate function (anchor for xref) |
| `Glic.ProfileEnablement.DisabledReason.` | Histogram recording why AI is disabled |
| `Glic.ProfileEnablement.IsEnabled.Startup` | Enablement re-checked every launch |
| `SetGetDefaultBrowserNameCallback` | Callback registration for the gate function |
| `AssocQueryStringW` | Windows API used to read the actual default browser |
| `skipDefaultBrowser` / `setAsDefaultBrowser` | WebUI handlers (onboarding page, not the gate) |
| Resource ID 2361 (zh-CN) | User-facing gate message text |

## Risks and Limitations

- **Version coupling:** If Tabbit rewrites the gate logic (different asm pattern), the script's pattern matching fails gracefully (no patch applied, error reported). Manual re-analysis needed.
- **Signature:** Tabbit.dll may be code-signed. The patch invalidates the signature, but Windows does not enforce DLL signatures for user-installed apps. No functional impact observed.
- **Browser must be closed** during patching (the DLL is locked while running).
- **Updates wipe the patch** — use `--block-updates` for durability.

## Decision Tree for AI Agents

```
User wants Tabbit AI without setting default browser
  │
  ├─ Is tabbit_ai_unlock.py available?
  │   ├─ YES → Run: python tabbit_ai_unlock.py --patch --block-updates
  │   └─ NO  → Follow the "Locating the patch point" section manually
  │
  ├─ Script reports "FAIL: Gate string not found"?
  │   └─ Tabbit changed the gate mechanism. Do manual RE:
  │      1. strings Tabbit.dll | grep -i "default browser"
  │      2. Find new anchor string
  │      3. Trace xref → function → branch → patch
  │
  └─ After patching: restart Tabbit Browser and verify AI panel works
```
