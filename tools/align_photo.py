#!/usr/bin/env python3
"""Register the mask layout onto the real die photomicrograph.

Finds the orientation by brute force (8 candidates, FFT cross-correlation of the metal
mask against photo brightness), then refines an affine transform from ~100 local tile
matches. Writes the transform as JSON:  photo_xy = A @ (rotated_layout_x, y, 1).

    align_photo.py source/analyzer source/4004-composite-photo.jpg netlist/photo_align.json
"""
import json
import sys
import numpy as np
from PIL import Image
from layout import load_layers


def norm(a):
    a = a - a.mean()
    return a / (a.std() + 1e-9)


def correlate(a, b):
    h, w = max(a.shape[0], b.shape[0]) * 2, max(a.shape[1], b.shape[1]) * 2
    return np.fft.irfft2(np.fft.rfft2(a, (h, w)) * np.conj(np.fft.rfft2(b, (h, w))), (h, w))


def orient(img, rot, flip):
    img = img.rotate(rot, expand=True)
    return img.transpose(Image.FLIP_LEFT_RIGHT) if flip else img


def main(src, photo_path, out):
    metal = Image.fromarray((load_layers(src)["metal"] * 255).astype(np.uint8))
    photo = Image.open(photo_path).convert("RGB")
    lum = np.asarray(photo).astype(float).mean(2)

    # coarse: which way round is the photo, and roughly where?
    f = 4
    small = norm(np.asarray(photo.resize((photo.width // f, photo.height // f), Image.LANCZOS)).astype(float).mean(2))
    best = None
    for rot in (0, 90, 180, 270):
        for flip in (0, 1):
            t = orient(metal, rot, flip)
            t = norm(np.asarray(t.resize((t.width // f, t.height // f), Image.LANCZOS)).astype(float))
            c = correlate(small, t)
            iy, ix = np.unravel_index(c.argmax(), c.shape)
            dy = iy if iy < c.shape[0] // 2 else iy - c.shape[0]
            dx = ix if ix < c.shape[1] // 2 else ix - c.shape[1]
            score = c.max() / small.size
            if best is None or score > best[0]:
                best = (score, rot, flip, dx * f, dy * f)
    score, rot, flip, dx, dy = best
    print(f"orientation: rotate {rot}, flip {flip}, offset ({dx},{dy}), correlation {score:.2f}", file=sys.stderr)

    # fine: match tiles locally, fit an affine map
    t = np.asarray(orient(metal, rot, flip)).astype(float)
    size, reach, pts = 256, 40, []
    for ty in range(100, t.shape[0] - size - 100, 200):
        for tx in range(100, t.shape[1] - size - 100, 200):
            tile = t[ty:ty + size, tx:tx + size]
            y0, x0 = ty + dy - reach, tx + dx - reach
            if tile.std() < 60 or y0 < 0 or x0 < 0:
                continue
            win = lum[y0:y0 + size + 2 * reach, x0:x0 + size + 2 * reach]
            if win.shape != (size + 2 * reach, size + 2 * reach):
                continue
            c = correlate(norm(win), norm(tile))[:2 * reach + 1, :2 * reach + 1]
            iy, ix = np.unravel_index(c.argmax(), c.shape)
            if c.max() / tile.size > 0.25:
                pts.append((tx + size / 2, ty + size / 2, x0 + ix + size / 2, y0 + iy + size / 2))
    pts = np.array(pts)
    a = np.c_[pts[:, 0], pts[:, 1], np.ones(len(pts))]
    for _ in range(2):  # second pass drops the worst tenth
        cx = np.linalg.lstsq(a, pts[:, 2], rcond=None)[0]
        cy = np.linalg.lstsq(a, pts[:, 3], rcond=None)[0]
        res = np.hypot(a @ cx - pts[:, 2], a @ cy - pts[:, 3])
        keep = res <= np.percentile(res, 90)
        a, pts = a[keep], pts[keep]
    print(f"affine fit on {len(pts)} tiles: median error {np.median(res):.2f} px, worst {res.max():.2f} px", file=sys.stderr)
    json.dump({"rotate": rot, "flip": flip, "affine": [list(cx), list(cy)],
               "photo_size": list(photo.size), "median_error_px": float(np.median(res))},
              open(out, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
