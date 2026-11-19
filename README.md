# Vanessa Glowczewski

Personal website and portfolio: https://vglowczewski.github.io

Built with plain HTML, CSS, and vanilla JavaScript. No frameworks or build step.

## Structure

- `index.html`: home, About me, project interests, Off the clock, and contact strip
- `experience.html`: experience, leadership and involvement, and education
- `projects.html`, `contact.html`: all projects and contact details
- `gallery.html`, `data/gallery.json`: food and travel photos, captions, and focus positions
- `data/projects.json`: project content
- `css/` and `js/`: styles and scripts
- `assets/`: images and film textures
- `tools/`: scripts that generate project pages and run checks

## Local preview and maintenance

From this folder, run `py -m http.server 8000 --bind 127.0.0.1`, then open
http://127.0.0.1:8000. Stop the server with Ctrl+C.

After editing project data or the case-study template, run:

```powershell
py tools/generate.py
py tools/check.py
```

The film-inspired interface uses Instrument Serif and Inter. Grayscale object
cutouts form the hero; reduced-motion preferences make the composition static.
Contact links use `CONTACT` in `js/site.js`; keep HTML fallback links in sync.

Offline image tools are `tools/process_objects.py` and `tools/make_gallery.py`.
Use Pillow/NumPy only in ignored `tools/.venv/`; the site and generator do not
need them. Keep originals in ignored `tools/source/`. The gallery tool searches
`tools/source/gallery/` recursively, strips all metadata, preserves edited JSON
entries, adds new photos, and reports removed sources without deleting entries.
`tools/gallery-exclusions.json` lists deliberately removed gallery filenames so
they are not reimported; original photos remain untouched in `tools/source/`.
Run the gallery tool, then regenerate after adding photos. Change
`--gallery-grayscale` in `css/styles.css` from `0` to `1` for monochrome photos.

The checks reject pictographic Unicode characters and colors outside the interface
palette, including SVG assets and embedded SVG data. They also check content,
navigation, image metadata, and generation.

`tools/design-review.html` is a local-only, ignored artwork and type sheet.
Open `/tools/design-review.html` on the preview server. Screenshot attempts are
saved under the ignored `tools/screenshots/` directory when capture is available.

`tools/social-preview.html` is the 1200×630 social-card source.
`tools/render_social.py`, run with the local image-tool environment and a supplied
`AGENT_BROWSER_CDP` endpoint, captures its actual HTML with the loaded site fonts
and embeds Instrument Serif glyphs in the favicon. The attached browser's fixed
viewport is handled with native, unscaled screenshot tiles. A blocked capture
uses an explicitly reported browser-canvas fallback, never labelled a screenshot.

---

Content and images © Vanessa Glowczewski. All rights reserved.