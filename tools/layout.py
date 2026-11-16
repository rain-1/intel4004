"""Shared helpers: load the 4004 mask-layer bitmaps and label connected regions."""
import numpy as np
from PIL import Image

LAYERS = ("diffusion", "poly", "metal", "vias", "contacts")


def load_layers(src_dir):
    """Return {layer: bool array}, True where the mask has material."""
    out = {}
    for name in LAYERS:
        im = Image.open(f"{src_dir}/i4004-{name}.bmp").convert("L")
        out[name] = np.array(im) < 128
    return out


def label(mask):
    """4-connected component labelling. Returns (labels int32, count); 0 = background."""
    h, w = mask.shape
    left = np.zeros_like(mask)
    left[:, 1:] = mask[:, :-1]
    starts = mask & ~left
    run = np.cumsum(starts.ravel()).reshape(h, w)  # 1-based run id on mask pixels
    run = np.where(mask, run, 0)
    nruns = int(run.max())
    both = mask[:-1] & mask[1:]
    pairs = np.unique(np.stack([run[:-1][both], run[1:][both]], axis=1), axis=0)
    parent = list(range(nruns + 1))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(nruns + 1)])
    uniq, compact = np.unique(roots[1:], return_inverse=True)
    lut = np.zeros(nruns + 1, np.int32)
    lut[1:] = compact + 1
    return lut[run], len(uniq)


def dilate(mask, n=1):
    """4-neighbour binary dilation, n iterations."""
    m = mask.copy()
    for _ in range(n):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m
