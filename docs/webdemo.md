# Browser demo bundle

`tools/webdemo.py` packages Breadbin for a browser: EmulatorJS running the VICE x64sc core on the
MEGA65 Open ROMs. It is ported from upstream (Konstantinos Patronas, MIT; upstream aa2f787, cache
fix 9210ff2) and produces a **local directory only**; nothing is published or hosted from here.

## What is in the repo and what is not

The emulator, the core and the Open ROMs are GPL/LGPL and stay outside the repo, in the
"webdemo tool" (a directory with `build_core.sh`, `make_webdemo.py` and, once built, `kit/`).
The script refuses with a message if `kit/` is missing. No Commodore ROM is needed: Breadbin
replaces the KERNAL.

## Use

```sh
make webdemo WEBDEMO=/path/to/webdemo-tool     # build/webdemo/ and build/webdemo.zip
```

(`build/` is ignored.) This builds `build/breadbin.prg` and `build/breadbin.reu`, the same REU
root image `make run-reu-root` boots (256 KB, block b at offset b*256), then writes:

- `index.html`, the page (login hint, credits);
- `breadbin-web-HASH.zip` with `breadbin.prg` and `breadbin.reu`. EmulatorJS caches a game by
  URL for days, so the name carries a hash of the contents and returning visitors get new
  releases;
- `data/`, the emulator kit copied from the tool;
- `LICENSES/`, the licence texts and the build scripts of the core (the source offer).

Any hosted copy must ship `LICENSES/` as is. Hosting is the owner's call.

The core has no drive, so the kernel is the autostarted `.prg` and the root is the REU
(`root on reu` at boot). Writes live in the page's RAM until it is closed.

Status: no real bundle has been built, because the external emulator kit is absent on the build machine;
`tools/test_webdemo.py` ran only against a fake kit. Boot time to a shell prompt is unmeasured; the measured
figure is time to the `login:` screen with `root on reu` shown: 2.4 s real time, 1.2 s in warp.
