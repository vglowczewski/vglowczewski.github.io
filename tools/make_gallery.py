"""Offline gallery derivatives. Use tools/.venv/Scripts/python tools/make_gallery.py.

Sources are private and ignored. Edited JSON entries are retained verbatim.
Only new sources are added; missing sources are reported, never deleted.
gallery-exclusions.json prevents deliberately removed photos from being readded.
The site and standard-library generator never import Pillow.
"""
import argparse
import io
import json
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageCms, ImageOps

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".avif", ".bmp"}


def stem_slug(stem):
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode().lower()).strip("-")
    if not slug:
        raise ValueError("Photo filenames must contain a letter or number.")
    return slug


def build(root=ROOT, source=None):
    source = source or root / "tools/source/gallery"
    target = root / "assets/images/gallery"
    data_path = root / "data/gallery.json"
    exclusions_path = root / "tools/gallery-exclusions.json"
    excluded = json.loads(exclusions_path.read_text(encoding="utf-8")) if exclusions_path.exists() else []
    if not isinstance(excluded, list) or any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.webp", name)
        for name in excluded
    ):
        raise ValueError("gallery-exclusions.json must contain an array of gallery filenames.")
    excluded = set(excluded)
    entries = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else []
    if not isinstance(entries, list):
        raise ValueError("gallery.json must contain an array.")
    existing = {entry["file"]: entry for entry in entries}
    if len(existing) != len(entries):
        raise ValueError("gallery.json contains duplicate file values.")
    target.mkdir(parents=True, exist_ok=True)
    seen = set()
    for photo in sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS):
        relative = photo.relative_to(source)
        category = relative.parts[0].lower() if len(relative.parts) > 1 else "travel"
        # Category prefix prevents root/travel and food filename collisions.
        nested = relative.with_suffix("").parts
        identity = "-".join(stem_slug(part) for part in nested)
        if len(nested) == 1:
            identity = "travel-" + identity
        file = identity + ".webp"
        if file in excluded:
            print(f"Skipped excluded source: {file}")
            continue
        if file in seen:
            raise ValueError(f"Two sources produce {file}; rename one source.")
        seen.add(file)
        with Image.open(photo) as original:
            oriented = ImageOps.exif_transpose(original).convert("RGB")
            if original.info.get("icc_profile"):
                oriented = ImageCms.profileToProfile(
                    oriented, ImageCms.ImageCmsProfile(io.BytesIO(original.info["icc_profile"])),
                    ImageCms.createProfile("sRGB"), outputMode="RGB")
            # Force a fresh pixel-only image; no info/exif/icc/xmp survives.
            clean = Image.frombytes("RGB", oriented.size, oriented.tobytes())
        sizes = {}
        for suffix, width in (("", 800), ("-full", 1800)):
            height = max(1, round(clean.height * width / clean.width))
            image = clean.resize((width, height), Image.Resampling.LANCZOS)
            output = target / f"{Path(file).stem}{suffix}.webp"
            image.save(output, "WEBP", quality=88, method=6)
            with Image.open(output) as result:
                if any(k in result.info for k in ("exif", "icc_profile", "xmp")):
                    raise ValueError(f"Unexpected metadata in {output.name}")
            sizes["thumbnail" if not suffix else "full"] = {"width": width, "height": height}
        if file not in existing:
            caption = re.sub(r"[-_]+", " ", photo.stem).strip()
            caption = caption[:1].upper() + caption[1:]
            entry = {"file": file, "category": category, "caption": caption, "alt": caption, "focus": "center",
                     "width": sizes["thumbnail"]["width"], "height": sizes["thumbnail"]["height"],
                     "full_width": sizes["full"]["width"], "full_height": sizes["full"]["height"]}
            entries.append(entry)
            existing[file] = entry
            print(f"Added {file}")
    removed = [entry["file"] for entry in entries if entry["file"] not in seen]
    for name in removed:
        print(f"Source removed, entry retained: {name}")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the file byte-for-byte on a no-op run as well as edited values.
    if not data_path.exists() or entries != json.loads(data_path.read_text(encoding="utf-8")):
        data_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Gallery: {len(entries)} entries; {len(removed)} removed sources reported.")
    return entries, removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    build()
