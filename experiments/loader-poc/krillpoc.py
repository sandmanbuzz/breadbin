import sys, time
sys.path.insert(0, "/home/user/breadbin/tools")
import vicetest
img = sys.argv[1]; secs = int(sys.argv[2])
with vicetest.Vice(img, warp=True) as v:
    t0 = time.time()
    time.sleep(8)
    for i in range(secs // 10):
        time.sleep(10)
        scr = v.screen()
        print(f"--- t={int(time.time()-t0)}s"); print("\n".join(l for l in scr.splitlines() if l.strip())[:900])
        sys.stdout.flush()
