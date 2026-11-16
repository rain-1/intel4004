#!/bin/sh
# Build the lesion harnesses. Run from the repository root:
#   sh experiments/lesion/build.sh
# Pilot (random tests, as in experiments/FEASIBILITY-4004.txt):
#   experiments/lesion/lesion --k 2 --golden > g.jsonl && python3 experiments/lesion/check_golden.py g.jsonl vectors/v1
#   experiments/lesion/run_sweep.sh experiments/lesion/pilot_list.txt out.txt 2
#   python3 experiments/lesion/analyze.py out.txt netlist/4004.json out.tsv
# Full study (structured tests): see experiments/lesion/RESULTS.txt, section "Reproducing".
set -e
cc -O2 -march=native -Wall -Wextra -o experiments/lesion/lesion experiments/lesion/lesion.c experiments/lesion/lesionsim.c
cc -O2 -march=native -Wall -Wextra -o experiments/lesion/study experiments/lesion/study.c experiments/lesion/lesionsim.c sim/ref4004.c sim/mcs4.c
