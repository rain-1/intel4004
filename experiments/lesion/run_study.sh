#!/bin/sh
# run_study.sh LISTFILE OUTDIR [JOBS] : run the lesions in LISTFILE ("17o" / "17c" per line)
# with the structured test set on JOBS workers (default 8), niced. Each worker appends result
# lines (format: study.c header) to OUTDIR/part.N.out; lesions already present there are
# skipped, so an interrupted sweep can be resumed by running the same command again.
set -e
list=$1; out=$2; jobs=${3:-8}
here=$(cd "$(dirname "$0")" && pwd); root=$here/../..
mkdir -p "$out"
cat "$out"/part.*.out 2>/dev/null | awk '{print $1 $2}' | sort > "$out/done.txt" || true
grep -vxF -f "$out/done.txt" "$list" > "$out/todo.txt" || true
echo "$(wc -l < "$out/todo.txt") lesions to run on $jobs workers"
rm -f "$out"/todo.part.*
split -n r/"$jobs" -d "$out/todo.txt" "$out/todo.part."
for p in "$out"/todo.part.*; do
  n=${p##*.}
  nice -n 10 "$here/study" --net "$root/netlist/4004.net" --all-from "$p" >> "$out/part.$n.out" 2>> "$out/stderr.txt" &
done
wait
echo done
