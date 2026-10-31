import sys, time
sys.path.insert(0, "/home/user/breadbin/tools")
import vicetest
with vicetest.Vice(sys.argv[1], warp=True) as v:
    time.sleep(10)
    print(v._cmd("m 8:f7ce f7d5"))
    print(v._cmd("m 8:fffa fffb"))
