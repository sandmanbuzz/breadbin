#!/usr/bin/env python3
"""Build a non-accelerating 32 KiB ROM to smoke-test the SJD-style read hook.

The extension trampoline calls the original JD DSTRT routine unchanged. This
validates 32 KiB bank placement and the JSR/RTS hook contract; it is not a
performance patch and must not be treated as a production drive ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROM16 = 0x4000
EXTENSION_BASE = 0x8000
HOOK_ADDRESS = 0xF4D1
HOOK_EXPECT = bytes.fromhex("20 0A F5")  # JSR $F50A (stock JD DSTRT)
HOOK_REPLACE = bytes.fromhex("20 00 B0")  # JSR $B000 (extension trampoline)
TRAMPOLINE_ADDRESS = 0xB000
TRAMPOLINE = bytes.fromhex("4C 0A F5")  # JMP $F50A


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_smoke_image(base: bytes) -> tuple[bytes, bytes, dict]:
    if len(base) != ROM16:
        raise ValueError(f"JD base must be 16384 bytes, got {len(base)}")
    offset = HOOK_ADDRESS - 0xC000
    if base[offset:offset + 3] != HOOK_EXPECT:
        raise ValueError(
            f"expected JSR $F50A at ${HOOK_ADDRESS:04X}$, "
            f"found {base[offset:offset + 3].hex(' ').upper()}"
        )

    extension = bytearray([0xFF] * ROM16)
    trampoline_offset = TRAMPOLINE_ADDRESS - EXTENSION_BASE
    extension[trampoline_offset:trampoline_offset + len(TRAMPOLINE)] = TRAMPOLINE

    patched_base = bytearray(base)
    patched_base[offset:offset + 3] = HOOK_REPLACE
    image = bytes(extension) + bytes(patched_base)
    manifest = {
        "format": "breadbin-drive-rom-v1",
        "base_sha256": sha256(base),
        "patches": [{
            "address": f"${HOOK_ADDRESS:04X}",
            "expect": HOOK_EXPECT.hex(" ").upper(),
            "replace": HOOK_REPLACE.hex(" ").upper(),
        }],
        "extension": {
            "load_address": f"${EXTENSION_BASE:04X}",
            "trampoline_address": f"${TRAMPOLINE_ADDRESS:04X}",
            "trampoline": "JMP $F50A (stock JD DSTRT)",
        },
        "warning": "SMOKE TEST ONLY: no acceleration; not a production drive ROM",
    }
    return image, bytes(extension), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="user-supplied 16 KiB JD ROM")
    parser.add_argument("--output", required=True, type=Path, help="32 KiB smoke-test ROM output")
    parser.add_argument("--extension-output", type=Path, help="optional 16 KiB extension bank output")
    parser.add_argument("--manifest-output", type=Path, help="optional JSON manifest output")
    args = parser.parse_args()

    try:
        image, extension, manifest = build_smoke_image(args.base.read_bytes())
        args.output.write_bytes(image)
        if args.extension_output:
            args.extension_output.write_bytes(extension)
        if args.manifest_output:
            args.manifest_output.write_text(json.dumps(manifest, indent=2) + chr(10))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"wrote {args.output}: {len(image)} bytes, sha256={sha256(image)}")
    print("SMOKE TEST ONLY: read hook returns to stock JD; no speedup or new feature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
