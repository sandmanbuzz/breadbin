# The p-code VM as a shared library (docs/design/pvm.md): src/pvm/pvm.s as CX format 3 at
# /lib/pvm on the boot disk; build/pvm/pvmstub.s is what p-code programs link against
# (tools/pvmlink.py prog). Included last by the Makefile.
$(BUILD)/pvm/pvm: src/pvm/pvm.s src/pvm/pvm.cfg tools/pvmlink.py tools/cx.py $(wildcard include/*.inc)
	@mkdir -p $(dir $@)
	python3 tools/pvmlink.py lib $(BUILD)/pvm >/dev/null

$(BUILD)/root/lib/pvm: $(BUILD)/pvm/pvm
	@mkdir -p $(dir $@)
	cp $< $@

$(BUILD)/breadbin.d64: $(BUILD)/root/lib/pvm

# p-code programs from mini C (tools/cc.py --pcode): src/pc/NAME.c -> /bin/NAME, CX format 2
# importing /lib/pvm. A static pattern rule, so it wins over the assembly programs' rule.
PCPROGS := $(patsubst src/pc/%.c,%,$(wildcard src/pc/*.c))
PCBIN   := $(patsubst %,$(BUILD)/root/bin/%,$(PCPROGS))
$(if $(filter $(PROGS),$(PCPROGS)),$(error src/pc and src/bin both make $(filter $(PROGS),$(PCPROGS))))

$(BUILD)/pc/%.s: src/pc/%.c tools/cc.py tools/cc_pcode.py
	@mkdir -p $(dir $@)
	python3 tools/cc.py --pcode $< > $@.tmp
	mv $@.tmp $@

$(BUILD)/pc/%.o: $(BUILD)/pc/%.s src/pvm/pvm.inc include/breadbin.inc
	ca65 -I include -I src/pvm -o $@ $<

$(PCBIN): $(BUILD)/root/bin/%: $(BUILD)/pc/%.o $(BUILD)/pvm/pvm tools/pvmlink.py tools/cx.py
	@mkdir -p $(dir $@)
	python3 tools/pvmlink.py prog $@ $(BUILD)/pvm $< >/dev/null

$(BUILD)/breadbin.d64: $(PCBIN)
