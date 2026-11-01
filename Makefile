# Breadbin build
BUILD   := build
KSRC    := $(wildcard src/kernel/*.s)
KOBJ    := $(patsubst src/kernel/%.s,$(BUILD)/k/%.o,$(KSRC))
PROGS   := $(patsubst src/bin/%.s,%,$(wildcard src/bin/*.s))
CX      := $(patsubst %,$(BUILD)/root/bin/%,$(PROGS))
LIBSRC  := $(wildcard src/lib/*.s)
LIBOBJ  := $(BUILD)/lib/breadbin.lib
ROOTSRC := $(shell find rootfs -type f)

.PHONY: FORCE all clean test test-host test-smoke test-only test-keyboard test-console size run run-reu
.SECONDARY:
all: $(BUILD)/breadbin.d64

# make CACHE=0 builds a kernel whose REU block cache stays off until `cache on` (bench images)
CACHE   ?= 1
$(BUILD)/cache.stamp: FORCE
	@mkdir -p $(BUILD)
	@echo "$(CACHE)" | cmp -s - $@ || echo "$(CACHE)" > $@
FORCE:
$(BUILD)/k/blk.o: $(BUILD)/cache.stamp

$(BUILD)/k/%.o: src/kernel/%.s src/kernel/k.inc src/kernel/uci.inc include/breadbin.inc
	@mkdir -p $(dir $@)
	ca65 -g -I src/kernel -D CACHE_DEFAULT=$(CACHE) $< -o $@

$(BUILD)/breadbin.prg: $(KOBJ) src/kernel.cfg
	ld65 -C src/kernel.cfg -m $(BUILD)/kernel.map -Ln $(BUILD)/kernel.lbl -o $@ $(KOBJ)

$(BUILD)/lib/%.o: src/lib/%.s src/lib/lib.inc include/breadbin.inc
	@mkdir -p $(dir $@)
	ca65 -g $< -o $@

$(LIBOBJ): $(patsubst src/lib/%.s,$(BUILD)/lib/%.o,$(LIBSRC))
	rm -f $@
	ar65 a $@ $^

$(BUILD)/p/%.o: src/bin/%.s include/breadbin.inc
	@mkdir -p $(dir $@)
	ca65 -g $< -o $@

# link twice (origin $0000 and $0100) and diff into a relocatable CX file
$(BUILD)/root/bin/%: $(BUILD)/p/%.o $(LIBOBJ) src/prog.cfg tools/cx.py
	@mkdir -p $(dir $@) $(BUILD)/p
	ld65 -C src/prog.cfg -S 0 -Ln $(BUILD)/p/$*.lbl -o $(BUILD)/p/$*.0 $< $(LIBOBJ)
	ld65 -C src/prog.cfg -S 256 -o $(BUILD)/p/$*.1 $< $(LIBOBJ)
	python3 tools/cx.py $(BUILD)/p/$*.0 $(BUILD)/p/$*.1 $(BUILD)/p/$*.lbl $@

$(BUILD)/breadbin.d64: $(BUILD)/breadbin.prg $(CX) $(ROOTSRC) tools/mkimage.py
	@mkdir -p $(BUILD)/root
	cp -R rootfs/. $(BUILD)/root/
	python3 tools/mkimage.py build $@ --boot $(BUILD)/breadbin.prg --root $(BUILD)/root --dev console:1 --dev null:0

test-host:
	python3 -m unittest discover -s tools -p 'test_*.py'

# A few minutes: the boot, scheduler, pipe and Ctrl-C paths. Run after any kernel change.
SMOKE := tests.test_system.Boot.test_00_kernal_is_shadowed \
         tests.test_system.Boot.test_02_echo \
         tests.test_system.Boot.test_05_pipe_three_stages \
         tests.test_system.Boot.test_13_ctrl_c_blocked_reader
test-smoke: all test-host
	python3 -m unittest $(SMOKE) -v

# Real keystrokes through VICE's keyboard matrix (needs xdotool and a display):
#   xvfb-run -a -s "-screen 0 1280x1024x24" make test-keyboard
test-keyboard: all
	python3 -m unittest tests.test_keyboard -v

test-console: all
	python3 -m unittest tests.test_console -v

# Targeted: make test-only T="tests.test_system.Boot.test_24_editor tests.test_system.REU"
test-only: all
	python3 -m unittest $(T) -v

test: all test-host
	python3 -m unittest discover -s tests -p 'test_*.py' -v

run: all
	x64sc -autostart $(BUILD)/breadbin.d64

run-reu: all
	x64sc -reu -reusize 512 -autostart $(BUILD)/breadbin.d64

clean:
	rm -rf $(BUILD)

# byte budget per kernel module and the headroom left
size: all
	python3 tools/size.py
