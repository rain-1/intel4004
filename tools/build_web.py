#!/usr/bin/env python3
"""Build the single-file browser demo: web/template.html + assets -> web/4004-birthday.html

Embeds the die photo (half size), two node-id maps warped into photo space (which
electrical node owns each pixel: one map for metal, one for poly/diffusion), the netlist,
the simulator and the birthday ROM.
"""
import base64
import io
import json
import sys
import numpy as np
from PIL import Image
from diemap import photo_maps


def data_uri(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def id_image(ids):
    rgb = np.dstack([ids & 255, ids >> 8, np.zeros_like(ids)]).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def main(src, photo_path, align_path, rom_path, template, sim_js, out):
    photo, ids_metal, ids_lower, net = photo_maps(src, photo_path, align_path)
    web_net = {
        "nodes": net["nodes"],
        "area": net["area"],
        "pads": net["pads"],
        "transistors": [v for t in net["transistors"] for v in (t["gate"], t["a"], t["b"])],
    }
    parts = {
        "__SIM_JS__": open(sim_js).read(),
        "__NET__": json.dumps(web_net, separators=(",", ":")),
        "__ROM__": open(rom_path, "rb").read().hex(),
        "__PHOTO__": data_uri(photo, "JPEG", quality=80),
        "__IDS_METAL__": data_uri(id_image(ids_metal), "PNG", optimize=True),
        "__IDS_LOWER__": data_uri(id_image(ids_lower), "PNG", optimize=True),
        "__W__": str(photo.width),
        "__H__": str(photo.height),
        "__N_TRANSISTORS__": f"{len(net['transistors']):,}",
        "__N_CAPS__": str(len(net["capacitors"])),
        "__N_NODES__": f"{net['nodes']:,}",
        "__ALIGN_ERR__": f"{net['align']['median_error_px']:.1f}",
    }
    html = open(template).read()
    for key, value in parts.items():
        if key not in html:
            print(f"warning: {key} not used by template", file=sys.stderr)
        html = html.replace(key, value)
    open(out, "w").write(html)
    print(f"wrote {out}: {len(html) / 1e6:.2f} MB", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:8])
