# Kernel modules (docs/design/next/modules-v1.md). Included last by the Makefile.
#   build/kexp.{s,inc}, build/khash.inc   the module API, generated from the linked kernel
#   build/root/lib/km/<name>              src/mod/<name>.s as a CX file on the boot disk
# The kernel carries the API hash as one word (src/kernel/khash.s). The hash depends on the final
# link, so a changed hash relinks the kernel once; the word moves no address, which is checked.
KMOD    := $(patsubst src/mod/%.s,%,$(wildcard src/mod/*.s))
# fast.km uses the kernel's JiffyDOS byte routines
ifeq ($(JIFFY),0)
KMOD    := $(filter-out fast,$(KMOD))
endif
KMODCX  := $(patsubst %,$(BUILD)/root/lib/km/%,$(KMOD))

$(BUILD)/khash.inc:
	@mkdir -p $(BUILD)
	@printf '.word 0\n' > $@
$(BUILD)/k/khash.o: $(BUILD)/khash.inc

$(BUILD)/kapi.stamp: $(BUILD)/breadbin.prg src/mod/kapi.txt tools/kexports.py
	python3 tools/kexports.py gen $(BUILD)/kernel.lbl src/mod/kapi.txt $(BUILD)
	@if [ $(BUILD)/khash.inc -nt $(BUILD)/breadbin.prg ]; then \
	  $(MAKE) --no-print-directory $(BUILD)/breadbin.prg && \
	  python3 tools/kexports.py check $(BUILD)/kernel.lbl src/mod/kapi.txt $(BUILD)/khash.inc \
	  || { echo "mk/modules.mk: the kernel moved when its hash word changed" >&2; exit 1; }; fi
	@touch $@

$(BUILD)/kexp.o: $(BUILD)/kapi.stamp
	ca65 $(BUILD)/kexp.s -o $@

$(BUILD)/mod/%.o: src/mod/%.s $(BUILD)/kapi.stamp include/breadbin.inc
	@mkdir -p $(dir $@)
	ca65 -g -I $(BUILD) $(MODFLAGS) $< -o $@

# a module's .incbin and .include files (the font and driver of con80) are inputs too
$(BUILD)/mod/con80.o: src/mod/con80.inc src/mod/con80.font

# link twice (origin $0000 and $0100) and diff into a relocatable CX file, as for programs
$(BUILD)/root/lib/km/%: $(BUILD)/mod/%.o $(BUILD)/kexp.o src/mod/module.cfg tools/cx.py
	@mkdir -p $(dir $@) $(BUILD)/mod
	ld65 -C src/mod/module.cfg -S 0 -Ln $(BUILD)/mod/$*.lbl -o $(BUILD)/mod/$*.0 $< $(BUILD)/kexp.o
	ld65 -C src/mod/module.cfg -S 256 -o $(BUILD)/mod/$*.1 $< $(BUILD)/kexp.o
	python3 tools/cx.py $(BUILD)/mod/$*.0 $(BUILD)/mod/$*.1 $(BUILD)/mod/$*.lbl $@

$(BUILD)/breadbin.d64: $(KMODCX)
