#!/usr/bin/env python3
"""Inspect/apply SJD41 generator patch tables. Inputs are operator-supplied."""
from __future__ import annotations
import argparse, hashlib, sys
from dataclasses import dataclass
from pathlib import Path

SECTORS = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
FILES = {"stage1": "1.JD/E0&CBM/C0-G", "cbm": "2.CBM/E0-GENERAT", "sjd": "3.SJD/E0-GENE460"}

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class D64:
    def __init__(self, raw: bytes):
        if len(raw) != 174848:
            raise ValueError(f"expected 35-track D64 (174848 bytes), got {len(raw)}")
        self.raw, self.starts = raw, []
        total = 0
        for count in SECTORS:
            self.starts.append(total); total += count

    def sector(self, track: int, sector: int) -> bytes:
        if not 1 <= track <= 35 or not 0 <= sector < SECTORS[track - 1]:
            raise ValueError(f"invalid D64 sector {track}/{sector}")
        off = (self.starts[track - 1] + sector) * 256
        return self.raw[off:off + 256]

    def file(self, track: int, sector: int) -> bytes:
        out, seen = bytearray(), set()
        while track:
            if (track, sector) in seen: raise ValueError(f"sector-chain loop at {track}/{sector}")
            seen.add((track, sector)); block = self.sector(track, sector)
            nt, ns = block[0], block[1]
            out.extend(block[2:] if nt else block[2:2 + ns - 1])
            track, sector = nt, ns
        return bytes(out)

    def prgs(self) -> dict[str, bytes]:
        out, seen = {}, set()
        track, sector = 18, 1
        while track:
            if (track, sector) in seen: raise ValueError("directory-chain loop")
            seen.add((track, sector)); block = self.sector(track, sector)
            for i in range(8):
                e = block[2 + i * 32:2 + (i + 1) * 32]
                if (e[0] & 7) == 2:
                    name = e[3:19].decode("latin-1").replace("\xa0", " ").strip()
                    out[name] = self.file(e[1], e[2])
            track, sector = block[0], block[1]
        return out

@dataclass(frozen=True)
class Record:
    address: int
    payload: bytes

@dataclass(frozen=True)
class Table:
    marker: int
    start: int
    end: int
    records: tuple[Record, ...]

def parse_table(prg: bytes) -> Table:
    if len(prg) < 12: raise ValueError("PRG too short")
    load = prg[0] | prg[1] << 8
    if load != 0x0801: raise ValueError(f"expected BASIC load address $0801, got ${load:04X}")
    pos, previous_end = 2, None
    while pos + 2 <= len(prg):
        nxt = prg[pos] | prg[pos + 1] << 8
        if nxt == 0:
            if previous_end != pos - 1 or prg[pos - 1] != 0:
                raise ValueError("BASIC end pointer lacks preceding line terminator")
            marker_file, start_file = pos - 1, pos + 2
            marker, start = load + marker_file - 2, load + start_file - 2
            break
        next_pos = nxt - load + 2
        if next_pos <= pos + 4 or next_pos > len(prg):
            raise ValueError(f"invalid BASIC link ${nxt:04X} at {pos}")
        line_end = prg.find(b"\0", pos + 4, next_pos)
        if line_end != next_pos - 1: raise ValueError(f"malformed BASIC line at {pos}")
        previous_end, pos = line_end, next_pos
    else: raise ValueError("BASIC end pointer not found")

    records, cursor = [], start_file
    while cursor + 3 <= len(prg):
        lo, hi, n = prg[cursor:cursor + 3]
        if lo == hi == n == 0:
            return Table(marker, start, load + cursor + 1, tuple(records))
        size = n or 256
        end = cursor + 3 + size
        if end > len(prg): raise ValueError(f"truncated payload at PRG offset {cursor}")
        records.append(Record(lo | hi << 8, prg[cursor + 3:end]))
        cursor = end
    raise ValueError("patch-table terminator not found")

def apply(memory: bytearray, table: Table) -> None:
    for record in table.records:
        end = record.address + len(record.payload)
        if end > 0x10000: raise ValueError(f"record ${record.address:04X} crosses 64 KiB")
        memory[record.address:end] = record.payload

def mismatch_runs(a: bytes, b: bytes, base: int):
    result = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y: continue
        addr = base + i
        if not result or addr > result[-1][1] + 1: result.append([addr, addr, 1])
        else: result[-1][1], result[-1][2] = addr, result[-1][2] + 1
    return result

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--disk", required=True, type=Path)
    p.add_argument("--jd-rom", required=True, type=Path)
    p.add_argument("--compare-sjd", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--summary-only", action="store_true")
    a = p.parse_args()
    try:
        files = D64(a.disk.read_bytes()).prgs()
        tables = {}
        for key, name in FILES.items():
            if name not in files: raise ValueError(f"missing PRG {name!r}")
            tables[key] = parse_table(files[name])
        for key, t in tables.items():
            ds = [r.address for r in t.records]
            de = [r.address + len(r.payload) - 1 for r in t.records]
            total = sum(len(r.payload) for r in t.records)
            print(f"{key}: {len(t.records)} records, {total} payload bytes")
            print(f"  marker ${t.marker:04X}, table ${t.start:04X}, end ${t.end:04X}; destinations ${min(ds):04X}-${max(de):04X}")
            if not a.summary_only:
                for i, r in enumerate(t.records):
                    print(f"  {i:02d}: ${r.address:04X}-${r.address + len(r.payload) - 1:04X}, {len(r.payload)} bytes, sha256={digest(r.payload)[:16]}")

        jd = a.jd_rom.read_bytes()
        if len(jd) != 0x4000: raise ValueError(f"JD image must be 16 KiB, got {len(jd)}")
        mem = bytearray(0x10000)
        mem[0x8000:0xA000] = jd[0x2000:0x4000]
        apply(mem, tables["stage1"])
        captured = bytes(mem[0x8000:0xA000])
        mem = bytearray(0x10000)
        mem[0x6000:0x8000] = captured
        apply(mem, tables["sjd"])
        generated = bytes(mem[0x6000:0x8000])
        spill = bytes(mem[0x8000:0x8065])
        print(f"\nE000-FFFF output: {len(generated)} bytes, sha256={digest(generated)}")
        print(f"Stage-3 spill beyond $7FFF: 101 bytes, sha256={digest(spill)}")
        if a.output:
            a.output.write_bytes(generated); print(f"wrote {a.output}")
        if a.compare_sjd:
            sjd = a.compare_sjd.read_bytes()
            if len(sjd) != 0x8000: raise ValueError(f"SJD image must be 32 KiB, got {len(sjd)}")
            diff = mismatch_runs(generated, sjd[0x6000:0x8000], 0xE000)
            print(f"comparison: {sum(r[2] for r in diff)} differing bytes in {len(diff)} runs")
            for start, end, count in diff: print(f"  ${start:04X}-${end:04X}: {count} byte(s)")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2

if __name__ == "__main__":
    raise SystemExit(main())
