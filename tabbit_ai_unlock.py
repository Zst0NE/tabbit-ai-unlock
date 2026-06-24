#!/usr/bin/env python3
"""
Tabbit Browser AI Unlock Tool
==============================
Bypass the "must set as default browser to use AI" restriction in Tabbit Browser.

Tabbit Browser (by Meituan) is a Chromium fork with a built-in AI assistant based
on Chrome's Glic (Gemini side panel). Tabbit added a custom native gate that blocks
AI features unless Tabbit is the Windows default browser.

This tool patches Tabbit.dll to remove that restriction. The patch point is located
structurally (not by hardcoded offset) so it works across Tabbit versions.

Usage:
    python tabbit_ai_unlock.py [options]

Options:
    --patch            Apply the bypass patch (auto-creates .bak backup)
    --restore          Restore original DLL from backup
    --status           Check current patch state without modifying
    --block-updates    Rename Installer/setup.exe to prevent auto-updates
    --restore-updates  Restore Installer/setup.exe to re-enable auto-updates
    --dll PATH         Explicit path to Tabbit.dll (auto-detected if omitted)

Examples:
    python tabbit_ai_unlock.py --patch --block-updates
    python tabbit_ai_unlock.py --status
    python tabbit_ai_unlock.py --restore --restore-updates

Requirements:
    Python 3.6+, no external dependencies.
    Tabbit Browser must be CLOSED when patching (DLL is locked while running).

How it works:
    Inside Tabbit.dll there is a function that:
    1. Reads the current Windows default browser name via AssocQueryString
    2. Checks if the name contains "Tabbit"
    3. Calls SetIsDefaultBrowser(true) only if it matches

    The gate is a conditional branch:
        cmp  bpl, 1          ; did the name contain "Tabbit"?
        jne  <epilogue>      ; no -> skip, AI stays locked

    This tool NOPs the jne (6 bytes), so it always falls through to
    SetIsDefaultBrowser(true), unlocking AI regardless of default browser.

Locating strategy (version-resilient):
    1. Find unique string "Checking default browser: current=" in .rdata
    2. Find the LEA RIP-relative xref to it in .text
    3. Use .pdata to get the containing function's boundaries
    4. Within that function, find: cmp bpl,1 + jne rel32
    5. Verify the jne target skips past a SetIsDefault(true) call
    6. NOP the 6-byte jne

License: MIT
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATE_STRING = b"Checking default browser: current="

CMP_BPL_1 = bytes([0x40, 0x80, 0xFD, 0x01])       # cmp bpl, 1
JNE_REL32 = bytes([0x0F, 0x85])                     # jne rel32 (first 2 bytes)
NOP_6     = bytes([0x90] * 6)                        # 6x nop
SET_DEFAULT_TRUE = bytes([0xB2, 0x01, 0xE8])         # mov dl, 1; call ...

VERSION = "1.0.0"


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
    """Within the gate function, find the cmp bpl,1 + jne pattern.
    Returns (file_offset, current_6_bytes, error_msg)."""
    fo_start = text.raw_off + (func_start - image_base - text.va)
    fo_end = text.raw_off + (func_end - image_base - text.va)
    func = data[fo_start:fo_end]
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

        # Case 1: already patched (6x NOP)
        if candidate == NOP_6:
            after = func[jne_off + 6 : jne_off + 512]
            if SET_DEFAULT_TRUE in after:
                return fo_start + jne_off, NOP_6, None
            search_from = idx + 1
            continue

        # Case 2: original jne rel32
        if candidate[:2] != JNE_REL32:
            search_from = idx + 1
            continue

        disp = _i32(data, fo_start + jne_off + 2)
        jne_next = jne_off + 6
        jne_target_rel = jne_next + disp  # relative to func start

        # jne must jump forward
        if disp <= 0:
            search_from = idx + 1
            continue

        # Between jne and its target, SetIsDefault(true) must exist
        between = func[jne_next : min(len(func), jne_target_rel)]
        if SET_DEFAULT_TRUE not in between:
            search_from = idx + 1
            continue

        file_offset = fo_start + jne_off
        return file_offset, bytes(candidate), None

    return None, None, "Could not locate 'cmp bpl, 1; jne' pattern in the gate function."


# ---------------------------------------------------------------------------
# DLL auto-detection
# ---------------------------------------------------------------------------

def _find_tabbit_dll() -> Tuple[Optional[str], Optional[str]]:
    """Auto-detect the latest Tabbit.dll. Returns (dll_path, version_dir)."""
    candidates = []

    # Standard location
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(os.path.join(local, "Tabbit Browser", "Application"))

    # Common custom locations (Windows drive letters)
    for drive in ("C", "D", "E"):
        for user_dir in ("Users\\Stone", "Users\\Administrator"):
            candidates.append(
                f"{drive}:\\{user_dir}\\AppData\\Local\\Tabbit Browser\\Application"
            )

    for base in candidates:
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

    # Step 1
    if verbose:
        print("[1/4] Locating anchor string...")
    string_va, err = _find_string_va(data, sections, image_base)
    if err:
        raise RuntimeError(err)
    if verbose:
        print(f"      Found at VA 0x{string_va:X}")

    # Step 2
    if verbose:
        print("[2/4] Finding code reference (LEA RIP-relative)...")
    xref_va, _ = _find_lea_xref(data, text, image_base, string_va)
    if xref_va is None:
        raise RuntimeError("No code reference to anchor string found in .text")
    if verbose:
        print(f"      Found at VA 0x{xref_va:X}")

    # Step 3
    if verbose:
        print("[3/4] Resolving function boundaries (.pdata)...")
    func_start, func_end = _find_function(data, pdata, image_base, xref_va)
    if func_start is None:
        raise RuntimeError("Could not find containing function in .pdata")
    if verbose:
        print(f"      Function 0x{func_start:X}..0x{func_end:X} ({func_end - func_start} bytes)")

    # Step 4
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
# Commands
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

    # Backup
    bak = dll_path + ".bak"
    if not os.path.exists(bak):
        print(f"\nCreating backup: {os.path.basename(bak)}")
        shutil.copy2(dll_path, bak)
    else:
        print(f"\nBackup already exists: {os.path.basename(bak)}")

    # Patch
    print("Applying patch...")
    patched = bytearray(data)
    patched[offset : offset + 6] = NOP_6

    try:
        with open(dll_path, "wb") as f:
            f.write(patched)
    except PermissionError:
        print("\n[FAIL] Cannot write — is Tabbit Browser still running? Close it first.")
        return False

    # Verify
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
    print(f"[OK] Restored from backup.")
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
    print(f"[WARN] setup.exe not found at expected location.")
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
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tabbit Browser AI Unlock — "
            "bypass the default-browser requirement for AI features"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s --patch --block-updates    Unlock AI and freeze version
  %(prog)s --status                   Check current state
  %(prog)s --restore --restore-updates  Undo everything
        """,
    )
    parser.add_argument("--patch", action="store_true", help="apply the AI unlock patch")
    parser.add_argument("--restore", action="store_true", help="restore original DLL from backup")
    parser.add_argument("--status", action="store_true", help="check current patch state")
    parser.add_argument("--block-updates", action="store_true", help="block Tabbit auto-updates")
    parser.add_argument("--restore-updates", action="store_true", help="restore auto-updates")
    parser.add_argument("--dll", type=str, default=None, help="explicit path to Tabbit.dll")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    if not any([args.patch, args.restore, args.status, args.block_updates, args.restore_updates]):
        parser.print_help()
        return 0

    # Resolve paths
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

    ok = True

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
