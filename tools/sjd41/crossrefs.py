#!/usr/bin/env python3
"""Find changed absolute JSR/JMP call sites from the JD bank into SJD extension ROM.

This is a byte-pattern scanner, not a 6502 disassembler. Results are candidates:
data bytes can coincidentally resemble JSR/JMP instructions.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

ROM16 = 0x4000
ROM32 = 0x8000
BASE_ADDRESS = 0xC000


@dataclass(frozen=True)
class CrossReference:
    source: int
    mnemonic: str
    target: int
    old_bytes: str
    new_bytes: str


def find_cross_references(base: bytes, sjd: bytes) -> list[CrossReference]:
    if len(base) != ROM16:
        raise ValueError(f"JD base must be 16384 bytes, got {len(base)}")
    if len(sjd) != ROM32:
        raise ValueError(f"SJD image must be 32768 bytes, got {len(sjd)}")

    upper = sjd[ROM16:]
    found = []
    for offset in range(ROM16 - 2):
        opcode = upper[offset]
        if opcode not in (0x20, 0x4C):
            continue
        target = upper[offset + 1] | upper[offset + 2] << 8
        if not 0x8000 <= target <= 0xBFFF:
            continue
        new = upper[offset:offset + 3]
        old = base[offset:offset + 3]
        if new == old:
            continue
        found.append(CrossReference(
            source=BASE_ADDRESS + offset,
            mnemonic="JSR" if opcode == 0x20 else "JMP",
            target=target,
            old_bytes=old.hex(" ").upper(),
            new_bytes=new.hex(" ").upper(),
        ))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jd-rom", required=True, type=Path)
    parser.add_argument("--sjd-rom", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON candidate list")
    args = parser.parse_args()

    try:
        refs = find_cross_references(args.jd_rom.read_bytes(), args.sjd_rom.read_bytes())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps([asdict(ref) for ref in refs], indent=2))
    else:
        print(f"{len(refs)} changed absolute JSR/JMP candidates into $8000-$BFFF")
        print("NOTE: raw byte scan only; verify instruction boundaries before treating as hooks.")
        for ref in refs:
            print(
                f"${ref.source:04X}: {ref.mnemonic} ${ref.target:04X} "
                f"[{ref.old_bytes} -> {ref.new_bytes}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
