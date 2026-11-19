# vglowczewski.github.io

Personal website and portfolio. Live at https://vglowczewski.github.io

Plain HTML, CSS, and vanilla JS. No frameworks, no build step beyond a small Python script that generates the project pages.

## Layout

```
index.html, experience.html,
projects.html, gallery.html,
contact.html          Pages
data/projects.json    Project content
data/gallery.json     Gallery photos, captions, focal points
css/, js/             Styles and scripts
assets/               Images and textures
tools/                Generators, checks, image scripts
```

## Running locally

```bash
python -m http.server 8000 --bind 127.0.0.1
```

Then open http://127.0.0.1:8000. (On Windows, use `py` instead of `python`.)

## Editing content

Project pages are generated from `data/projects.json`. After changing that file or the case-study template, regenerate and check:

```bash
python tools/generate.py
python tools/check.py
```

`check.py` validates content and navigation, image metadata, and the generated pages. It also fails on emoji or other pictographic characters and on any color outside the site palette (including inside SVGs).

Contact links are defined in the `CONTACT` object in `js/site.js`. The HTML fallback links need to be updated to match.

## Gallery

Originals go in `tools/source/gallery/` (git-ignored). Then:

```bash
python tools/make_gallery.py
python tools/generate.py
```

The script strips all image metadata, adds new photos to `data/gallery.json`, and keeps any entries you've edited by hand. If a source photo has been removed, it reports it but doesn't delete the entry. Filenames in `tools/gallery-exclusions.json` are skipped on import, so deliberately removed photos don't come back.

To make the gallery black and white, change `--gallery-grayscale` from `0` to `1` in `css/styles.css`.

## Image tools

`process_objects.py` (hero cutouts) and `make_gallery.py` need Pillow and NumPy. Install them in a virtual environment at `tools/.venv/` (git-ignored). The site itself and `generate.py` don't depend on either.

## Social preview

`tools/social-preview.html` is the source for the 1200×630 share card. `tools/render_social.py` renders it with a headless browser, which you point to with the `AGENT_BROWSER_CDP` environment variable. It also embeds the Instrument Serif glyphs used in the favicon. If the screenshot fails, it falls back to a canvas render and says so in the output.

## Notes

- Fonts: Instrument Serif and Inter.
- The hero animation respects `prefers-reduced-motion` and falls back to a static layout.
- `tools/design-review.html` is a local-only type and artwork sheet (git-ignored). View it at `/tools/design-review.html` on the preview server.

## License

Content and images © Vanessa Glowczewski. All rights reserved.