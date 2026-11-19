"""Offline grayscale cutouts. Run with tools/.venv/Scripts/python.

Install Pillow and NumPy only into the ignored tools/.venv environment.
Find named sources under tools/source/objects/, falling back to tools/source/.
No originals are modified; every output is grayscale RGBA without metadata.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("laptop", "coffee", "camera", "stamp", "saturn", "moon")
FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".avif", ".bmp"}


def find_source(name):
    for folder in (ROOT / "tools/source/objects", ROOT / "tools/source"):
        matches = sorted(p for p in folder.glob("*") if p.is_file()
                         and p.stem.casefold() == name and p.suffix.lower() in FORMATS)
        if len(matches) > 1:
            raise ValueError(f"More than one {name} source; keep one named file.")
        if matches:
            return matches[0]
    return None


def remove_background(gray, alpha):
    """Threshold only border-connected background, preserving internal whites."""
    pixels = np.asarray(gray)
    edge = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
    corners = np.concatenate([a.ravel() for a in (pixels[:4, :4], pixels[:4, -4:], pixels[-4:, :4], pixels[-4:, -4:])])
    white = np.mean(edge >= 245) >= .80 or np.mean(corners >= 245) >= .95
    black = np.mean(edge <= 15) >= .80 or np.mean(corners <= 15) >= .95
    if not white and not black:
        return alpha, None
    candidates = pixels >= 245 if white else pixels <= 15
    # fromarray can expose a read-only buffer; floodfill needs owned pixels.
    mask = Image.fromarray((candidates * 255).astype(np.uint8)).copy()
    w, h = gray.size
    for x, y in [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]:
        if mask.getpixel((x, y)) == 255:
            ImageDraw.floodfill(mask, (x, y), 128)
    outside = np.asarray(mask) == 128
    if not outside.any():
        raise ValueError("Background flood fill did not modify the mask.")
    rim = np.asarray(Image.fromarray((outside * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
    coverage = np.ones(pixels.shape, dtype=np.float64)
    coverage[outside] = 0
    soft = rim & ~outside
    coverage[soft] = np.clip((255 - pixels[soft].astype(float)) / 24 if white else pixels[soft] / 24, 0, 1)
    return Image.fromarray(np.rint(np.asarray(alpha) * coverage).astype(np.uint8)), "white" if white else "black"


def process(name, path):
    with Image.open(path) as original:
        source = ImageOps.exif_transpose(original).convert("RGBA")
    source.thumbnail((884, 884), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(source)
    alpha = source.getchannel("A")
    removed = None
    if name in {"saturn", "moon"}:
        # Suppress the faint photographic frame without clipping dim ring lines.
        values = np.asarray(gray, dtype=np.float64)
        threshold = 18 if name == "saturn" else 10
        coverage = np.clip((values - threshold) / (255 - threshold), 0, 1)
        soft = np.clip((values - threshold) / 12, 0, 1)
        soft = soft * soft * (3 - 2 * soft)
        alpha = Image.fromarray(np.rint(255 * coverage * soft).astype(np.uint8))
        gray = Image.new("L", source.size, 255)
    else:
        if alpha.getextrema() == (255, 255):
            alpha, removed = remove_background(gray, alpha)
        gray = ImageEnhance.Contrast(gray).enhance(1.06)
        rng = np.random.default_rng(NAMES.index(name))
        values = np.asarray(gray).astype(float) + rng.normal(0, .7, (gray.height, gray.width))
        gray = Image.fromarray(np.rint(np.clip(values, 0, 255)).astype(np.uint8))
    rgba = Image.merge("RGBA", (gray, gray, gray, alpha))
    box = alpha.point(lambda v: 255 if v > 2 else 0).getbbox()
    if not box:
        raise ValueError(f"{name}: no foreground found.")
    rgba = ImageOps.expand(rgba.crop(box), border=8, fill=(0, 0, 0, 0))
    # Copying pixels into a fresh image prevents inherited EXIF/profile fields.
    clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
    target = ROOT / f"assets/images/objects/{name}.webp"
    target.parent.mkdir(parents=True, exist_ok=True)
    clean.save(target, "WEBP", lossless=True, method=6, exact=True)
    with Image.open(target) as result:
        assert result.size[0] <= 900 and result.size[1] <= 900 and result.mode == "RGBA"
        channels = np.asarray(result)
        assert np.array_equal(channels[:, :, 0], channels[:, :, 1])
        assert np.array_equal(channels[:, :, 1], channels[:, :, 2])
        assert channels[:, :, 3].min() == 0 and channels[:, :, 3].max() > 0
        assert not any(k in result.info for k in ("exif", "icc_profile", "xmp"))
    center = [round(((source.size[i] / 2 - box[i] + 8) / clean.size[i]) * 100, 4) for i in (0, 1)]
    print(f"{name}: {clean.width}x{clean.height}; " + (f"removed solid {removed} background by thresholding" if removed else "preserved/derived alpha"))
    return {"width": clean.width, "height": clean.height, "center_percent": center,
            "background_removed": removed}


def main():
    results = {}
    for name in NAMES:
        path = find_source(name)
        if path is None:
            print(f"Missing {name}: no image invented.")
            continue
        results[name] = process(name, path)
    (ROOT / "tools/object-geometry.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
