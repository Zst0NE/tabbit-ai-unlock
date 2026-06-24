# Tabbit Browser AI Unlock

Bypass the "must set as default browser" restriction for AI features in Tabbit Browser.

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant (based on Chrome's Glic/Gemini side panel). Tabbit added a hard-coded gate that **blocks AI features unless Tabbit is the Windows default browser**. This tool removes that restriction via a binary patch.

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

## Requirements

- Python 3.6+ (no external dependencies)
- Windows (Tabbit is Windows-only)
- Tabbit Browser must be **closed** when patching

## How It Works

Inside `Tabbit.dll`, there is a function that:

1. Reads the current Windows default browser via `AssocQueryString`
2. Checks if the name contains "Tabbit"
3. Calls `SetIsDefaultBrowser(true)` only if it matches

The gate is a conditional branch:

```asm
cmp  bpl, 1          ; did the name contain "Tabbit"?
jne  <epilogue>      ; no -> skip, AI stays locked
```

This tool NOPs the `jne` (6 bytes → `90 90 90 90 90 90`), so it always falls through to `SetIsDefaultBrowser(true)`, unlocking AI regardless of which browser is set as default.

### Version-Resilient Locating

The patch offset changes between Tabbit versions. Instead of hardcoding it, the tool locates the patch point structurally:

1. Find the anchor string `"Checking default browser: current="` in `.rdata`
2. Find the `LEA RIP-relative` code reference in `.text`
3. Use `.pdata` to resolve function boundaries
4. Within the function, match the `cmp bpl, 1; jne rel32` pattern
5. Verify the `jne` skips over `SetIsDefaultBrowser(true)`

This approach works across Tabbit versions as long as the gate logic hasn't been fundamentally rewritten.

## Options

| Flag | Description |
|------|-------------|
| `--patch` | Apply the AI unlock patch (auto-creates `.bak` backup) |
| `--restore` | Restore original DLL from backup |
| `--status` | Check current patch state |
| `--block-updates` | Rename `Installer/setup.exe` to prevent auto-updates |
| `--restore-updates` | Restore `setup.exe` to re-enable auto-updates |
| `--dll PATH` | Explicit path to `Tabbit.dll` (auto-detected if omitted) |

## Why Block Updates?

Tabbit auto-updates frequently. Each update creates a new version folder with a fresh `Tabbit.dll`, wiping the patch. Use `--block-updates` to prevent this.

## License

MIT
