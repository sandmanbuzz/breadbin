"""Finding 1 of the ce02c7f hater: a held sector must not outlive the disk it came from.

Only the umount path is tested (FastClose): umount reaches ft_close through iec_close, which
clears the drive's state, so the next read re-installs the drive code and its blob zeroes the
held sector. A swap with no umount and no eject is NOT covered (accepted risk, fast-io.md 18.16),
and no layout tried reproduces the stale hit; see docs/hardware-notes.md.
"""
import os
import shutil
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from vicetest import Vice  # noqa: E402
import mkimage  # noqa: E402

IMAGE = os.path.join(ROOT, "build", "breadbin.d64")
WORK = os.path.join(ROOT, "build", "test_fast_swap")
K = 12


def runs(fs, k):
    """starts of k free blocks in a row on one track (physically consecutive sectors), one per track."""
    seen, out = set(), []
    for b in range(1, fs.nblocks - k):
        if any(fs.is_used(b + i) for i in range(k)):
            continue
        ts = [mkimage.block_to_ts(b + i) for i in range(k)]
        if all(ts[i][0] == ts[0][0] and ts[i][1] == ts[0][1] + i for i in range(k)) and ts[0][0] not in seen:
            seen.add(ts[0][0])
            out.append(b)
    return out


def make_disk(tag, with_z, s):
    img = mkimage.load(IMAGE)
    fs = mkimage.FS(img)
    n_root = s + K                       # the root directory moves here
    root = fs.read_inode(mkimage.ROOT_INO)
    old = root["direct"][0]
    fs.set_used(n_root, True)
    img.put_block(n_root, bytearray(img.block(old)))
    fs.set_used(old, False)
    root["direct"][0] = n_root
    fs.write_inode(mkimage.ROOT_INO, root)
    f = fs.alloc_inode(mkimage.T_FILE)
    ino = fs.read_inode(f)
    for i in range(K):
        fs.set_used(s + i, True)
        img.put_block(s + i, bytearray(b"F" * 256))
        ino["direct"][i] = s + i
    ino["size"] = K * 256
    fs.write_inode(f, ino)
    fs.dir_add(mkimage.ROOT_INO, b"f", f)
    if with_z:
        fs.create(mkimage.ROOT_INO, b"z", b"Z" * 256)
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, tag + ".d64")
    with open(path, "wb") as g:
        g.write(img.data)
    return path


def module_base(v):
    import re
    ls = v.run("mod ls")
    base = int(re.search(r"\(fast\): page (\d+)", ls).group(1)) << 8
    with open(os.path.join(ROOT, "build", "mod", "fast.lbl")) as f:
        lbl = {m.group(2): int(m.group(1), 16)
               for m in (re.match(r"al ([0-9A-F]{6}) \.(\S+)", ln) for ln in f) if m}
    return base, lbl


def drive_byte(v, a):
    import re
    out = v._cmd("m 8:%04x 8:%04x" % (a, a), wait=0.3)
    v._cmd("x")
    m = re.search(r">8:%04x\s+([0-9a-f]{2})" % a, out)
    return int(m.group(1), 16) if m else -1


class FastClose(unittest.TestCase):
    def test_close_reinstalls_before_next_read(self):
        """Mechanism (finding 1): a channel close (umount) clears state for the drive, so the next
        fast read re-installs the drive code, and the blob's d_kt is zero: the held sector is dropped.
        The check: state of drive 8 is 0 after umount, and back to 1 after the next fast read."""
        os.makedirs(WORK, exist_ok=True)
        a = make_disk("A", with_z=False, s=runs(mkimage.FS(mkimage.load(IMAGE)), K)[0])
        img = os.path.join(WORK, "boot.d64")
        shutil.copy(IMAGE, img)
        v = Vice(img, warp=True, reu=2048, reu_image=os.path.join(WORK, "reu.img"))
        try:
            v.wait_shell()
            self.assertEqual(v.run("eject", timeout=900), "")
            v._cmd("detach 8")
            v._cmd(f'attach "{a}" 8')
            self.assertEqual(v.run("mount 8 /mnt"), "")
            self.assertEqual(v.run("mod load /lib/km/fast"), "")
            base, lbl = module_base(v)
            st = base + lbl["state"]                             # drive 8 is index 0
            v.run("wc /mnt/f", timeout=900)
            self.assertEqual(v.mem(st, st)[0], 1, "fast path not active before the close")
            self.assertEqual(v.run("umount /mnt"), "")          # the swap path: umount -> iec_close
            self.assertEqual(v.mem(st, st)[0], 0, "the close did not clear the drive's state")
            self.assertEqual(v.run("mount 8 /mnt"), "")
            v.run("wc /mnt/f", timeout=900)
            self.assertEqual(v.mem(st, st)[0], 1, "the next read did not re-install the drive code")
        finally:
            v.close()


if __name__ == "__main__":
    unittest.main()
