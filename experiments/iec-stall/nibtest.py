"""Steps of the Keymaster nibbler test on the real drives (run by hand between nibsetup.sh up and down, under the lock).

    BREADBIN_ULTIMATE=host python3 nibtest.py load          # run the nibbler by DMA, print the menu
    BREADBIN_ULTIMATE=host python3 nibtest.py keys 'text'   # type text (\\n = Return), wait 3 s, print the screen
    BREADBIN_ULTIMATE=host python3 nibtest.py screen        # print the screen (one DMA read: never during a transfer)
    BREADBIN_ULTIMATE=host python3 nibtest.py wait N        # poll one screen byte every 5 s until it changes, max N s

The nibbler comes from the Ultimate's SD card (NIBBLER env: the file path on the Ultimate, fetched over FTP by the caller).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_basic import feed, screen, u  # noqa: E402

cmd = sys.argv[1]
if cmd == "load":
    u.resume()
    u.reset()
    time.sleep(8)
    u.run_prg(open(os.environ["NIBBLER"], "rb").read())
    time.sleep(12)
    print(screen())
elif cmd == "keys":
    feed(sys.argv[2].replace("\\n", "\n"))
    time.sleep(3)
    print(screen())
elif cmd == "screen":
    print(screen())
elif cmd == "wait":
    t0 = time.time()
    first = bytes(u.readmem(0x0400 + 40 * 12, 40))
    while time.time() - t0 < int(sys.argv[2]):
        time.sleep(5)
        if bytes(u.readmem(0x0400 + 40 * 12, 40)) != first:
            break
    print(f"changed or timed out after {time.time() - t0:.0f} s")
    print(screen())
