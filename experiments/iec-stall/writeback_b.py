"""Q6 write-back on drive B (bus 10): a scratch copy under /Temp/bqwb, U2 from BASIC on device 10, FTP watch, unmount, restore by finally. Needs IEC, IMG, BREADBIN_ULTIMATE and tools/with-lock -r ultimate. Drive A is not touched."""
import json, os, subprocess, sys, time, urllib.request, ftplib
sys.path.insert(0, os.environ["IEC"])
from bench_basic import u, feed, screen
H = os.environ["BREADBIN_ULTIMATE"]
IMG = os.environ["IMG"]
DIR, NAME = "/Temp/bqwb", "/Temp/bqwb/wb.d64"
OFF = 256
PAT = b"WRITEBACK-PROBE"
def put(p, v):
    urllib.request.urlopen(urllib.request.Request(f"http://{H}/v1/configs/{p}?value={v}", method="PUT"), timeout=10).read()
def ftp():
    f = ftplib.FTP(); f.connect(H, 21, timeout=20); f.login(); return f
def has():
    f = ftp(); buf = bytearray()
    f.retrbinary("RETR " + NAME, buf.extend); f.quit()
    return len(buf) == 174848 and bytes(buf[OFF:OFF + len(PAT)]) == PAT
result = {}
B = "Drive%20B%20Settings"
try:
    f = ftp(); f.mkd(DIR)
    with open(IMG, "rb") as src: f.storbinary("STOR " + NAME, src)
    f.quit()
    result["file_before"] = has()
    put(B + "/Drive%20Bus%20ID", 10)        # while disabled: never share bus 9 with drive A
    put(B + "/Drive", "Enabled")
    u.resume()
    u.mount("b", NAME, mode="readwrite")
    u.reset(); time.sleep(12)
    feed('10 open2,10,2,"#"\n'); time.sleep(2)
    feed('20 open15,10,15\n'); time.sleep(2)
    feed('30 print#2,"WRITEBACK-PROBE"\n'); time.sleep(2)
    feed('40 print#15,"u2:2 0 1 1"\n'); time.sleep(2)
    feed('50 input#15,e,m$,t,s:print "u2 status";e;m$;t;s\n'); time.sleep(2)
    feed('60 close2:close15\n'); time.sleep(2)
    feed('run\n'); time.sleep(12)
    result["screen"] = [l for l in screen().splitlines() if "u2" in l or "?" in l][-4:]
    seen = None
    for i in range(45):
        time.sleep(1)
        if has(): seen = i + 1; break
    result["in_file_after_u2_s"] = seen
    u.remove("b")
    time.sleep(3)
    result["in_file_after_unmount"] = has()
finally:
    try: u.remove("b")
    except Exception: pass
    put(B + "/Drive", "Disabled"); put(B + "/Drive%20Bus%20ID", 9)
    subprocess.run(["sh", os.path.join(os.environ["IEC"], "nibsetup.sh"), "down"], check=False)
    try:
        f = ftp()
        try: f.delete(NAME)
        except Exception: pass
        try: f.rmd(DIR)
        except Exception: pass
        f.quit()
    except Exception: pass
    print(json.dumps(result, indent=1), flush=True)
    print("done", flush=True)
