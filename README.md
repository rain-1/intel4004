# Intel 4004, from the die up

A transistor-level emulator of the Intel 4004, built from tracings of the chip's mask
layers, plus a birthday program for the chip's 55th anniversary (15 November 2026).

    make            # build ./i4004
    make demo       # run the birthday card on the transistor-level chip
    make test       # cross-check against the reference emulator
    make web        # rebuild web/4004-birthday.html (open it in a browser)

**What this is and is not.** The netlist is extracted from the 4004.com
project's published tracings of the mask layers, not from a photograph. The
photograph is used only for alignment and display. For the full account of the
process, what public information was used and how to check it, see
`docs/HOW-IT-WAS-MADE.md`.

## How it works

1. **Layers** (`source/analyzer/i4004-*.bmp`): five 1-bit tracings of the die
   (diffusion, polysilicon, metal, metal contacts, buried contacts) from the 4004.com
   35th Anniversary Project.
2. **Netlist** (`tools/extract_netlist.py` -> `netlist/4004.json`, `.net`): poly over
   diffusion is a transistor unless a buried contact joins them; connected regions
   joined through contacts become electrical nodes. Result: 2,242 transistors
   (427 of them loads, 8 input-protection devices), 66 capacitors, 1,100 nodes. These
   counts match the ones published by the 4004.com project.
3. **Simulator** (`sim/switchsim.c`): every transistor is a switch. After each clock
   edge, groups of connected nodes are resolved: a path to VSS wins, else VDD, else the
   group keeps its charge. No knowledge of the instruction set is built in.
4. **Board** (`sim/board.c`, `sim/mcs4.c`): drives the two clock phases and behaves
   like the 4001 ROM / 4002 RAM chips on the pins.
5. **Reference** (`sim/ref4004.c`): an ordinary instruction-level emulator written
   from the manual, used only to check the above.

`make test` compares complete bus-activity logs (every fetch, SRC and I/O transfer)
between the two: exhaustive ADD/SUB, every accumulator instruction on every value, RAM
and ports across all DCL banks, control flow including page-boundary and stack-wrap
cases, and randomly generated programs. All identical.

`tools/align_photo.py` registers the layout onto the real die photomicrograph
(`source/4004-composite-photo.jpg`) by image correlation, to about half a pixel, so the
web demo can paint live node states onto the photo. `web/sim4004.js` is a port of the C
simulator; `bun web/check.js ...` checks it against the C logs.

## The Busicom calculator

The 4004 was designed for the Busicom 141-PF printing calculator. Its original
firmware runs unmodified on the transistor-level chip here, with behavioural
models of the shift registers, keyboard and drum printer:

    make busicom                       # 2 SQRT on the transistor-level chip
    ./i4004-busicom 18 + 42 + =        # prints a paper tape: 18, 42, 60
    make test-busicom                  # 49 calculations, about 5 minutes

All 49 regression cases produce bus logs identical to the instruction-level
reference and the arithmetically expected tape. Only the 4004 itself is
simulated at transistor level, and the printer timing is inferred, not measured.
See `docs/BUSICOM.txt`.

## Related work in this tree

- `vectors/`: single-instruction test vectors from the netlist, and what they
  say about questions left open in MAME's 4004 core.
- `experiments/lesion/`: single-transistor lesion study of the 4004.
- `chips/` (not in this repository yet): other chips (EMZ1001 ROM decoding,
  MOS MPS-7600, Motorola 6800 undocumented opcodes, the Unisonic Champion font,
  and several surveys).

## Limits

- The netlist comes from the layer tracings, not from automatic segmentation of the
  photograph; the photo is too low-resolution for that. It is used for alignment only.
- One tracing artefact is corrected by rule (see `MIN_SECOND_SHAPE_FRACTION` in the
  extractor): a buried contact that grazes a neighbouring poly line at the CM-ROM driver.
- Switch-level only: no voltages, no real timing. Bootstrap capacitors are ignored.
- The ROM, RAM and teletype are behavioural models. During reset the board feeds NOPs;
  if it instead fed a two-byte instruction from ROM address 0 and released RESET in
  X3..A2, the simulated chip mis-executed its first instruction. Unverified on hardware.
- Speed: about 11,000 instruction cycles/s in C; the real chip did 92,500.

## Credits and licence of the inputs

Die photomicrograph, mask-layer tracings and readme in `source/` are from the Intel 4004
35th Anniversary Project, https://www.4004.com/ (Tim McNerney, Lajos Kintli, Fred
Huettig, Barry and Brian Silverman, Christopher Tarnovsky), CC BY-NC-SA 3.0. Anything
derived from them here (netlist, web demo) carries the same non-commercial terms.
