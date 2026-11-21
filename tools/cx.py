#!/usr/bin/env python3
"""Make a page-relocatable Breadbin executable (CX format).

The program is linked twice, at origin $0000 and $0100. Bytes that differ
by exactly one are high bytes of absolute addresses; their offsets form the
relocation table. The loader adds the load page to each of them.

Usage: cx.py A.bin B.bin LABELS OUT                          (format 1, a program)
       cx.py --lib NAMES A.bin B.bin LABELS OUT STUB          (format 3, a library)
       cx.py --import PATH LIB A.bin B.bin C.bin LABELS OUT   (format 2, importing LIB)
  LABELS is an ld65 -Ln file (gives __BSS_SIZE__, and a library's exports).

The version byte is the format (the binfmt), all little-endian:
1  "CX", 1, image size (2), bss size (2), reloc count (2), image, reloc offsets (2 each).
3  a library: format 1's layout and no BSS (one copy serves every process that imports it).
   Image bytes 0-1 are the library id, a hash of its exports (NAMES, comma-separated, zp:name for a
   zero-page one: name and offset, or value for zero page), so a program linked against another export table
   is refused, while a fix that keeps the table needs no relink. STUB is ca65 source defining
   the exports as LIBBASE + offset for the importer's links.
2  a program importing one library: "CX", 2, image (2), bss (2), reloc count (2), library reloc
   count (2), library id (2), the library's path (16, NUL-padded); image, reloc offsets, library
   reloc offsets (2 each: the loader adds the library's first page). Linked three times: A at
   origin $0000 with the stub at LIBBASE $0000, B at $0100, C with LIBBASE $0100.
"""
import re
import struct
import sys
import zlib

LIBBASE = 0x0000                # the stub's base in the first link, as programs link at $0000


def relocs(a, b):
    if len(a) != len(b):
        raise ValueError("builds differ in size")
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            if (x + 1) & 0xff != y:
                raise ValueError(f"offset {i:#x}: {x:#x} vs {y:#x} is not a high byte")
            out.append(i)
    return out


def make_cx(a, b, bss):
    r = relocs(a, b)
    hdr = b"CX" + bytes([1]) + struct.pack("<HHH", len(a), bss, len(r))
    return hdr + bytes(a) + b"".join(struct.pack("<H", o) for o in r)


def make_lib(a, b, bss, exports):
    """(format 3 bytes, id) for a library whose exports are {name: (offset or zp value, zp)}."""
    if bss:
        raise ValueError("a library has no BSS: its state is per process")
    if len(a) < 2 or a[:2] != b"\0\0":
        raise ValueError("a library image starts with two zero bytes for its id")
    r = relocs(a, b)
    lid = lib_id(exports)
    img = struct.pack("<H", lid) + bytes(a[2:])
    return b"CX" + bytes([3]) + struct.pack("<HHH", len(img), 0, len(r)) + img + \
        b"".join(struct.pack("<H", o) for o in r), lid


def lib_id(exports):
    text = ";".join("%s=%s%d" % (n, "z" if zp else "", v) for n, (v, zp) in sorted(exports.items()))
    return (zlib.crc32(text.encode()) & 0xFFFF) or 1


def lib_exports(labels_text, names):
    """{name: (value, zp)} from an ld65 -Ln file of the library linked at $0000; a name written
    zp:name is a zero-page export (a value, not an offset)."""
    out = {}
    for n in names:
        zp = n.startswith("zp:")
        n = n[3:] if zp else n
        m = re.search(r"al ([0-9A-Fa-f]+) \.%s$" % re.escape(n), labels_text, re.M)
        if not m:
            raise ValueError("export %s not in the labels" % n)
        v = int(m.group(1), 16)
        if zp and v > 0xFF:
            raise ValueError("export %s is not in zero page" % n)
        out[n] = (v, zp)
    return out


def lib_stub(exports):
    """ca65 source: each export as LIBBASE + offset (LIBBASE given with -D), zero page as is."""
    lines = []
    for n, (v, zp) in sorted(exports.items()):
        if zp:
            lines += [".exportzp %s" % n, "%s = $%02X" % (n, v)]
        else:
            lines += [".export %s" % n, "%s = LIBBASE + $%04X" % (n, v)]
    return "\n".join(lines) + "\n"


def make_import(a, b, c, bss, path, lid):
    """Format 2: a program (links a, b at $0000/$0100, c with the library moved a page)."""
    if not (len(a) == len(b) == len(c)):
        raise ValueError("builds differ in size")
    r = relocs(a, b)
    lr = relocs(a, c)
    both = set(r) & set(lr)
    if both:
        raise ValueError("offsets %s move with both the program and the library" % sorted(both))
    if not path.startswith("/"):
        raise ValueError("library path must be absolute: %r" % path)  # resolved in the kernel
    p = path.encode()
    if len(p) > 15:
        raise ValueError("library path over 15 bytes")
    hdr = b"CX" + bytes([2]) + struct.pack("<HHHHH", len(a), bss, len(r), len(lr), lid) + p.ljust(16, b"\0")
    return hdr + bytes(a) + b"".join(struct.pack("<H", o) for o in r + lr)


def bss_size(labels_text):
    m = re.search(r"al ([0-9A-Fa-f]+) \.__BSS_SIZE__", labels_text)
    return int(m.group(1), 16) if m else 0


def main():
    if sys.argv[1] == "--lib":
        names, a, b, labels, out, stub = sys.argv[2:8]
        with open(labels) as f:
            text = f.read()
        ex = lib_exports(text, names.split(","))
        data, _ = make_lib(open(a, "rb").read(), open(b, "rb").read(), bss_size(text), ex)
        with open(out, "wb") as f:
            f.write(data)
        with open(stub, "w") as f:
            f.write(lib_stub(ex))
        return
    if sys.argv[1] == "--import":
        path, lib, a, b, c, labels, out = sys.argv[2:9]
        ld = open(lib, "rb").read()
        if ld[:3] != b"CX\x03":
            raise ValueError("%s is not a library" % lib)
        lid = ld[9] | ld[10] << 8
        with open(labels) as f:
            bss = bss_size(f.read())
        data = make_import(open(a, "rb").read(), open(b, "rb").read(), open(c, "rb").read(), bss, path, lid)
        with open(out, "wb") as f:
            f.write(data)
        return
    a, b, labels, out = sys.argv[1:5]
    with open(a, "rb") as f:
        da = f.read()
    with open(b, "rb") as f:
        db = f.read()
    with open(labels) as f:
        bss = bss_size(f.read())
    with open(out, "wb") as f:
        f.write(make_cx(da, db, bss))


if __name__ == "__main__":
    main()
