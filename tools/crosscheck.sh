#!/bin/sh
# Assemble a program, run it on the reference emulator and on the transistor-level
# simulation, and compare their complete activity logs (every fetch, SRC and I/O).
#   tools/crosscheck.sh program.asm [extra i4004 options]
# Work files are left in build/crosscheck/ for inspection.
set -e
src=$1; shift
out=build/crosscheck
mkdir -p "$out"
name=$(basename "$src" .asm)
python3 tools/asm4004.py "$src" "$out/$name.bin" 2>/dev/null
./i4004 --ref --quiet --log "$out/$name.ref.log" "$@" "$out/$name.bin" || {
    echo "FAIL $src (reference did not halt)"; exit 1; }
./i4004 --quiet --log "$out/$name.sim.log" "$@" "$out/$name.bin" || {
    echo "FAIL $src (transistor-level run did not halt)"
    diff "$out/$name.ref.log" "$out/$name.sim.log" | head -12; exit 1; }
if cmp -s "$out/$name.ref.log" "$out/$name.sim.log"; then
    echo "ok   $src ($(wc -l < "$out/$name.sim.log") log lines identical)"
else
    echo "FAIL $src"; diff "$out/$name.ref.log" "$out/$name.sim.log" | head -12; exit 1
fi
