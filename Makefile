CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra
SRC     := sim/main.c sim/board.c sim/switchsim.c sim/mcs4.c sim/ref4004.c

all: i4004 netlist/4004.net

i4004: $(SRC) $(wildcard sim/*.h)
	$(CC) $(CFLAGS) -o $@ $(SRC)

# Rebuild the netlist from the mask-layer bitmaps (needs python3 with numpy + Pillow)
netlist/4004.net: tools/extract_netlist.py tools/layout.py
	python3 tools/extract_netlist.py source/analyzer netlist/4004.json

%.bin: %.asm tools/asm4004.py
	python3 tools/asm4004.py $< $@

# Cross-check the transistor-level chip against the reference emulator.
# Work files (binaries, logs, fuzz programs) are left in build/.
test: i4004
	@for t in hello alu accumulator memory; do tools/crosscheck.sh tests/$$t.asm || exit 1; done
	@tools/crosscheck.sh tests/control.asm --test 0
	@tools/crosscheck.sh tests/control.asm --test 1
	@tools/crosscheck.sh demo/birthday.asm
	@mkdir -p build/fuzz
	@for seed in $$(seq 1 $${FUZZ:-25}); do \
		python3 tests/fuzz.py $$seed > build/fuzz/fuzz$$seed.asm; \
		tools/crosscheck.sh build/fuzz/fuzz$$seed.asm --test $$((seed % 2)) || exit 1; \
	done

demo: i4004 demo/birthday.bin
	./i4004 demo/birthday.bin

clean:
	rm -f i4004

.PHONY: all clean test demo web video vectors test-independent

# Single-file browser demo: the birthday program running on the die photograph
web: demo/birthday.bin
	python3 tools/align_photo.py source/analyzer source/4004-composite-photo.jpg netlist/photo_align.json
	python3 tools/build_web.py source/analyzer source/4004-composite-photo.jpg netlist/photo_align.json \
		demo/birthday.bin web/template.html web/sim4004.js web/4004-birthday.html

# Vertical 1080x1920 video of the run (needs ffmpeg; fonts in video/fonts/)
video: i4004 demo/birthday.bin
	mkdir -p build/video
	./i4004 --quiet --dump build/video/run --extra 400 demo/birthday.bin
	python3 tools/make_video.py build/video/run demo/birthday.bin video/4004-birthday.mp4

# Single-instruction test vectors from the transistor-level chip (see vectors/README.md)
i4004-vectors: sim/vectors.c sim/switchsim.c sim/switchsim.h
	$(CC) $(CFLAGS) -o $@ sim/vectors.c sim/switchsim.c

vectors: i4004-vectors
	python3 tools/gen_vectors.py vectors/v1 400
	python3 tools/analyze_vectors.py vectors/v1

# Busicom 141-PF calculator firmware on the transistor-level chip (see docs/BUSICOM.txt)
BUSICOM_SRC := busicom/busicom.c sim/board.c sim/switchsim.c sim/mcs4.c sim/ref4004.c
BUSICOM_ROM := source/busicom/busicom-141pf.bin

i4004-busicom: $(BUSICOM_SRC) $(wildcard sim/*.h)
	$(CC) $(CFLAGS) -o $@ $(BUSICOM_SRC)

# Demo: square root of 2 on the transistor-level chip (about 15-30 s)
busicom: i4004-busicom netlist/4004.net
	./i4004-busicom 2 SQRT

# 49 calculations, transistor level vs reference (bus logs) and vs the arithmetic.
# About 5 min on 12 threads; JOBS=n to change the parallelism.
test-busicom: i4004-busicom netlist/4004.net
	python3 busicom/test_busicom.py $(if $(JOBS),-j $(JOBS))

# Rebuild the ROM image from the annotated listing (not kept in this tree; see
# source/busicom/NOTICE.txt for where to download it) and check it is the same image.
busicom-rom:
	@test -n "$(LISTING)" || { echo "usage: make busicom-rom LISTING=path/to/Busicom-141PF-Calculator_asm_rel-1-0-1.txt"; exit 2; }
	mkdir -p build/busicom
	python3 -I busicom/extract_rom.py "$(LISTING)" build/busicom/busicom-141pf.bin
	cmp build/busicom/busicom-141pf.bin $(BUSICOM_ROM) && echo "identical to $(BUSICOM_ROM)"

.PHONY: busicom test-busicom busicom-rom

# Replay the vectors through an independent emulator (see tests/independent/RESULTS.md)
#   make test-independent I40XX=/path/to/i40xx-checkout
test-independent:
	bun tests/independent/check_i40xx.js $(I40XX) vectors/v1
