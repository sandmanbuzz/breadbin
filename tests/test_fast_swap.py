"""A held sector must not outlive the disk it came from (finding 1 of the ce02c7f hater).

Two disks built from the same image. On both, the root directory is moved to block N and
file f (12 blocks) sits on the 12 blocks just before it, so the block a two-sector pass keeps
after f's last block is the root directory. Disk B also has /z. Read f from A (the fast path
keeps the root directory in the drive), swap in B, list /mnt: B's listing must show z. A stale
hit serves A's root directory and z is missing.
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


class FastSwap(unittest.TestCase):
    def test_swap_disk_after_read(self):
        """Find a layout whose last fast read leaves the root directory's sector held (checked in the
        drive: track and sector), then swap disks and list: B's listing must show z."""
        os.makedirs(WORK, exist_ok=True)
        probe = mkimage.FS(mkimage.load(IMAGE))
        starts = runs(probe, K)[:6]
        self.assertTrue(starts, "no free run of %d blocks on one track" % K)
        img = os.path.join(WORK, "boot.d64")
        shutil.copy(IMAGE, img)
        v = Vice(img, warp=True, reu=2048, reu_image=os.path.join(WORK, "reu.img"))
        chosen = None
        try:
            v.wait_shell()
            self.assertEqual(v.run("eject", timeout=900), "")
            for s0 in starts:
                a = make_disk("A", with_z=False, s=s0)
                b = make_disk("B", with_z=True, s=s0)
                v._cmd("detach 8")
                v._cmd(f'attach "{a}" 8')
                v.run("umount /mnt")
                self.assertEqual(v.run("mount 8 /mnt"), "")
                if chosen is None and not v.run("mod ls").count("(fast)"):
                    self.assertEqual(v.run("mod load /lib/km/fast"), "")
                v.run("wc /mnt/f", timeout=900)
                root_ts = mkimage.block_to_ts(s0 + K)
                kt, k2 = drive_byte(v, 0x04EA), drive_byte(v, 0x04EB)
                if (kt, k2) == (root_ts[0], root_ts[1]):
                    chosen = (s0, a, b)
                    break
            if chosen is None:
                self.skipTest("no candidate layout left the root directory's sector held after the read")
            s0, a, b = chosen
            v._cmd("detach 8")
            v._cmd(f'attach "{b}" 8')
            listing = v.run("ls /mnt", timeout=900).split()
            self.assertIn("z", listing, "B's root directory is A's: a held sector from the previous disk")
        finally:
            v.close()

class FastClose(unittest.TestCase):
    def test_close_marks_next_read(self):
        """Mechanism (finding 1): umount (iec_close) leaves ft_inval set, so the next read sends a
        throwaway request and drops any sector the drive still holds."""
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
            v.run("wc /mnt/f", timeout=900)
            self.assertEqual(v.run("umount /mnt"), "")          # the swap path: umount -> iec_close
            inval = v.mem(base + lbl["ft_inval"], base + lbl["ft_inval"])[0]
            self.assertEqual(inval, 1, "ft_close did not mark the next read: a held sector would survive the close")
        finally:
            v.close()


if __name__ == "__main__":
    unittest.main()
