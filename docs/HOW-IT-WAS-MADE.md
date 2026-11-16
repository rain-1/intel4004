# How this was made, and what "from die shots" really means

This is an account of the process by the AI model that did the work (Claude,
running in Claude Code), written on 2026-11-16 from the session log. It
answers the fair questions people asked when the video was shared: did it
really work from the image, did it just recognise the 4004 and reproduce a
known emulator, and how would anyone check.

## Short answers

1. **The netlist was not extracted from a photograph.** It was extracted by my
   code from five hand-made tracings of the chip's mask layers, published by the
   Intel 4004 35th Anniversary Project (4004.com). Those tracings are the result
   of years of work by that project's volunteers. Turning a photo into those
   layers is the hard part of chip reverse engineering, and I did not do it.
2. **I knew it was a 4004.** The request said so. I used public knowledge of the
   4004 freely: the pinout, the bus timing and the instruction set.
3. **The part that runs the chip contains no knowledge of the 4004.** The
   simulator (`sim/switchsim.c`, about 170 lines) only knows "a transistor is a
   switch". It has no opcodes, no registers and no instruction names. The
   4004's behaviour comes out of the 2,242 transistors in the netlist.
4. **I did not copy an existing emulator or netlist.** The 4004.com download
   contains a Windows analyzer program; I deleted the executables without
   running them, and the package has no source code or netlist file. The
   instruction-level emulator in this tree (`sim/ref4004.c`) is mine, written
   from what I know of the manual, and is used only as a checker.
5. **When I later tried the hard part on a different chip, it failed.** See
   "What I could not do" below.

A fair one-line description: *an AI extracted a transistor netlist from
published mask-layer tracings of the 4004, wrote a switch-level simulator for
it, and proved it against an independent instruction-level model.* "Reverse
engineered the 4004 from a photo" overstates it.

## What I was asked

> Would you be able to take intel 4004 die shots and produce a working emulator
> from them? maybe a little demo cute program celebrating the chip today

Using information from the internet was allowed.

## The stages, in order

Times are minutes after the request. The first working demo took about 27
minutes, which is itself a sign of how much the published tracings did.

### 1. Finding material (0 to 2 minutes)

I went straight to 4004.com and Wikimedia Commons and downloaded:

| File | What it is | How it was used |
|---|---|---|
| `source/4004-composite-photo.jpg` | Die photomicrograph, 2760 x 2034 | Looked at; alignment and backdrop only |
| `source/4004-masks-composite.jpg` | Coloured composite of the masks | Looked at once |
| `source/analyzer/i4004-{diffusion,poly,metal,vias,contacts}.bmp` | Five 1-bit tracings of the mask layers, 1968 x 2706, from Lajos Kintli's analyzer package | **The input to netlist extraction** |
| `source/analyzer/readme.txt` | Analyzer documentation | Read for what each layer file means and for notes on layout quirks |
| `source/analyzer/i4004-signals.txt` | Signal names with schematic coordinates | Printed once while inspecting the package; not read by any code |
| `source/i4004-schematic.gif`, `analyzer/i4004-schematic.bmp` | The 4004 schematic | Downloaded, never opened or used |
| `source/4004-50th-1st-cut-svg.html` | Vector drawing of the layout | Downloaded, not used |
| Analyzer `.exe` and `.bat` files | Windows analyzer and simulator | Deleted unrun |

### 2. Deciding not to use the photo (2 minutes)

I viewed crops of the photograph next to the mask composite. Wires in the photo
are roughly 4 to 5 pixels wide and the layers overlap in colour. I judged that
too coarse to segment automatically and **did not attempt it**. That judgement
was made by eye in under a minute; I did not test it. I switched to the layer
tracings and said so in my first report to the user:

> The netlist does not come from automatic segmentation of the photograph. [...]
> I started instead from the 4004.com project's hand tracings of the five die
> layers.

### 3. Netlist extraction (2 to 9 minutes)

`tools/extract_netlist.py` and `tools/layout.py`. The rules are those of
silicon-gate pMOS, which I knew:

- Label connected regions in each layer.
- Where polysilicon crosses diffusion there is a transistor, unless a buried
  contact joins the two there.
- "Vias" join metal to whatever is underneath.
- Regions joined through contacts are one electrical node.

Result: 2,242 transistors, 66 capacitors, 1,100 nodes, no unexplained shapes.
The analyzer's readme gives the project's own counts from the layout: 1,807
transistors, 427 load devices, 8 input protectors and 66 capacitors. Mine are
2,242 transistors (1,807 + 427 + 8) and 66 capacitors, so they agree. That
count match is the only comparison I made with their netlist.

The 16 bond pads were located by me on the metal layer and named from the
published 4004 pinout.

One real problem appeared here. The first netlist had the CM-ROM output driver
shorted to its own inverter. I rendered that area, found a buried contact that
grazes a neighbouring polysilicon line by a few pixels, and added a rule: a
contact touching a second shape of the same layer counts only if at least 20%
of it lies on that shape. Exactly one contact on the chip is affected. This is
a judgement call about a tracing artefact, and it is flagged in the code.
While chasing it I read the analyzer readme's notes on layout quirks, which
say that pixel errors had wrongly connected layers in places. That told me
such errors exist; it does not say where this one is.

### 4. Switch-level simulator (9 to 13 minutes)

`sim/switchsim.c`. Every transistor is a switch that is on when its gate is
low. After each clock edge, groups of nodes connected through on-switches are
resolved: a path to VSS wins, otherwise VDD, otherwise the group keeps its
charge, with the larger node winning when charge is shared. This is the same
idea as the well-known Visual 6502 simulator, which I knew of and did not
copy code from.

### 5. The board around the chip (13 to 15 minutes)

`sim/board.c`, `sim/mcs4.c`. These drive the two clock phases and behave like
the 4001 ROM and 4002 RAM chips on the pins. Here I used knowledge of the
MCS-4 bus cycle (eight clock periods, address then data, SYNC, the CM lines).

### 6. Proving it (13 to 21 minutes)

`sim/ref4004.c` is an ordinary instruction-level emulator I wrote from the
manual. `make test` runs the same programs on both and compares complete logs
of bus activity: exhaustive ADD and SUB, every accumulator instruction on every
value, RAM and ports across banks, control flow including page-boundary and
stack-wrap cases, and 25 randomly generated programs. All identical.

It did not pass first time. The first run disagreed with the reference: an
index register pair held the wrong value. The cause was reset timing. If RESET
was released while a two-byte instruction was on the bus, the simulated chip
mis-executed its first instruction. I found that by trying every release point,
and changed the board (feed NOPs during reset), not the chip. One of my own
control-flow tests also had a bug and had to be fixed.

### 7. Demo, web page, video (17 to 55 minutes)

- `demo/birthday.asm`: a 4004 program I wrote, assembled with my own assembler
  (`tools/asm4004.py`).
- `tools/align_photo.py`: registers the layout onto the die photo by image
  correlation. **This is the only place the photograph is used.**
- `web/sim4004.js`: a JavaScript port of the simulator, checked against the C
  simulator's logs.
- `tools/make_video.py`: renders the video from a recorded run. Every lit wire
  comes from recorded node states. One thing on screen does not come from the
  chip: the worked subtraction digits are computed by the renderer and revealed
  when the chip finishes each digit.

### 8. Later work on the same netlist

- `vectors/`: 102,400 single-instruction test vectors, with state set and read
  only through the pins. They show bus contents during cycles the manual does
  not document.
- `busicom/`: the original Busicom 141-PF calculator firmware runs on the
  netlist; 49 calculations match the reference and the expected arithmetic.
  This is the strongest check, because the program is someone else's.
- `experiments/lesion/`: every transistor forced open and forced closed, one at
  a time. 468 of these faults break exactly one instruction. An emulator
  written from the manual has no transistors to break.

## How to check this yourself

    python3 tools/extract_netlist.py source/analyzer /tmp/4004.json
    cmp /tmp/4004.net netlist/4004.net     # same netlist from the bitmaps
    make && make test                      # 32 comparisons, all identical
    grep -n -i "opcode\|accumulator" sim/switchsim.c   # nothing

I re-ran the first three on 2026-11-16 before writing this: the netlist
reproduced byte for byte and all 32 comparisons passed.

To see that the netlist matters, delete or change one transistor line in
`netlist/4004.net` and run `make test`.

## What is weak or unverified

- **The first checker is also mine.** The reference emulator and the tests were
  written by the same model that wrote the simulator. To address that, the
  netlist-derived vectors were later replayed through an emulator written by
  someone else (`tests/independent/RESULTS.md`): 92,000 vectors covering every
  documented instruction except RDR and the TEST term of JCN are identical.
  Those two are not modelled by that emulator and remain checked only against
  my own reference, the manual and the Busicom firmware.
- **Nothing was compared with a real 4004**, or with the 4004.com project's
  own simulator.
- **Switch-level only.** No voltages, no timing within a clock phase.
- **One tracing artefact was corrected by rule**, as described above.
- **The session log is the only record of the first day.** There was no version
  control until this repository was created, so the commit history does not
  show the order of work.

## What I could not do

After this, we tried the genuinely hard version on other chips, working from
real die photographs with no tracings.

- **Random logic from photos: failed.** On a National MM5777 calculator chip,
  extraction from delayered photographs produced about one wrong connection per
  transistor. That is useless for simulation. A single photograph also cannot
  show everything; that chip needed separate photos with the metal on and off.
- **Regular arrays from photos: worked.** Mask ROMs and PLAs are grids, and
  reading them is a much easier problem. That gave an unsolved ROM layout for
  the ISKRA EMZ1001, a ROM read for the MOS MPS-7600, and a character ROM for
  the Unisonic Champion. That work is not in this repository yet.

So the honest capability claim is: given clean layer tracings, netlist
extraction and simulation take minutes; given only photographs, ROM-like
structures are readable and general logic is not, at least not by the methods
tried here.

## Credit

The mask-layer tracings, photomicrograph and Busicom firmware recovery are the
work of the Intel 4004 35th Anniversary Project: Tim McNerney, Lajos Kintli,
Fred Huettig, Barry Silverman, Brian Silverman and Christopher Tarnovsky, with
the Computer History Museum and Intel. Their material is CC BY-NC-SA 3.0. See
`NOTICE.md`.
