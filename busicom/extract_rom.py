#!/usr/bin/env python3
"""Rebuild the 141-PF ROM image from the address/byte columns of the annotated listing.
Only parses text; nothing in the listing is executed.

    python3 -I busicom/extract_rom.py Busicom-141PF-Calculator_asm_rel-1-0-1.txt busicom-141pf.bin

The listing is not kept in this tree: see source/busicom/NOTICE.txt.
"""
import re, sys
rom = {}
# "addr bytes [label:] mnemonic" (native code) or "addr [label:] bytes ;comment" (pseudo code)
pat = re.compile(r'^([0-9a-f]{3})[ \t]+(?:[A-Za-z_][A-Za-z0-9_]*:[ \t]+)?((?:[0-9a-f]{2}(?=[ \t;]|$)[ \t]*)+)')
for line in open(sys.argv[1], encoding="latin-1"):
    m = pat.match(line)
    if not m:
        continue
    a = int(m.group(1), 16)
    for i, b in enumerate(m.group(2).split()):
        if a + i in rom and rom[a + i] != int(b, 16):
            sys.exit(f"conflict at {a+i:03x}")
        rom[a + i] = int(b, 16)
top = max(rom) + 1
missing = [a for a in range(top) if a not in rom]
img = bytes(rom.get(a, 0) for a in range(top))
open(sys.argv[2], "wb").write(img)
print(f"{len(rom)} bytes defined, image {top} bytes (0x000-0x{top-1:03x}); "
      f"{len(missing)} undefined addresses: {' '.join(f'{a:03x}' for a in missing[:40])}")
