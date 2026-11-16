"""Which electrical node owns each pixel of the die photograph.

Warps the extracted layout regions into photo space using the alignment found by
align_photo.py. Shared by the web demo and the video renderer.
"""
import json
import numpy as np
from PIL import Image
from extract_netlist import extract

NONE = 0xFFFF


def photo_maps(src, photo_path, align_path, scale=2):
    """Return (photo, ids_metal, ids_lower, net).

    photo is shrunk by `scale`; the id maps are uint16 arrays of the same size holding a
    node number per pixel (NONE where the layer is absent). ids_lower is poly, else diffusion.
    """
    net, regions = extract(src, verbose=False)
    align = json.load(open(align_path))
    photo = Image.open(photo_path).convert("RGB")
    w, h = photo.width // scale, photo.height // scale

    # output pixel (u,v) -> photo (scale*u, scale*v) -> rotated-layout coords via inverse affine
    m = np.array(align["affine"] + [[0, 0, 1]])
    inv = np.linalg.inv(m) @ np.diag([scale, scale, 1]) @ np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]])
    coeffs = tuple(inv[:2].ravel())

    def warp(node_map):
        img = Image.fromarray(node_map.astype(np.int32), mode="I")
        img = img.rotate(align["rotate"], expand=True, fillcolor=-1)
        if align["flip"]:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        return np.asarray(img.transform((w, h), Image.AFFINE, coeffs, Image.NEAREST, fillcolor=-1))

    def ids_for(names):
        ids = np.full((h, w), -1, np.int32)
        for name in names:  # later names only fill pixels still empty
            lab, node_of = regions[name]
            ids = np.where(ids < 0, warp(node_of[lab]), ids)
        return np.where(ids < 0, NONE, ids).astype(np.uint16)

    net["align"] = align
    return photo.resize((w, h), Image.LANCZOS), ids_for(["metal"]), ids_for(["poly", "diffusion"]), net
