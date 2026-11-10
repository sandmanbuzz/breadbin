"""IOSTAT counters of a running kernel (make IOSTAT=1, the default): how often the block-read mitigation fired.
    BREADBIN_ULTIMATE=host python3 iostat.py IMAGE.prg     # needs IMAGE.lbl next to it; a few small DMA reads, run it after login
imported by dmaboot.py / plainboot.py for the stall dump (decode.py prints it)."""
import re
import sys

IOSTAT_NAMES = ("io_nread io_nretry io_nfail io_neoi", "io_ltrk io_lsct io_lidx io_ltry io_lst io_lwn")


def labels(img):
    return {m.group(2): int(m.group(1), 16) for l in open(img[:-4] + ".lbl")
            for m in [re.match(r"al ([0-9A-F]{6}) \.(\S+)", l)] if m}


def iostat_dump(u, lbl):
    """The counters (16-bit, little endian) and the last-timeout record, or {} for a kernel built IOSTAT=0."""
    if "io_nread" not in lbl:
        return {}
    d = {}
    for n in IOSTAT_NAMES[0].split():
        b = u.readmem(lbl[n], 2)
        d[n] = b[0] | b[1] << 8
    for n in IOSTAT_NAMES[1].split():
        d[n] = u.readmem(lbl[n], 1)[0]
    return d


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    from bench_basic import u
    print({k: f"{v:x}" for k, v in iostat_dump(u, labels(sys.argv[1])).items()})
