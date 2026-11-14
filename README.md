# Vanessa Glowczewski

Personal website and portfolio: https://vglowczewski.github.io

Built with plain HTML, CSS, and vanilla JavaScript. No frameworks or build step.

## Structure

- `index.html`: home, About me, featured projects, Off the clock, and contact strip
- `experience.html`: experience, leadership and involvement, and education
- `projects.html`, `contact.html`: all projects and contact details
- `data/projects.json`: project content
- `css/` and `js/`: styles and scripts
- `assets/`: images and icons
- `tools/`: scripts that generate project pages and run checks

## Local preview and maintenance

From this folder, run `py -m http.server 8000 --bind 127.0.0.1`, then open
http://127.0.0.1:8000. Stop the server with Ctrl+C.

After editing project data or the case-study template, run:

```powershell
py tools/generate.py
py tools/check.py
```

The home rotates two-color computer, coffee, and planet photo prints on a flat
halftone disc. CSS loops eight-second holds with 0.35-second crossfades.
Reduced-motion preferences show only the static computer, without overlays.
Shared retro icons live in `assets/icons/`; project icons use the `graphic` field.
Contact links use `CONTACT` in `js/site.js`; keep HTML fallback links in sync.

`tools/make_halftone.py` is an optional, offline Pillow/NumPy tool. Its setup and
commands are in its docstring. Keep originals in ignored `tools/source/`, and
install image libraries only in ignored `tools/.venv/`. Neither the site nor
`tools/generate.py` needs them. Prints are opaque, lossless WebP, exactly cobalt
and paper. `tools/hero-prints.json` records actual crop and overlay geometry.
The computer bezel mark is repaired before screening. Do not publish originals.

The checks reject pictographic Unicode characters and colors outside the print
palette, including SVG assets and embedded SVG data. They also check content,
navigation, image metadata, and generation.

`tools/design-review.html` is a local-only, ignored artwork and type sheet.
Open `/tools/design-review.html` on the preview server. Screenshot attempts are
saved under the ignored `tools/screenshots/` directory when capture is available.

---

Content and images © Vanessa Glowczewski. All rights reserved.