#!/usr/bin/env python3
"""Generate single-instruction test vectors for all 256 opcodes from the transistor-level
4004 (runs ./i4004-vectors once per opcode, in parallel).

    gen_vectors.py OUT_DIR [COUNT_PER_OPCODE]      -> OUT_DIR/00.json.gz ... FF.json.gz
"""
import gzip
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


def one(args):
    out_dir, opcode, count = args
    res = subprocess.run(["./i4004-vectors", "--opcode", f"{opcode:02X}", "--count", str(count), "--seed", str(opcode + 1)],
                         capture_output=True, text=True, check=True)
    tests = [json.loads(line) for line in res.stdout.splitlines()]
    with gzip.open(os.path.join(out_dir, f"{opcode:02x}.json.gz"), "wt", compresslevel=9) as f:
        f.write("[\n" + ",\n".join(json.dumps(t, separators=(",", ":")) for t in tests) + "\n]\n")
    return len(tests), res.stderr


if __name__ == "__main__":
    out_dir = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    os.makedirs(out_dir, exist_ok=True)
    with ThreadPoolExecutor(os.cpu_count()) as pool:
        results = list(pool.map(one, [(out_dir, op, count) for op in range(256)]))
    print(f"{sum(n for n, _ in results)} vectors in {out_dir}", file=sys.stderr)
    for _, err in results:
        if err:
            print(err, file=sys.stderr)
