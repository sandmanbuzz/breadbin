#!/usr/bin/env python3
"""Build a private 32 KiB 1541C/1541-II-style ROM from a user's JD ROM.

The proprietary base ROM is supplied by the user and never stored here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROM16 = 0x4000
BANK_SIZE = 0x4000
BASE_SHA256 = "2de4d06b4aa2a1b1129cc641a01cbac7e631de362dbd6fe2129eec7336afad53"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def vectors(image: bytes) -> dict[str, int]:
    bank = image[-ROM16:]
    return {
        "nmi": bank[0x3FFA] | bank[0x3FFB] << 8,
        "reset": bank[0x3FFC] | bank[0x3FFD] << 8,
        "irq": bank[0x3FFE] | bank[0x3FFF] << 8,
    }


def inspect(path: Path) -> int:
    raw = path.read_bytes()
    print(f"file: {path}\nbytes: {len(raw)}\nsha256: {sha256(raw)}")
    if len(raw) not in (ROM16, 2 * ROM16):
        print("error: expected 16384 or 32768 bytes", file=sys.stderr)
        return 2
    mapping = (
        "16 KiB JD bank at $C000-$FFFF"
        if len(raw) == ROM16
        else "32 KiB image; upper bank at $C000-$FFFF"
    )
    print(f"mapping: {mapping}")
    print("vectors: " + " ".join(
        f"{key.upper()}=${value:04X}" for key, value in vectors(raw).items()
    ))
    if len(raw) == ROM16:
        known = "yes" if sha256(raw) == BASE_SHA256 else "no"
        print(f"known supplied JD 6.01 hash: {known}")
    return 0


def parse_address(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an address")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError("address must be an integer or hexadecimal string")
    text = value.strip()
    if text.startswith("$"):
        return int(text[1:], 16)
    return int(text, 0)


def build(
    base_path: Path, extension_path: Path, manifest_path: Path, output_path: Path
) -> int:
    base = base_path.read_bytes()
    extension = extension_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not isinstance(manifest, dict) or manifest.get("format") != "breadbin-drive-rom-v1":
        raise ValueError("unsupported manifest format")
    if len(base) != ROM16:
        raise ValueError(f"base must be 16384 bytes, got {len(base)}")
    if len(extension) != BANK_SIZE:
        raise ValueError(f"extension must be 16384 bytes, got {len(extension)}")

    actual_hash = sha256(base)
    expected_hash = manifest.get("base_sha256")
    if not isinstance(expected_hash, str) or actual_hash.lower() != expected_hash.lower():
        raise ValueError(f"base SHA-256 mismatch: expected {expected_hash!r}, got {actual_hash}")

    patches = manifest.get("patches", [])
    if not isinstance(patches, list):
        raise ValueError("patches must be an array")

    patched = bytearray(base)
    occupied: set[int] = set()
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            raise ValueError(f"invalid patch #{index}: expected an object")
        try:
            address = parse_address(patch["address"])
            old = bytes.fromhex(patch["expect"])
            new = bytes.fromhex(patch["replace"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid patch #{index}: {exc}") from exc

        if not 0xC000 <= address <= 0xFFFF:
            raise ValueError(f"patch #{index}: address outside $C000-$FFFF")
        offset = address - 0xC000
        if not old or len(old) != len(new) or offset + len(old) > ROM16:
            raise ValueError(f"patch #{index}: invalid length or bank crossing")
        span = range(offset, offset + len(old))
        if any(byte in occupied for byte in span):
            raise ValueError(f"patch #{index}: overlaps prior patch")
        if bytes(patched[offset:offset + len(old)]) != old:
            found = bytes(patched[offset:offset + len(old)])
            raise ValueError(
                f"patch #{index} at ${address:04X}: expected {old.hex()}, found {found.hex()}"
            )
        occupied.update(span)
        patched[offset:offset + len(new)] = new

    result = extension + bytes(patched)
    output_path.write_bytes(result)
    print(f"wrote {output_path} ({len(result)} bytes), SHA-256 {sha256(result)}")
    print(
        f"layout: extension $8000-$BFFF; JD-derived bank $C000-$FFFF; "
        f"{len(patches)} patch records"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("rom", type=Path)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--base", required=True, type=Path)
    build_parser.add_argument("--extension", required=True, type=Path)
    build_parser.add_argument("--manifest", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "inspect":
            return inspect(args.rom)
        return build(args.base, args.extension, args.manifest, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
