"""Offline photo preparation, never imported by the site or page generator.

Setup: py -m venv tools/.venv
       tools/.venv/Scripts/python -m pip install Pillow NumPy
Run:   tools/.venv/Scripts/python tools/make_halftone.py
Check: tools/.venv/Scripts/python tools/make_halftone.py --check

Originals stay in ignored tools/source/. Crop coordinates refer to those
originals, before resizing. The output has no alpha, profiles, or EXIF.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
COBALT = (47, 75, 203)
PAPER = (244, 242, 238)
WIDTH = 640
SCREEN_ANGLE = 45
DOT_PITCH = 10
LOGO_BOX = (.49, .72, .53, .76)
SIZES = {"computer": (640, 548), "coffee": (640, 640), "planet": (640, 480)}


def remove_logo(image):
    """Replace the lower-bezel mark with neighboring silver, row by row."""
    rgb = np.array(image.convert("RGB"))
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = [round(n * size) for n, size in zip(LOGO_BOX, (w, h, w, h))]
    strip = max(2, round(w * .004))
    left = np.median(rgb[y0:y1, x0 - strip:x0], axis=1)
    right = np.median(rgb[y0:y1, x1:x1 + strip], axis=1)
    t = np.linspace(0, 1, x1 - x0)[None, :, None]
    rgb[y0:y1, x0:x1] = np.rint(left[:, None] * (1 - t) + right[:, None] * t)
    return Image.fromarray(rgb)


def crop_box(name, size):
    w, h = size
    if name == "computer":
        return tuple(round(n * s) for n, s in zip((.245, .255, .77, .93), (w, h, w, h)))
    # Square mug, including its handle; ringed planet with a small side margin.
    unit = round(w * (.60 if name == "coffee" else .85) / (1 if name == "coffee" else 4))
    cw, ch = (unit, unit) if name == "coffee" else (unit * 4, unit * 3)
    x, y = round((w - cw) / 2), round((h - ch) / 2)
    return x, y, x + cw, y + ch


def point_percent(point, box, size):
    x0, y0, x1, y1 = box
    return [round((point[0] * size[0] - x0) / (x1 - x0) * 100, 4),
            round((point[1] * size[1] - y0) / (y1 - y0) * 100, 4)]


def halftone(gray):
    """A 45-degree clustered-dot screen; dots join into solid ink in shadows."""
    values = np.asarray(gray, dtype=np.float64)
    y, x = np.indices(values.shape, dtype=np.float64)
    angle = np.deg2rad(SCREEN_ANGLE)
    u = (x * np.cos(angle) + y * np.sin(angle)) / DOT_PITCH
    v = (-x * np.sin(angle) + y * np.cos(angle)) / DOT_PITCH
    dx, dy = (u + .5) % 1 - .5, (v + .5) % 1 - .5
    radius2 = dx * dx + dy * dy
    # Exact area of a circle clipped by its square cell (0 through 100% ink).
    radius = np.sqrt(np.maximum(radius2, .25))
    segments = radius2 * np.arccos(.5 / radius) - .5 * np.sqrt(np.maximum(radius2 - .25, 0))
    threshold = np.pi * radius2 - np.where(radius2 > .25, 4 * segments, 0)
    ink = (1 - values / 255) > threshold
    ink[values == 0] = True
    ink[values == 255] = False
    rgb = np.empty((*values.shape, 3), dtype=np.uint8)
    rgb[:] = PAPER
    rgb[ink] = COBALT
    return Image.fromarray(rgb)


def check_outputs():
    for name, size in SIZES.items():
        path = ROOT / f"assets/images/hero-{name}.webp"
        with Image.open(path) as image:
            assert image.format == "WEBP" and image.mode == "RGB", path
            assert image.size == size, (path, image.size)
            colors = image.getcolors(image.width * image.height)
            assert colors is not None and {c for _, c in colors} == {COBALT, PAPER}, path
            assert not any(key in image.info for key in ("exif", "icc_profile", "xmp")), path
            if name == "planet":
                for x, y in ((0, 0), (630, 0), (0, 470), (630, 470)):
                    assert np.all(np.asarray(image.crop((x, y, x + 10, y + 10))) == COBALT)
        print(f"{path.relative_to(ROOT)}: {size[0]}x{size[1]}, two opaque colors, {path.stat().st_size:,} bytes")
    # Extremes and tone progression must work independently of these three photos.
    coverage = []
    for value in (0, 64, 128, 192, 255):
        pixels = np.asarray(halftone(Image.new("L", (160, 160), value)))
        coverage.append(np.mean(np.all(pixels == COBALT, axis=2)))
    assert coverage[0] == 1 and coverage[-1] == 0
    assert all(a > b for a, b in zip(coverage, coverage[1:])), coverage
    assert max(abs(actual - (1 - value / 255)) for actual, value in zip(coverage, (0, 64, 128, 192, 255))) < .015


def generate():
    geometry = {}
    for name in SIZES:
        source = ROOT / f"tools/source/{name}.jpg"
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
        size = image.size
        box = crop_box(name, size)
        if name == "computer":
            patched = remove_logo(image)
            # Check both the actual repair and that no pixels outside it changed.
            before, after = np.array(image), np.array(patched)
            x0, y0, x1, y1 = [round(n * s) for n, s in zip(LOGO_BOX, (*size, *size))]
            assert after[y0:y1, x0:x1].min() > 190, "Bezel repair must contain no dark mark"
            before[y0:y1, x0:x1] = after[y0:y1, x0:x1]
            assert np.array_equal(before, after), "Repair modified pixels outside the mark"
            image = patched
        gray = ImageOps.grayscale(image.crop(box).resize(SIZES[name], Image.Resampling.LANCZOS))
        gray = ImageOps.autocontrast(gray)
        # A fixed midpoint avoids bleaching the planet against its dark sky.
        contrast = 1.10 if name == "computer" else 1.18
        gray = gray.point(lambda v: round(max(0, min(255, (v - 127.5) * contrast + 127.5))))
        if name == "computer":
            gray = gray.point(lambda v: round(255 * (v / 255) ** 1.35))
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1.5, percent=180, threshold=2))
        gray = gray.point(lambda v: 0 if v <= 12 else 255 if v >= 251 else v)
        output = ROOT / f"assets/images/hero-{name}.webp"
        halftone(gray).save(output, "WEBP", lossless=True, quality=100, method=6)
        item = {"source_size": size, "crop_px": box, "output_size": SIZES[name]}
        if name == "computer":
            item["screen_percent"] = [point_percent(p, box, size) for p in ((.28, .30), (.73, .68))]
        elif name == "coffee":
            item["center_percent"] = point_percent((.5, .48), box, size)
            item["radius_percent_width"] = round(.18 * size[0] / (box[2] - box[0]) * 100, 4)
        else:
            item["center_percent"] = point_percent((.5, .51), box, size)
        geometry[name] = item
    (ROOT / "tools/hero-prints.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(geometry, indent=2))
    check_outputs()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Decode and check existing prints without reading originals")
    args = parser.parse_args()
    check_outputs() if args.check else generate()
