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
