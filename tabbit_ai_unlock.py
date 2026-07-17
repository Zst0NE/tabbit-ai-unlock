#!/usr/bin/env python3
"""
Tabbit Browser AI Unlock Tool
==============================
Bypass the "must set as default browser to use AI" restriction in Tabbit Browser,
and optionally configure a Bring-Your-Own-Key (BYOK) OpenAI / Anthropic chat panel.

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant based
on Chrome's Glic (Gemini side panel) plus Meituan backends (web.tabbit.ai etc.).
Tabbit added a custom native gate that blocks AI features unless Tabbit is the
Windows default browser.

This tool patches Tabbit.dll to remove that restriction. The patch point is located
structurally (not by hardcoded offset) so it works across Tabbit versions.

Additionally, because Tabbit's native AI is locked to Meituan/Google backends and
does NOT expose a user-facing OpenAI/Anthropic base URL setting, this tool can
launch a local BYOK chat panel that talks to your own OpenAI-compatible or
Anthropic API endpoint.

Usage:
    python tabbit_ai_unlock.py [options]

Options:
    --patch            Apply the bypass patch (auto-creates .bak backup)
    --restore          Restore original DLL from backup
    --status           Check current patch state without modifying
    --block-updates    Rename Installer/setup.exe to prevent auto-updates
    --restore-updates  Restore Installer/setup.exe to re-enable auto-updates
    --dll PATH         Explicit path to Tabbit.dll (auto-detected if omitted)

    --set-api          Save OpenAI/Anthropic API config (see --provider etc.)
    --show-api         Show current API config (key redacted)
    --clear-api        Remove saved API config
    --byok             Launch local BYOK chat panel (uses saved API config)
    --provider NAME    openai | anthropic | openai-compatible
    --base-url URL     API base URL (e.g. https://api.openai.com/v1)
    --api-key KEY      API key / token
    --model NAME       Model id (e.g. gpt-4o-mini, claude-sonnet-4-6)
    --port N           BYOK server port (default 8765)
    --bind ADDR        BYOK bind address (default 127.0.0.1)

Examples:
    python tabbit_ai_unlock.py --patch --block-updates
    python tabbit_ai_unlock.py --status
    python tabbit_ai_unlock.py --set-api --provider openai --api-key sk-... --model gpt-4o-mini
    python tabbit_ai_unlock.py --set-api --provider anthropic --api-key sk-ant-... --model claude-sonnet-4-6
    python tabbit_ai_unlock.py --set-api --provider openai-compatible \\
        --base-url https://your-proxy.example/v1 --api-key sk-... --model deepseek-chat
    python tabbit_ai_unlock.py --byok

Requirements:
    Python 3.6+, no external dependencies for patch/status.
    BYOK panel needs Python 3.6+ stdlib only (urllib).
    Tabbit Browser must be CLOSED when patching (DLL is locked while running).

How the unlock works:
    Inside Tabbit.dll there is a function that:
    1. Reads the current Windows default browser name via AssocQueryString
    2. Checks if the name contains "Tabbit"
    3. Calls SetIsDefaultBrowser(true) only if it matches

    Gate variants observed:
      (v1.1.x)  cmp  bpl, 1 / jne  <skip SetIsDefault>
      (v1.5.x)  test bl, bl  / je   <skip SetIsDefault>

    This tool NOPs the skip-branch (6 bytes), so it always falls through to
    SetIsDefaultBrowser(true), unlocking AI regardless of default browser.

Locating strategy (version-resilient):
    1. Find unique string "Checking default browser: current=" in .rdata
    2. Find the LEA RIP-relative xref to it in .text
    3. Use .pdata to get the containing function's boundaries
    4. Within that function, find SetIsDefault(true) = mov dl,1; call
    5. Find conditional jump that skips past that call
    6. Prefer known prefixes (cmp bpl,1 / test bl,bl); NOP the 6-byte jcc

License: MIT
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATE_STRING = b"Checking default browser: current="

CMP_BPL_1 = bytes([0x40, 0x80, 0xFD, 0x01])       # cmp bpl, 1  (v1.1.x)
TEST_BL_BL = bytes([0x84, 0xDB])                    # test bl, bl (v1.5.x)
JNE_REL32 = bytes([0x0F, 0x85])                     # jne rel32
JE_REL32 = bytes([0x0F, 0x84])                      # je  rel32
NOP_6 = bytes([0x90] * 6)                           # 6x nop
SET_DEFAULT_TRUE = bytes([0xB2, 0x01, 0xE8])        # mov dl, 1; call ...

VERSION = "1.3.0"

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openai-compatible": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "openai-compatible": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-6",
}


# ---------------------------------------------------------------------------
# Minimal PE parser (no external dependencies)
# ---------------------------------------------------------------------------

def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]

def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]

def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]

def _u64(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


class PESection:
    """Minimal PE section header."""
    __slots__ = ("name", "va", "vsize", "raw_off", "raw_size")

    def __init__(self, name: str, va: int, vsize: int, raw_off: int, raw_size: int):
        self.name = name
        self.va = va
        self.vsize = vsize
        self.raw_off = raw_off
        self.raw_size = raw_size

    def __repr__(self) -> str:
        return f"<Section {self.name} VA=0x{self.va:X} raw=0x{self.raw_off:X}>"


def parse_pe(data: bytes) -> Tuple[int, List[PESection]]:
    """Parse PE headers. Returns (image_base, [PESection, ...])."""
    if data[:2] != b"MZ":
        raise ValueError("Not a valid PE file (missing MZ header)")

    pe_off = _u32(data, 0x3C)
    if data[pe_off : pe_off + 4] != b"PE\x00\x00":
        raise ValueError("Not a valid PE file (missing PE\\0\\0 signature)")

    coff_off = pe_off + 4
    num_sections = _u16(data, coff_off + 2)
    opt_size = _u16(data, coff_off + 16)
    opt_off = coff_off + 20

    magic = _u16(data, opt_off)
    if magic == 0x20B:      # PE32+ (64-bit)
        image_base = _u64(data, opt_off + 24)
    elif magic == 0x10B:    # PE32 (32-bit)
        image_base = _u32(data, opt_off + 28)
    else:
        raise ValueError(f"Unknown optional header magic: 0x{magic:X}")

    sec_off = opt_off + opt_size
    sections = []
    for i in range(num_sections):
        s = sec_off + i * 40
        name = data[s : s + 8].rstrip(b"\x00").decode("latin-1")
        vsize = _u32(data, s + 8)
        va = _u32(data, s + 12)
        raw_size = _u32(data, s + 16)
        raw_off = _u32(data, s + 20)
        sections.append(PESection(name, va, vsize, raw_off, raw_size))

    return image_base, sections


def _get_section(sections: List[PESection], name: str) -> Optional[PESection]:
    for s in sections:
        if s.name == name:
            return s
    return None


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _find_string_va(
    data: bytes, sections: List[PESection], image_base: int
) -> Tuple[Optional[int], Optional[str]]:
    """Locate the gate anchor string and return its VA."""
    idx = data.find(GATE_STRING)
    if idx == -1:
        return None, (
            "Anchor string not found. "
            "This DLL may not be Tabbit, or the version changed the string."
        )
    for s in sections:
        if s.raw_off <= idx < s.raw_off + s.raw_size:
            rva = s.va + (idx - s.raw_off)
            return image_base + rva, None
    return None, "Anchor string found at unexpected file offset (not in any section)."


def _find_lea_xref(
    data: bytes, text: PESection, image_base: int, target_va: int
) -> Tuple[Optional[int], Optional[int]]:
    """Scan .text for a LEA reg,[RIP+disp32] referencing target_va.
    Returns (instruction_va, file_offset) or (None, None)."""
    base = text.raw_off
    end = base + text.raw_size
    i = base
    while i < end - 7:
        b0 = data[i]
        # REX.W=1 (0x48) or REX.WR (0x4C) + 0x8D + modrm with mod=00 rm=101
        if b0 in (0x48, 0x4C) and data[i + 1] == 0x8D and (data[i + 2] & 0xC7) == 0x05:
            disp = _i32(data, i + 3)
            insn_va = image_base + text.va + (i - base)
            if insn_va + 7 + disp == target_va:
                return insn_va, i
        i += 1
    return None, None


def _find_function(
    data: bytes, pdata: PESection, image_base: int, code_va: int
) -> Tuple[Optional[int], Optional[int]]:
    """Use .pdata RUNTIME_FUNCTION entries to find the function containing code_va.
    Returns (func_start_va, func_end_va) or (None, None)."""
    target_rva = code_va - image_base
    o = pdata.raw_off
    limit = o + min(pdata.vsize, pdata.raw_size)
    while o < limit - 12:
        begin = _u32(data, o)
        end = _u32(data, o + 4)
        if begin <= target_rva < end:
            return image_base + begin, image_base + end
        o += 12
    return None, None


def _find_patch_point(
    data: bytes,
    text: PESection,
    image_base: int,
    func_start: int,
    func_end: int,
) -> Tuple[Optional[int], Optional[bytes], Optional[str]]:
    """Within the gate function, find the skip-branch before SetIsDefault(true).

    Supports:
      v1.1.x: cmp bpl,1 ; jne rel32
      v1.5.x: test bl,bl ; je  rel32
      generic: any je/jne that jumps exactly past a mov dl,1; call site,
               preferring known boolean-test prefixes.

    Returns (file_offset, current_6_bytes, error_msg).
    """
    fo_start = text.raw_off + (func_start - image_base - text.va)
    fo_end = text.raw_off + (func_end - image_base - text.va)
    func = data[fo_start:fo_end]

    # --- Strategy 1: known legacy pattern (cmp bpl,1 + jne/NOP) ---
    search_from = 0
    while True:
        idx = func.find(CMP_BPL_1, search_from)
        if idx == -1:
            break
        jne_off = idx + len(CMP_BPL_1)
        if jne_off + 6 > len(func):
            search_from = idx + 1
            continue
        candidate = func[jne_off : jne_off + 6]
        if candidate == NOP_6:
            after = func[jne_off + 6 : jne_off + 512]
            if SET_DEFAULT_TRUE in after:
                return fo_start + jne_off, NOP_6, None
            search_from = idx + 1
            continue
        if candidate[:2] != JNE_REL32:
            search_from = idx + 1
            continue
        disp = _i32(data, fo_start + jne_off + 2)
        if disp <= 0:
            search_from = idx + 1
            continue
        between = func[jne_off + 6 : min(len(func), jne_off + 6 + disp)]
        if SET_DEFAULT_TRUE not in between:
            search_from = idx + 1
            continue
        return fo_start + jne_off, bytes(candidate), None

    # --- Strategy 2: known v1.5 pattern (test bl,bl + je/NOP) ---
    search_from = 0
    while True:
        idx = func.find(TEST_BL_BL, search_from)
        if idx == -1:
            break
        je_off = idx + len(TEST_BL_BL)
        if je_off + 6 > len(func):
            search_from = idx + 1
            continue
        candidate = func[je_off : je_off + 6]
        if candidate == NOP_6:
            after = func[je_off + 6 : je_off + 512]
            if SET_DEFAULT_TRUE in after:
                return fo_start + je_off, NOP_6, None
            search_from = idx + 1
            continue
        if candidate[:2] != JE_REL32:
            search_from = idx + 1
            continue
        disp = _i32(data, fo_start + je_off + 2)
        if disp <= 0:
            search_from = idx + 1
            continue
        between = func[je_off + 6 : min(len(func), je_off + 6 + disp)]
        if SET_DEFAULT_TRUE not in between:
            search_from = idx + 1
            continue
        return fo_start + je_off, bytes(candidate), None

    # --- Strategy 3: generic — jcc that lands exactly after SetIsDefault(true) ---
    set_sites = []
    st = 0
    while True:
        j = func.find(SET_DEFAULT_TRUE, st)
        if j == -1:
            break
        set_sites.append(j)
        st = j + 1

    for set_j in set_sites:
        after = set_j + 7  # end of mov dl,1; call
        # Prefer boolean-test prefixes
        for i in range(max(0, set_j - 512), set_j - 5):
            if func[i : i + 2] not in (JE_REL32, JNE_REL32):
                continue
            disp = struct.unpack_from("<i", func, i + 2)[0]
            if i + 6 + disp != after:
                continue
            prev2 = func[i - 2 : i] if i >= 2 else b""
            prev4 = func[i - 4 : i] if i >= 4 else b""
            preferred = (
                prev2 == TEST_BL_BL
                or prev4 == CMP_BPL_1
                or prev2 in (
                    bytes([0x84, 0xC0]),
                    bytes([0x84, 0xDB]),
                    bytes([0x84, 0xC9]),
                )
            )
            if preferred:
                return fo_start + i, bytes(func[i : i + 6]), None
        # Fallback: earliest jcc that skips this set site
        for i in range(max(0, set_j - 512), set_j - 5):
            if func[i : i + 2] not in (JE_REL32, JNE_REL32):
                continue
            disp = struct.unpack_from("<i", func, i + 2)[0]
            if i + 6 + disp == after:
                return fo_start + i, bytes(func[i : i + 6]), None

    # Already-patched generic: NOP after known test/cmp prefixes
    for set_j in set_sites:
        for i in range(max(0, set_j - 512), set_j - 5):
            if func[i : i + 6] != NOP_6:
                continue
            prev2 = func[i - 2 : i] if i >= 2 else b""
            prev4 = func[i - 4 : i] if i >= 4 else b""
            if prev2 == TEST_BL_BL or prev4 == CMP_BPL_1:
                return fo_start + i, NOP_6, None

    return None, None, (
        "Could not locate gate skip-branch (cmp bpl,1 / test bl,bl / jcc over "
        "SetIsDefault). Tabbit may have rewritten the gate — re-analyze needed."
    )


# ---------------------------------------------------------------------------
# DLL auto-detection
# ---------------------------------------------------------------------------

def _find_tabbit_dll() -> Tuple[Optional[str], Optional[str]]:
    """Auto-detect the latest Tabbit.dll. Returns (dll_path, version_dir)."""
    candidates = []

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(os.path.join(local, "Tabbit Browser", "Application"))

    for drive in ("C", "D", "E"):
        for user_dir in ("Users\\Stone", "Users\\Administrator"):
            candidates.append(
                f"{drive}:\\{user_dir}\\AppData\\Local\\Tabbit Browser\\Application"
            )

    seen = set()
    uniq = []
    for c in candidates:
        key = os.path.normcase(os.path.normpath(c))
        if key not in seen:
            seen.add(key)
            uniq.append(c)

    for base in uniq:
        if not os.path.isdir(base):
            continue
        versions = []
        for entry in os.listdir(base):
            parts = entry.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                versions.append(entry)
        if not versions:
            continue
        versions.sort(key=lambda v: [int(x) for x in v.split(".")])
        latest = versions[-1]
        dll = os.path.join(base, latest, "Tabbit.dll")
        if os.path.isfile(dll):
            return dll, os.path.join(base, latest)

    return None, None


# ---------------------------------------------------------------------------
# Analysis pipeline (shared by --patch and --status)
# ---------------------------------------------------------------------------

def _analyze(dll_path: str, verbose: bool = True):
    """Run the full analysis pipeline. Returns (data, file_offset, current_bytes) or raises."""
    data = open(dll_path, "rb").read()
    image_base, sections = parse_pe(data)
    text = _get_section(sections, ".text")
    pdata = _get_section(sections, ".pdata")

    if not text or not pdata:
        raise RuntimeError("Missing .text or .pdata section — not a valid Tabbit.dll")

    if verbose:
        print("[1/4] Locating anchor string...")
    string_va, err = _find_string_va(data, sections, image_base)
    if err:
        raise RuntimeError(err)
    if verbose:
        print(f"      Found at VA 0x{string_va:X}")

    if verbose:
        print("[2/4] Finding code reference (LEA RIP-relative)...")
    xref_va, _ = _find_lea_xref(data, text, image_base, string_va)
    if xref_va is None:
        raise RuntimeError("No code reference to anchor string found in .text")
    if verbose:
        print(f"      Found at VA 0x{xref_va:X}")

    if verbose:
        print("[3/4] Resolving function boundaries (.pdata)...")
    func_start, func_end = _find_function(data, pdata, image_base, xref_va)
    if func_start is None:
        raise RuntimeError("Could not find containing function in .pdata")
    if verbose:
        print(f"      Function 0x{func_start:X}..0x{func_end:X} ({func_end - func_start} bytes)")

    if verbose:
        print("[4/4] Locating patch point...")
    file_offset, current_bytes, err = _find_patch_point(
        data, text, image_base, func_start, func_end
    )
    if err:
        raise RuntimeError(err)
    if verbose:
        print(f"      Offset 0x{file_offset:X}, bytes: {current_bytes.hex()}")

    return data, file_offset, current_bytes


# ---------------------------------------------------------------------------
# Unlock commands
# ---------------------------------------------------------------------------

def cmd_status(dll_path: str) -> bool:
    """Check and report patch state."""
    try:
        _, offset, current = _analyze(dll_path)
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return False

    if current == NOP_6:
        print(f"\n[PATCHED] AI unlock is ACTIVE (offset 0x{offset:X})")
        return True
    else:
        print(f"\n[UNPATCHED] Default-browser gate is active (offset 0x{offset:X})")
        return False


def cmd_patch(dll_path: str) -> bool:
    """Apply the AI unlock patch."""
    print(f"Target: {dll_path}\n")

    try:
        data, offset, current = _analyze(dll_path)
    except RuntimeError as e:
        print(f"\n[FAIL] {e}")
        return False

    if current == NOP_6:
        print("\n[OK] Already patched — nothing to do.")
        return True

    bak = dll_path + ".bak"
    if not os.path.exists(bak):
        print(f"\nCreating backup: {os.path.basename(bak)}")
        shutil.copy2(dll_path, bak)
    else:
        print(f"\nBackup already exists: {os.path.basename(bak)}")

    print("Applying patch...")
    patched = bytearray(data)
    patched[offset : offset + 6] = NOP_6

    try:
        with open(dll_path, "wb") as f:
            f.write(patched)
    except PermissionError:
        print("\n[FAIL] Cannot write — is Tabbit Browser still running? Close it first.")
        return False

    verify = open(dll_path, "rb").read()
    if verify[offset : offset + 6] == NOP_6:
        print(f"\n[OK] Patch applied successfully!")
        print(f"     0x{offset:X}: {current.hex()} -> {NOP_6.hex()}")
        return True
    else:
        print("\n[FAIL] Verification failed — file may be corrupted, restore from .bak")
        return False


def cmd_restore(dll_path: str) -> bool:
    """Restore original DLL from backup."""
    bak = dll_path + ".bak"
    if not os.path.exists(bak):
        print(f"[FAIL] No backup found: {bak}")
        return False
    try:
        shutil.copy2(bak, dll_path)
    except PermissionError:
        print("[FAIL] Cannot write — is Tabbit Browser still running? Close it first.")
        return False
    print("[OK] Restored from backup.")
    return True


def cmd_block_updates(version_dir: str) -> bool:
    """Block auto-updates by disabling setup.exe."""
    setup = os.path.join(version_dir, "Installer", "setup.exe")
    disabled = setup + ".disabled"
    if os.path.exists(disabled) and not os.path.exists(setup):
        print("[OK] Updates already blocked.")
        return True
    if os.path.exists(setup):
        os.rename(setup, disabled)
        print("[OK] Updates blocked: setup.exe -> setup.exe.disabled")
        return True
    print("[WARN] setup.exe not found at expected location.")
    return False


def cmd_restore_updates(version_dir: str) -> bool:
    """Re-enable auto-updates."""
    setup = os.path.join(version_dir, "Installer", "setup.exe")
    disabled = setup + ".disabled"
    if os.path.exists(disabled):
        os.rename(disabled, setup)
        print("[OK] Updates restored: setup.exe.disabled -> setup.exe")
        return True
    if os.path.exists(setup):
        print("[OK] setup.exe already present.")
        return True
    print("[WARN] Neither setup.exe nor setup.exe.disabled found.")
    return False


# ---------------------------------------------------------------------------
# BYOK API config
# ---------------------------------------------------------------------------

def _config_path() -> str:
    """Prefer project-local config next to this script."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "api_config.json")


def _load_api_config() -> Optional[dict]:
    path = _config_path()
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_api_config(cfg: dict) -> str:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def cmd_set_api(
    provider: str,
    base_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
) -> bool:
    provider = (provider or "").strip().lower()
    if provider not in DEFAULT_BASE_URLS:
        print(
            f"[FAIL] Unknown provider '{provider}'. "
            "Use: openai | anthropic | openai-compatible"
        )
        return False

    existing = _load_api_config() or {}
    cfg = {
        "provider": provider,
        "base_url": (
            base_url or existing.get("base_url") or DEFAULT_BASE_URLS[provider]
        ).rstrip("/"),
        "api_key": api_key if api_key is not None else existing.get("api_key", ""),
        "model": model or existing.get("model") or DEFAULT_MODELS[provider],
    }

    if not cfg["api_key"]:
        print("[FAIL] --api-key is required (or set previously).")
        return False

    path = _save_api_config(cfg)
    redacted = (
        cfg["api_key"][:6] + "..." + cfg["api_key"][-4:]
        if len(cfg["api_key"]) > 12
        else "***"
    )
    print("[OK] API config saved.")
    print(f"     file     : {path}")
    print(f"     provider : {cfg['provider']}")
    print(f"     base_url : {cfg['base_url']}")
    print(f"     model    : {cfg['model']}")
    print(f"     api_key  : {redacted}")
    print()
    print("Note: Tabbit's built-in AI panel still uses Meituan/Google backends.")
    print("      Prefer: --install-extension  (embedded side panel inside Tabbit)")
    print("      Or:     --byok               (localhost page)")
    return True


def cmd_show_api() -> bool:
    cfg = _load_api_config()
    if not cfg:
        print("[--] No API config found. Use --set-api to create one.")
        return False
    key = cfg.get("api_key", "")
    redacted = key[:6] + "..." + key[-4:] if len(key) > 12 else "***"
    print("[OK] Current API config:")
    print(f"     file     : {_config_path()}")
    print(f"     provider : {cfg.get('provider')}")
    print(f"     base_url : {cfg.get('base_url')}")
    print(f"     model    : {cfg.get('model')}")
    print(f"     api_key  : {redacted}")
    return True


def cmd_clear_api() -> bool:
    path = _config_path()
    if os.path.isfile(path):
        os.remove(path)
        print(f"[OK] Removed {path}")
        return True
    print("[--] No API config to remove.")
    return True


def cmd_byok(port: int, bind: str) -> bool:
    """Launch local BYOK chat panel (standalone localhost page)."""
    cfg = _load_api_config()
    if not cfg or not cfg.get("api_key"):
        print("[FAIL] No API config. Run --set-api first.")
        return False

    try:
        from tabbit_byok import run_server
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from tabbit_byok import run_server
        except ImportError as e:
            print(f"[FAIL] Cannot import tabbit_byok: {e}")
            return False

    print(
        f"[OK] Starting BYOK panel for provider={cfg['provider']} model={cfg['model']}"
    )
    print(f"     Open in Tabbit: http://{bind}:{port}/")
    print("     Tip: prefer --install-extension for a real embedded side panel.")
    run_server(cfg, host=bind, port=port)
    return True


def _extension_src_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "extension")


def _extension_install_dir() -> str:
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "Tabbit Browser", "BYOK Extension")


def _find_tabbit_exe() -> Optional[str]:
    """Locate Tabbit Browser.exe near the Application folder."""
    dll, version_dir = _find_tabbit_dll()
    if version_dir:
        app_root = os.path.dirname(version_dir)
        candidate = os.path.join(app_root, "Tabbit Browser.exe")
        if os.path.isfile(candidate):
            return candidate
        # some layouts put exe next to version dir parent
        for name in ("Tabbit Browser.exe", "chrome.exe"):
            p = os.path.join(app_root, name)
            if os.path.isfile(p):
                return p
    local = os.environ.get("LOCALAPPDATA", "")
    for drive_user in (
        os.path.join(local, "Tabbit Browser", "Application", "Tabbit Browser.exe"),
        r"E:\Users\Stone\AppData\Local\Tabbit Browser\Application\Tabbit Browser.exe",
        r"C:\Users\Stone\AppData\Local\Tabbit Browser\Application\Tabbit Browser.exe",
    ):
        if os.path.isfile(drive_user):
            return drive_user
    return None


def cmd_install_extension() -> bool:
    """Install the BYOK Chromium side-panel extension into Tabbit.

    Copies extension files to a stable path and creates a launcher that starts
    Tabbit with --load-extension so the panel is embedded in the browser UI
    (toolbar icon + side panel). This does NOT replace Meituan's native AI
    backend; it adds a parallel embedded panel for your own API keys.
    """
    src = _extension_src_dir()
    if not os.path.isdir(src) or not os.path.isfile(os.path.join(src, "manifest.json")):
        print(f"[FAIL] Extension source not found: {src}")
        return False

    dst = _extension_install_dir()
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"[OK] Extension installed to:\n     {dst}")

    # Seed config into extension directory for easy import (options page)
    cfg = _load_api_config()
    if cfg:
        seed = os.path.join(dst, "api_config.seed.json")
        with open(seed, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[OK] Seeded API config → {seed}")
        print("     Open extension Options →「从 api_config.json 文本导入」paste its content.")

    exe = _find_tabbit_exe()
    launcher_dir = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(launcher_dir, "launch_tabbit_byok.bat")
    ps1_path = os.path.join(launcher_dir, "launch_tabbit_byok.ps1")

    if not exe:
        print("[WARN] Could not auto-detect Tabbit Browser.exe")
        print("       Load unpacked extension manually:")
        print("       1. Open tabbit://extensions or chrome://extensions")
        print("       2. Enable Developer mode")
        print(f"       3. Load unpacked → {dst}")
        return True

    # Batch launcher (double-click friendly)
    bat = (
        "@echo off\r\n"
        f'start "" "{exe}" --load-extension="{dst}"\r\n'
    )
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)

    ps1 = (
        f'$exe = "{exe}"\n'
        f'$ext = "{dst}"\n'
        'Start-Process -FilePath $exe -ArgumentList "--load-extension=`"$ext`""\n'
    )
    with open(ps1_path, "w", encoding="utf-8") as f:
        f.write(ps1)

    print(f"[OK] Launcher created:\n     {bat_path}")
    print()
    print("How to use the embedded panel:")
    print("  1. Fully quit Tabbit (tray icon too)")
    print("  2. Double-click launch_tabbit_byok.bat  (loads the side-panel extension)")
    print("  3. Click the puzzle / extension icon → pin「Tabbit BYOK AI Panel」")
    print("  4. Click the toolbar icon → side panel opens inside Tabbit")
    print("  5. Configure API: right-click extension → Options")
    print()
    print("Manual alternative (persist without launcher):")
    print("  tabbit://extensions → Developer mode → Load unpacked →")
    print(f"  {dst}")
    return True


def cmd_embed_glic(port: int, bind: str) -> bool:
    """Experimental: point native Glic guest WebView at local BYOK page.

    Uses Chromium switch --glic-guest-url (see RESEARCH_NATIVE_AI.md).
    localhost is already in Tabbit's glicAllowedOrigins.
    This does NOT implement the full Glic guest protocol — the panel may load
    our UI but miss tab-context / host handshake features.
    """
    cfg = _load_api_config()
    if not cfg or not cfg.get("api_key"):
        print("[FAIL] No API config. Run --set-api first.")
        return False

    exe = _find_tabbit_exe()
    if not exe:
        print("[FAIL] Tabbit Browser.exe not found.")
        return False

    guest = f"http://{bind}:{port}/"
    ext = _extension_install_dir()
    args = [exe, f"--glic-guest-url={guest}"]
    # If extension was installed, load it too for a reliable fallback panel
    if os.path.isdir(ext) and os.path.isfile(os.path.join(ext, "manifest.json")):
        args.append(f"--load-extension={ext}")

    # Write experimental launcher
    launcher_dir = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(launcher_dir, "launch_tabbit_embed_glic.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n")
        f.write("REM Experimental: native Glic WebView -> local BYOK\r\n")
        f.write(f'start "" "{exe}" --glic-guest-url={guest}')
        if os.path.isdir(ext):
            f.write(f' --load-extension="{ext}"')
        f.write("\r\n")

    print("[EXPERIMENTAL] Native Glic guest URL override")
    print(f"     guest URL : {guest}")
    print(f"     exe       : {exe}")
    print(f"     launcher  : {bat_path}")
    print()
    print("Notes (read RESEARCH_NATIVE_AI.md):")
    print("  - Tabbit allows http://localhost in glicAllowedOrigins")
    print("  - Host still expects Glic guest protocol; full parity is NOT guaranteed")
    print("  - Prefer --install-extension for reliable embedded BYOK")
    print()
    print("Starting local BYOK server (Ctrl+C stops).")
    print("Fully quit other Tabbit instances, then open AI/Glic panel or use the bat.")

    # Launch browser once, then serve
    try:
        import subprocess
        subprocess.Popen(args, close_fds=True)
        print("[OK] Tabbit process started with --glic-guest-url")
    except Exception as e:
        print(f"[WARN] Could not auto-start Tabbit: {e}")
        print(f"       Run manually: {bat_path}")

    try:
        from tabbit_byok import run_server
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tabbit_byok import run_server

    run_server(cfg, host=bind, port=port)
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tabbit Browser AI Unlock — "
            "bypass the default-browser requirement; optional BYOK OpenAI/Anthropic panel"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s --patch --block-updates
  %(prog)s --status
  %(prog)s --restore --restore-updates
  %(prog)s --set-api --provider openai --api-key sk-xxx --model gpt-4o-mini
  %(prog)s --set-api --provider anthropic --api-key sk-ant-xxx --model claude-sonnet-4-6
  %(prog)s --set-api --provider openai-compatible --base-url https://proxy/v1 --api-key sk-xxx
  %(prog)s --install-extension
  %(prog)s --embed-glic
  %(prog)s --byok
        """,
    )
    parser.add_argument("--patch", action="store_true", help="apply the AI unlock patch")
    parser.add_argument("--restore", action="store_true", help="restore original DLL from backup")
    parser.add_argument("--status", action="store_true", help="check current patch state")
    parser.add_argument("--block-updates", action="store_true", help="block Tabbit auto-updates")
    parser.add_argument("--restore-updates", action="store_true", help="restore auto-updates")
    parser.add_argument("--dll", type=str, default=None, help="explicit path to Tabbit.dll")

    parser.add_argument("--set-api", action="store_true", help="save OpenAI/Anthropic API config")
    parser.add_argument("--show-api", action="store_true", help="show saved API config")
    parser.add_argument("--clear-api", action="store_true", help="delete saved API config")
    parser.add_argument(
        "--install-extension",
        action="store_true",
        help="install embedded BYOK side-panel extension into Tabbit",
    )
    parser.add_argument(
        "--embed-glic",
        action="store_true",
        help="EXPERIMENTAL: start BYOK + launch Tabbit with --glic-guest-url (native panel WebView)",
    )
    parser.add_argument("--byok", action="store_true", help="launch local BYOK chat panel (localhost)")
    parser.add_argument("--provider", type=str, default=None,
                        help="openai | anthropic | openai-compatible")
    parser.add_argument("--base-url", type=str, default=None, help="API base URL")
    parser.add_argument("--api-key", type=str, default=None, help="API key")
    parser.add_argument("--model", type=str, default=None, help="model id")
    parser.add_argument("--port", type=int, default=8765, help="BYOK server port (default 8765)")
    parser.add_argument("--bind", type=str, default="127.0.0.1", help="BYOK bind address")

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    api_actions = any([
        args.set_api, args.show_api, args.clear_api, args.byok,
        args.install_extension, args.embed_glic,
    ])
    unlock_actions = any([
        args.patch, args.restore, args.status, args.block_updates, args.restore_updates
    ])

    if not api_actions and not unlock_actions:
        parser.print_help()
        return 0

    ok = True

    if args.set_api:
        if not args.provider:
            print("[FAIL] --set-api requires --provider")
            return 1
        ok = cmd_set_api(args.provider, args.base_url, args.api_key, args.model) and ok

    if args.show_api:
        ok = cmd_show_api() and ok

    if args.clear_api:
        ok = cmd_clear_api() and ok

    if args.install_extension:
        ok = cmd_install_extension() and ok

    if args.embed_glic:
        return 0 if cmd_embed_glic(args.port, args.bind) else 1

    if args.byok:
        return 0 if cmd_byok(args.port, args.bind) else 1

    if not unlock_actions:
        return 0 if ok else 1

    if args.dll:
        dll_path = args.dll
        version_dir = os.path.dirname(dll_path)
    else:
        dll_path, version_dir = _find_tabbit_dll()

    if not dll_path or not os.path.isfile(dll_path):
        print("[FAIL] Could not find Tabbit.dll. Use --dll to specify the path.")
        return 1

    print(f"Tabbit.dll : {dll_path}")
    print(f"Version dir: {version_dir}")
    print()

    if args.status:
        ok = cmd_status(dll_path) and ok

    if args.restore:
        ok = cmd_restore(dll_path) and ok

    if args.patch:
        ok = cmd_patch(dll_path) and ok

    if args.block_updates:
        ok = cmd_block_updates(version_dir) and ok

    if args.restore_updates:
        ok = cmd_restore_updates(version_dir) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
