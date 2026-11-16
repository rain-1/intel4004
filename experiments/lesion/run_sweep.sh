#!/bin/sh
# run_sweep.sh LISTFILE OUTFILE [K] : run the lesions in LISTFILE ("17o" / "17c" per line)
# on all cores; result lines (see lesion.c) collected in OUTFILE.
set -e
list=$1; out=$2; k=${3:-2}
here=$(dirname "$0"); root=$here/../..
tmp=$(mktemp -d)
split -n r/$(nproc) "$list" "$tmp/part."
ls "$tmp"/part.* | xargs -P "$(nproc)" -I{} sh -c "'$here/lesion' --net '$root/netlist/4004.net' --k $k --all-from {} > {}.out 2>/dev/null"
cat "$tmp"/part.*.out | sort -n -k1,1 -k2,2 > "$out"
rm -r "$tmp"
