"""Static-site checks. Run: py tools/check.py"""
import contextlib
import copy
import colorsys
import html
from html.parser import HTMLParser
import io
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import generate

ROOT = Path(__file__).resolve().parents[1]
PALETTE = {"#2F4BCB", "#1C2A5A", "#CFE3F7", "#F4F2EE", "#FFFFFF", "#D93F22"}
SOURCE_TYPES = {".html", ".js", ".json", ".css", ".svg"}
COLOR_ATTRIBUTES = {"fill", "stroke", "color", "stop-color", "flood-color", "lighting-color"}


def source_files():
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in SOURCE_TYPES
                  and not {".git", ".checks", "__pycache__", "screenshots", ".venv", "source"}.intersection(p.relative_to(ROOT).parts))


def pictograph_errors(text):
    # Check literal code points, HTML entities, percent encoding, and JS/JSON escapes.
    expanded = html.unescape(unquote(text))
    expanded = re.sub(r"\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})",
                      lambda m: chr(int(m[1] or m[2], 16)), expanded)
    expanded = re.sub(r"[\ud800-\udbff][\udc00-\udfff]",
                      lambda m: chr(0x10000 + ((ord(m[0][0]) - 0xd800) << 10) + ord(m[0][1]) - 0xdc00),
                      expanded)
    return [
        f"line {expanded.count(chr(10), 0, i) + 1}: U+{ord(c):04X}"
        for i, c in enumerate(expanded)
        if 0x1f000 <= ord(c) <= 0x1faff or 0x2600 <= ord(c) <= 0x27bf
        or 0x2b00 <= ord(c) <= 0x2bff or ord(c) == 0xfe0f
    ]


def color_errors(value):
    """Validate explicit paint values, including alpha variants, without dependencies."""
    errors = []
    value = re.sub(r"\s*!important\b", "", value, flags=re.I)
    value = re.sub(r"url\([^)]*\)", "", value, flags=re.I)
    value = re.sub(r"--[\w-]+", "", value)

    def hex_color(match):
        literal = match[0]
        digits = literal[1:]
        if len(digits) in {3, 4}:
            digits = "".join(c * 2 for c in digits)
        if len(digits) not in {6, 8} or "#" + digits[:6].upper() not in PALETTE:
            errors.append(literal)
        return " "

    value = re.sub(r"#[0-9a-fA-F]+\b", hex_color, value)

    def functional_color(match):
        literal, name, body = match[0], match[1].lower(), match[2]
        parts = re.split(r"[\s,]+", body.split("/")[0].strip())
        try:
            if name in {"rgb", "rgba"}:
                channels = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
            elif name in {"hsl", "hsla"}:
                hue = parts[0]
                multiplier = 360 if hue.endswith("turn") else 180 / 3.141592653589793 if hue.endswith("rad") and not hue.endswith("grad") else .9 if hue.endswith("grad") else 1
                h = float(re.sub(r"(deg|grad|rad|turn)$", "", hue)) * multiplier / 360
                channels = [c * 255 for c in colorsys.hls_to_rgb(h, float(parts[2].rstrip("%")) / 100, float(parts[1].rstrip("%")) / 100)]
            else:
                raise ValueError
            if len(channels) != 3 or any(not 0 <= c <= 255 for c in channels):
                raise ValueError
            normalized = "#" + "".join(f"{round(c):02X}" for c in channels)
            if normalized not in PALETTE:
                errors.append(literal)
        except (ValueError, IndexError):
            errors.append(literal)
        return " "

    value = re.sub(r"\b(rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color|color-mix|device-cmyk)\(([^()]*)\)",
                   functional_color, value, flags=re.I)
    allowed = {
        "white", "transparent", "currentcolor", "none", "inherit", "initial", "unset", "revert", "revert-layer",
        "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset", "hidden",
        "auto", "center", "top", "right", "bottom", "left", "repeat", "no-repeat", "repeat-x", "repeat-y",
        "space", "round", "cover", "contain", "scroll", "fixed", "local", "padding-box", "border-box", "content-box", "text",
        "var", "calc", "min", "max", "clamp", "drop-shadow", "linear-gradient", "radial-gradient", "conic-gradient",
        "circle", "ellipse", "closest-side", "farthest-side", "closest-corner", "farthest-corner", "at", "to",
    }
    errors.extend(token for token in re.findall(r"(?<![\w-])[a-zA-Z][\w-]*", value) if token.lower() not in allowed)
    return errors


def css_palette_errors(text):
    errors = []
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Data-URI artwork has its own presentation attributes.
    for match in re.finditer(r'url\((["\'])(data:image/svg\+xml,.*?)\1\)', text, re.S):
        errors.extend(svg_palette_errors(unquote(match[2].split(",", 1)[1])))
    for match in re.finditer(r"([-\w]+)\s*:\s*([^;{}]+)", text):
        name, value = match[1].lower(), match[2]
        if name.startswith(("--", "background", "border", "outline")) or name in COLOR_ATTRIBUTES | {"box-shadow", "text-shadow", "text-decoration-color", "caret-color", "accent-color", "column-rule-color", "filter"}:
            if name == "filter":
                value = re.sub(r"\b(?:grayscale|contrast|saturate|brightness|opacity|hue-rotate|invert|sepia)\([^)]*\)", "", value)
            if name.startswith("--font"):
                continue
            errors.extend(f"line {text.count(chr(10), 0, match.start()) + 1}: {name}: {c}" for c in color_errors(value))
    return errors


def svg_palette_errors(text):
    root = ET.fromstring(text)
    errors = []
    for element in root.iter():
        for name, value in element.attrib.items():
            if name in COLOR_ATTRIBUTES:
                errors.extend(f"{element.tag.rsplit('}', 1)[-1]} {name}: {c}" for c in color_errors(value))
            elif name == "style":
                errors.extend(css_palette_errors(value))
        if element.tag.rsplit("}", 1)[-1] == "style":
            errors.extend(css_palette_errors(element.text or ""))
        if element.attrib.get("attributeName") in COLOR_ATTRIBUTES:
            for name in ("from", "to", "by", "values"):
                for value in element.attrib.get(name, "").split(";"):
                    errors.extend(color_errors(value))
    return errors


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.ids = []
        self.stack = []
        self.errors = []
        self.feed(text)
        if self.stack:
            self.errors.append(f"Unclosed tags: {self.stack}")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"Unexpected closing tag: {tag}")
        else:
            self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()


def plain_text(markup):
    return html.unescape(re.sub(r"<[^>]*>", "", markup)).strip()


class SiteChecks(unittest.TestCase):
    def test_photo_hero(self):
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        art = re.search(r'<div class="hero-art".*?(?=\s*<div class="hero-bottom")', home, re.S)[0]
        doc = Document(art)
        self.assertEqual(doc.errors, [])
        self.assertEqual(doc.elements[0][1]["role"], "img")
        self.assertEqual(doc.elements[0][1]["aria-label"], "Halftone photos: a computer, a cup of coffee, and a ringed planet")
        self.assertEqual([a["src"] for t, a in doc.elements if t == "img" and a["src"].startswith("assets/images/hero-")], [
            "assets/images/hero-computer.webp", "assets/images/hero-coffee.webp", "assets/images/hero-planet.webp",
        ])
        self.assertNotIn("<button", art)
        self.assertNotIn("assets/stickers/", home)
        css = (ROOT / "css/styles.css").read_text(encoding="utf-8")
        self.assertIn("animation-duration: 25.05s", css)
        self.assertIn("animation-iteration-count: infinite", css)
        self.assertIn("animation-fill-mode: both", css)
        for name in ("computer", "coffee", "planet"):
            self.assertIn(f"@keyframes print-{name}", css)
        for name in ("cursor-path", "cursor-click", "coffee-ripple", "moon-orbit"):
            self.assertIn(f"@keyframes {name}", css)
        reduced = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn(".hero-print { opacity: 0;", reduced)
        self.assertIn(".print-computer { opacity: 1; }", reduced)
        self.assertIn(".print-overlay { display: none; }", reduced)
        self.assertNotRegex(home, r"<(?:canvas|video|iframe)\b")

    def test_photo_files(self):
        sizes = {"computer": (640, 548), "coffee": (640, 640), "planet": (640, 480)}
        geometry = json.loads((ROOT / "tools/hero-prints.json").read_text(encoding="utf-8"))
        for name, size in sizes.items():
            content = (ROOT / f"assets/images/hero-{name}.webp").read_bytes()
            self.assertEqual(content[:4], b"RIFF")
            self.assertEqual(content[8:16], b"WEBPVP8L", "Prints must be lossless WebP")
            self.assertEqual(content[20], 0x2f)
            bits = int.from_bytes(content[21:25], "little")
            self.assertEqual(((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1), size)
            self.assertFalse(bits & (1 << 28), "Prints must have no transparency")
            self.assertEqual(geometry[name]["output_size"], list(size))
        css = (ROOT / "css/styles.css").read_text(encoding="utf-8")
        self.assertIn(f'top: {geometry["coffee"]["center_percent"][1]}%', css)
        self.assertIn(f'width: {geometry["coffee"]["radius_percent_width"] * 2:g}%', css)
        self.assertIn(f'top: {geometry["planet"]["center_percent"][1] - 16:g}%', css)
        self.assertIn("transform: rotate(-13deg)", css)
        self.assertIn("box-shadow: 4px 4px 0 var(--red)", css)
        self.assertIn("box-shadow: 4px 4px 0 var(--sky)", css)
        self.assertIn("drop-shadow(3px 3px 0 var(--red))", css)
        self.assertIn("tools/source/", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        self.assertNotIn("source/", (ROOT / "index.html").read_text(encoding="utf-8"))

    def test_photo_pixels_with_offline_tools(self):
        interpreter = ROOT / "tools/.venv/Scripts/python.exe"
        if not interpreter.is_file():
            interpreter = ROOT / "tools/.venv/bin/python"
        if not interpreter.is_file():
            if not all(importlib.util.find_spec(module) for module in ("PIL", "numpy")):
                self.skipTest("Optional offline Pillow/NumPy tools are not installed; WebP headers checked separately")
            interpreter = Path(sys.executable)
        result = subprocess.run([str(interpreter), str(ROOT / "tools/make_halftone.py"), "--check"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_pictographic_characters(self):
        errors = [f"{p.relative_to(ROOT)}: {error}" for p in source_files()
                  for error in pictograph_errors(p.read_text(encoding="utf-8"))]
        self.assertEqual(errors, [], "\n" + "\n".join(errors))

    def test_palette_only(self):
        css = ROOT / "css/styles.css"
        errors = [f"{css.relative_to(ROOT)}: {e}" for e in css_palette_errors(css.read_text(encoding="utf-8"))]
        for path in source_files():
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".svg":
                errors.extend(f"{path.relative_to(ROOT)}: {e}" for e in svg_palette_errors(text))
            elif path.suffix == ".html":
                for inline in re.findall(r"<svg\b.*?</svg>", text, flags=re.S):
                    errors.extend(f"{path.relative_to(ROOT)}: {e}" for e in svg_palette_errors(inline))
        self.assertEqual(errors, [], "\n" + "\n".join(errors))

    def test_design_guards_reject_invalid_inputs(self):
        for codepoint in (0x1f000, 0x1faff, 0x2600, 0x27bf, 0x2b00, 0x2bff, 0xfe0f, 0x1f1e6):
            self.assertTrue(pictograph_errors(chr(codepoint)))
        self.assertTrue(pictograph_errors("&#x1f680;"))
        self.assertTrue(pictograph_errors(r"\ud83d\ude80"))
        self.assertTrue(pictograph_errors(r"\u{1f680}"))
        self.assertFalse(pictograph_errors("vg ↗ ↓ ← –"))
        for color in ("#808080", "#123", "#12345678", "gray", "rgb(0 0 0 / .2)", "hsl(0 0% 50%)", "color(srgb 0 0 0)"):
            self.assertTrue(css_palette_errors(f".example {{ background: {color}; }}"), color)
            self.assertTrue(svg_palette_errors(f'<svg xmlns="http://www.w3.org/2000/svg"><path fill="{color}"/></svg>'), color)
        for color in ("white", "#fff", "#2f4bcb", "#2F4BCB22", "rgba(28,42,90,.15)", "rgb(47 75 203 / 25%)", "transparent", "#2F4BCB !important"):
            self.assertFalse(color_errors(color), color)
        self.assertTrue(css_palette_errors(".example { --bad: pink; color: var(--bad); }"))
        self.assertTrue(css_palette_errors(".example { color: var(--missing, brown); }"))
        self.assertFalse(color_errors("url(#face)"))
        self.assertTrue(css_palette_errors("""a { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cpath fill='%23808080'/%3E%3C/svg%3E"); }"""))
        # Prove the actual build checks fail and report the offending file.
        checks = ROOT / ".checks"
        checks.mkdir(exist_ok=True)
        original_root = ROOT
        with tempfile.TemporaryDirectory(dir=checks) as temporary:
            fixture = Path(temporary)
            (fixture / "css").mkdir()
            (fixture / "css/styles.css").write_text("body { color: #808080; }", encoding="utf-8")
            (fixture / "bad.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>' + chr(0x1f680) + '</text></svg>',
                encoding="utf-8",
            )
            try:
                globals()["ROOT"] = fixture
                for name, evidence in (("test_no_pictographic_characters", "bad.svg"), ("test_palette_only", "#808080")):
                    result = unittest.TestResult()
                    SiteChecks(name).run(result)
                    self.assertEqual(len(result.failures), 1)
                    self.assertFalse(result.errors)
                    self.assertIn(evidence, result.failures[0][1])
            finally:
                globals()["ROOT"] = original_root

    def test_retro_artwork(self):
        icons = list((ROOT / "assets/icons").glob("*.svg"))
        self.assertEqual(len(icons), 12)
        self.assertEqual(list((ROOT / "assets/stickers").glob("*.svg")), [])
        for path in icons:
            svg = ET.parse(path).getroot()
            self.assertEqual(svg.attrib["viewBox"], "0 0 64 64")
            self.assertEqual(len(svg.findall(".//{*}text")), 0, path.name)
            self.assertEqual(len(svg.findall(".//*[@fill='#D93F22']")), 1, path.name)
            if path.stem != "brand-starburst":
                self.assertTrue(svg.findall(".//{*}pattern"), path.name)
                self.assertTrue(any(e.attrib.get("stroke", svg.attrib.get("stroke")) == "#2F4BCB"
                                    and e.attrib.get("stroke-width", svg.attrib.get("stroke-width")) == "3" for e in svg.iter()))
            ids = {e.attrib["id"] for e in svg.iter() if "id" in e.attrib}
            for element in svg.iter():
                self.assertNotIn(element.tag.rsplit("}", 1)[-1], {"script", "foreignObject", "image"})
                for value in element.attrib.values():
                    for reference in re.findall(r"url\(#([^)]+)\)", value):
                        self.assertIn(reference, ids)
        self.assertEqual([p["graphic"] for p in generate.load_projects()], [
            "assets/icons/popcorn.svg", "assets/icons/fork-plate.svg", "assets/icons/ticket.svg", "assets/icons/map-pin.svg",
        ])
        css = (ROOT / "css/styles.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"(?:linear|radial|conic)-gradient\(|\bblur\(")

    def test_home_sections_and_exact_copy(self):
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"<section[^>]*aria-labelledby=\"([^\"]+)\"", home), [
            "hero-title", "about-title", "work-title", "off-clock-title", "contact-strip-title",
        ])
        for rail in ("About / 01", "Projects / 02", "OFF THE CLOCK / 03", "Contact / 04"):
            self.assertIn(rail, home)
        about = re.search(r'<div class="about-copy">(.*?)</div>', home, re.S)[1]
        self.assertEqual([plain_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", about, re.S)], [
            "I'm an Industrial Engineering student at Columbia University in New York, with a minor in Economics and AI. My coursework focuses on data analytics, stochastics, and optimization, which I'm interested in applying to products and operations.",
            "At Kraft Heinz, I focused on operations and continuous improvement, driving projects across functional teams. Previously, I gained hands-on engineering experience at Trophy Foods, and I founded SnackSpot, a direct-to-consumer snack kit company.",
            "On campus, I co-lead Columbia's INFORMS chapter, serve on Engineering Student Council, and connect students with New York's food community through Gourmand. Outside of work, I enjoy food and restaurant reviews, photography, travel, Pilates, golf, and hiking.",
        ])
        self.assertNotIn("<a ", about)
        portrait = re.search(r'<figure class="polaroid">.*?</figure>', home, re.S)[0]
        self.assertNotIn("figcaption", portrait)
        self.assertIn('src="assets/images/vanessa-glowczewski.jpg"', portrait)
        self.assertIn('id="currently-title">Currently…', home)
        self.assertIn('data-limit="3"', home)
        interests = re.findall(r'<article class="interest-card">(.*?)</article>', home, re.S)
        self.assertEqual(len(interests), 3)
        self.assertEqual([plain_text(re.search(r"<p>(.*?)</p>", card)[1]) for card in interests], [
            "I'm learning Spanish and have taken Spanish Pragmatics and Advanced Spanish through Columbia's LAIC department.",
            "I'm fascinated by space, especially space exploration and the search for alien life.",
            "I love classics. Favorites include War and Peace, Dracula, Jane Eyre, and And Then There Were None.",
        ])
        for number, (card, title, graphic) in enumerate(zip(interests, ("Spanish", "Space", "Literature"), ("speech-bubble", "ringed-planet", "open-book")), 1):
            self.assertIn(f"<h3>{title}</h3>", card)
            self.assertIn(f'src="assets/icons/{graphic}.svg"', card)
            self.assertIn(f'<span class="label interest-number">{number:02}</span>', card)
            self.assertNotRegex(card, r"<a\b")
        self.assertEqual(re.findall(r"<em>(.*?)</em>", interests[2]), [
            "War and Peace", "Dracula", "Jane Eyre", "And Then There Were None",
        ])
        strip = home.split('id="get-in-touch"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Get in touch.</h2>", strip)
        self.assertEqual({a["data-contact"]: a["href"] for t, a in Document(strip).elements if t == "a"}, {
            "email": "mailto:vanessaglowczewski@gmail.com",
            "linkedin": "https://www.linkedin.com/in/vanessa-glowczewski/",
        })

    def test_experience_groups_and_chronology(self):
        page = (ROOT / "experience.html").read_text(encoding="utf-8")
        self.assertIn("<title>Experience — Vanessa Glowczewski</title>", page)
        self.assertNotIn('class="about-copy"', page)
        self.assertNotIn('class="polaroid"', page)
        groups = re.findall(r'<section class="timeline-section".*?</section>', page, re.S)
        self.assertEqual(len(groups), 3)
        self.assertEqual([plain_text(re.search(r"<h2[^>]*>(.*?)</h2>", group)[1]) for group in groups], [
            "Experience", "Leadership & Involvement", "Education",
        ])
        expected_titles = [
            ["Supply Chain Development Innovation Intern, Kraft Heinz", "Engineering & EHS Intern, Trophy Foods"],
            ["Multicultural Business Association · Fellow", "Engineering Student Council · Campus Affairs", "Columbia Gourmand · Vice President", "Columbia INFORMS · Co-President", "Mentor, Society of Women Engineers"],
            ["Columbia University · Industrial Engineering"],
        ]
        expected_dates = [
            ["May – Aug 2026", "Jun – Aug 2025"],
            ["Oct 2026 – Present", "May 2025 – Present", "Jan 2025 – Present", "Sep 2024 – Present", "Sep 2024 – Present"],
            ["May 2028"],
        ]
        for group, titles, dates in zip(groups, expected_titles, expected_dates):
            self.assertEqual([plain_text(t) for t in re.findall(r"<h3>(.*?)</h3>", group)], titles)
            self.assertEqual(re.findall(r'<li><span class="label">(.*?)</span>', group), dates)
        self.assertIn("Mentor in SWE's mentorship program. Attended the 2026 SWE conference in Boston.", groups[1])
        self.assertIn("Built an automated root cause analysis dashboard and a supply chain losses forecasting tool, led continuous improvement reviews, and directed cross-team workshops to pilot new process flows.", groups[0])
        self.assertIn("Worked on safety and engineering programs, including Lockout Tagout, facility layouts, and employee safety training.", groups[0])

    def test_removed_sources_and_project_link_policy(self):
        sources = list(ROOT.glob("*.html")) + list(ROOT.glob("*.md")) + [ROOT / "sitemap.xml"]
        for folder in ("js", "css", "tools", "templates", "data", "assets"):
            sources.extend(p for p in (ROOT / folder).rglob("*") if p.suffix in {".html", ".md", ".js", ".css", ".py", ".json", ".svg"}
                           and not {".venv", "source", "screenshots", "__pycache__"}.intersection(p.relative_to(ROOT).parts))
        for path in sources:
            text = path.read_text(encoding="utf-8").lower()
            for removed in ("no" + "tion", "about" + ".html"):
                self.assertNotIn(removed, text, str(path.relative_to(ROOT)))
        self.assertEqual([[link["url"] for link in p["links"]] for p in generate.load_projects()], [
            ["https://snackspot.ca/"], [], [], ["https://github.com/vglowczewski/restaurant-alternatives"],
        ])

    def test_palette_contrast(self):
        css = (ROOT / "css/styles.css").read_text(encoding="utf-8")
        palette = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6});", css))
        expected = {
            "cobalt": "#2F4BCB", "navy": "#1C2A5A", "sky": "#CFE3F7",
            "paper": "#F4F2EE", "white": "#FFFFFF", "red": "#D93F22",
        }
        for name, value in expected.items():
            self.assertEqual(palette[name].upper(), value)
        self.assertIn("--frame: 1.5px solid var(--navy);", css)

        def luminance(color):
            rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            return sum(
                (x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4) * weight
                for x, weight in zip(rgb, (.2126, .7152, .0722))
            )

        for foreground, background in (
            ("navy", "paper"), ("navy", "sky"), ("cobalt", "paper"),
            ("cobalt", "sky"), ("white", "cobalt"), ("paper", "navy"),
            ("sky", "navy"),
        ):
            with self.subTest(foreground=foreground, background=background):
                a, b = luminance(palette[foreground]), luminance(palette[background])
                self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 4.5)
        # Worst case under a grain dot, not merely the untouched paper average.
        grain_paper = "#" + "".join(f"{round(int(palette['paper'][i:i + 2], 16) * .945 + int(palette['cobalt'][i:i + 2], 16) * .055):02X}" for i in (1, 3, 5))
        for foreground in ("navy", "cobalt"):
            a, b = luminance(palette[foreground]), luminance(grain_paper)
            self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 4.5)

    def test_resume_is_not_publicly_downloadable(self):
        pages = list(ROOT.glob("*.html")) + list((ROOT / "projects").glob("*.html"))
        for page in pages:
            for tag, attrs in Document(page.read_text(encoding="utf-8")).elements:
                self.assertNotIn("data-resume", attrs, page.name)
                if tag == "a":
                    self.assertNotIn("download", attrs, page.name)
                    self.assertNotIn("resume", attrs.get("href", "").lower(), page.name)
        script = (ROOT / "js/site.js").read_text(encoding="utf-8")
        self.assertNotIn("showResumeNote", script)
        self.assertNotIn("data-resume", script)
        documents = [
            path for path in (ROOT / "assets").rglob("*")
            if "resume" in path.name.lower() and path.suffix.lower() in {".pdf", ".doc", ".docx"}
        ]
        self.assertEqual(documents, [], "Reference resumes must not be hosted in public assets")
        experience = Document((ROOT / "experience.html").read_text(encoding="utf-8"))
        self.assertIn("experience", experience.ids)

    def test_supplied_personal_details(self):
        expected = {
            "email": "mailto:vanessaglowczewski@gmail.com",
            "linkedin": "https://www.linkedin.com/in/vanessa-glowczewski/",
            "github": "https://github.com/vglowczewski/",
        }
        contact = (ROOT / "contact.html").read_text(encoding="utf-8")
        links = {attrs["data-contact"]: attrs.get("href") for tag, attrs in Document(contact).elements if tag == "a" and "data-contact" in attrs}
        self.assertEqual(links, expected, "Contact links must also work without JavaScript")
        self.assertNotIn("hello@example.com", contact)
        self.assertNotIn("TODO: Add LinkedIn", contact)
        self.assertNotIn("TODO: Add GitHub", contact)
        site_js = (ROOT / "js/site.js").read_text(encoding="utf-8")
        for url in expected.values():
            self.assertIn(url.removeprefix("mailto:"), site_js)
        experience = (ROOT / "experience.html").read_text(encoding="utf-8")
        for fact in ("Columbia University", "Industrial Engineering", "May 2028", "Trophy Foods", "INFORMS", "Gourmand", "Multicultural Business Association"):
            self.assertIn(fact, experience)
        self.assertNotIn("TODO: Dates", experience)
        portrait = ROOT / "assets/images/vanessa-glowczewski.jpg"
        self.assertTrue(portrait.read_bytes().startswith(b"\xff\xd8\xff"))
        self.assertIn('alt="Vanessa Glowczewski smiling in a navy blazer."', (ROOT / "index.html").read_text(encoding="utf-8"))

    def test_project_data_and_generated_content(self):
        for project in generate.load_projects():
            page = (ROOT / "projects" / f'{project["slug"]}.html').read_text(encoding="utf-8")
            doc = Document(page)
            self.assertIn(generate.escape(project["title"]), page)
            for field in ("summary", "role", "problem", "approach", "outcome"):
                self.assertIn(generate.escape(project[field]), page)
            for section in ("overview", "problem", "approach", "outcome", "links"):
                self.assertIn(section, doc.ids)
            self.assertEqual('<dt class="label">Year</dt>' in page, bool(project["year"].strip()))
            if project.get("note"):
                self.assertIn(generate.escape(project["note"]), page)
                self.assertTrue(any(tag == "p" and attrs.get("class") == "note" for tag, attrs in doc.elements))
            for link in project["links"]:
                if link["url"]:
                    self.assertTrue(any(tag == "a" and attrs.get("href") == link["url"] and attrs.get("class") == "text-link" for tag, attrs in doc.elements))
            self.assertNotIn("TODO: This is a draft case study", page)

    def test_shared_social_preview(self):
        expected = "https://vglowczewski.github.io/assets/images/social-preview.png"
        self.assertEqual(generate.SOCIAL_IMAGE, expected)
        image = (ROOT / "assets/images/social-preview.png").read_bytes()
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", image[16:24]), (1200, 630))
        pages = list(ROOT.glob("*.html")) + list((ROOT / "projects").glob("*.html"))
        pages.append(ROOT / "templates/project.html")
        for page in pages:
            elements = Document(page.read_text(encoding="utf-8")).elements
            with self.subTest(page=page.name):
                for key, name in (("property", "og:image"), ("name", "twitter:image")):
                    values = [attrs.get("content") for tag, attrs in elements if tag == "meta" and attrs.get(key) == name]
                    self.assertEqual(values, [expected])
                self.assertTrue(any(tag == "meta" and attrs.get("name") == "twitter:card" and attrs.get("content") == "summary_large_image" for tag, attrs in elements))

    def test_project_images_are_durable_local_assets(self):
        signatures = {
            ".png": b"\x89PNG\r\n\x1a\n",
            ".jpg": b"\xff\xd8\xff",
            ".jpeg": b"\xff\xd8\xff",
            ".gif": b"GIF8",
        }
        for project in generate.load_projects():
            for image in project["images"]:
                path = ROOT / image["src"]
                content = path.read_bytes()
                with self.subTest(image=image["src"]):
                    suffix = path.suffix.lower()
                    if suffix == ".svg":
                        self.assertEqual(ET.fromstring(content).tag, "{http://www.w3.org/2000/svg}svg")
                    elif suffix == ".webp":
                        self.assertEqual(content[:4], b"RIFF")
                        self.assertEqual(content[8:12], b"WEBP")
                        dimensions = None
                        offset = 12
                        while offset + 8 <= len(content):
                            kind = content[offset:offset + 4]
                            size = int.from_bytes(content[offset + 4:offset + 8], "little")
                            chunk = content[offset + 8:offset + 8 + size]
                            if kind == b"VP8 ":
                                self.assertEqual(chunk[3:6], b"\x9d\x01\x2a")
                                dimensions = tuple(n & 0x3fff for n in struct.unpack("<HH", chunk[6:10]))
                            elif kind == b"VP8L":
                                bits = int.from_bytes(chunk[1:5], "little")
                                dimensions = ((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
                            elif kind == b"VP8X":
                                dimensions = tuple(int.from_bytes(chunk[i:i + 3], "little") + 1 for i in (4, 7))
                            if dimensions:
                                break
                            offset += 8 + size + (size % 2)
                        self.assertEqual(dimensions, (image["width"], image["height"]), "Stored WebP dimensions must match project data")
                    elif suffix == ".avif":
                        self.assertEqual(content[4:8], b"ftyp")
                        self.assertIn(b"avif", content[8:32])
                    else:
                        self.assertIn(suffix, signatures, "Use a browser-supported image format")
                        self.assertTrue(content.startswith(signatures[suffix]))
        self.assertNotIn("X-Amz-", (ROOT / "data/projects.json").read_text(encoding="utf-8"))

    def test_pages_and_internal_links(self):
        files = list(ROOT.glob("*.html")) + list((ROOT / "projects").glob("*.html"))
        self.assertEqual(len(files), 4 + len(generate.load_projects()))
        for file in files:
            with self.subTest(page=file.name):
                text = file.read_text(encoding="utf-8")
                self.assertTrue(text.lower().startswith("<!doctype html>"))
                self.assertNotIn("</+", text)
                doc = Document(text)
                self.assertEqual(doc.errors, [], "HTML tags must be properly closed and nested")
                self.assertEqual(len(doc.ids), len(set(doc.ids)), "Duplicate IDs")
                self.assertEqual(sum(tag == "h1" for tag, _ in doc.elements), 1)
                for tag in ("header", "main", "footer", "title"):
                    self.assertTrue(any(t == tag for t, _ in doc.elements), f"Missing {tag}")
                for name, value in (("name", "description"), ("name", "viewport"), ("property", "og:title"), ("property", "og:description")):
                    self.assertTrue(any(t == "meta" and a.get(name) == value and a.get("content") for t, a in doc.elements))
                self.assertTrue(any(t == "html" and a.get("lang") == "en" for t, a in doc.elements))
                self.assertTrue(any(t == "a" and a.get("class") == "skip-link" for t, a in doc.elements))
                nav = re.search(r'<nav class="site-nav".*?</nav>', text, re.S)[0]
                self.assertEqual([plain_text(a).replace("\xa0", " ").removesuffix(" ↗").strip() for a in re.findall(r"<a[^>]*>(.*?)</a>", nav)], ["Home", "Experience", "Projects", "Contact"])
                nav_links = [attrs["href"].split("/")[-1] for tag, attrs in Document(nav).elements if tag == "a"]
                self.assertEqual(nav_links, ["index.html", "experience.html", "projects.html", "contact.html"])
                for tag, attrs in doc.elements:
                    for reference in ("aria-labelledby", "aria-controls"):
                        for identifier in attrs.get(reference, "").split():
                            self.assertIn(identifier, doc.ids, f"Missing accessible reference: {identifier}")
                    if tag == "img":
                        self.assertIn("alt", attrs)
                        self.assertTrue(attrs["alt"] or attrs.get("aria-hidden") == "true", "Decorative images need an empty alt and aria-hidden")
                        self.assertTrue(attrs.get("width") and attrs.get("height"))
                    for key in ("href", "src"):
                        url = attrs.get(key)
                        if not url or urlsplit(url).scheme or url.startswith("//"):
                            continue
                        parts = urlsplit(url)
                        target = (file.parent / unquote(parts.path)).resolve() if parts.path else file
                        self.assertTrue(target.is_file(), f"{file.name}: missing {url}")
                        if parts.fragment and target.suffix == ".html":
                            ids = Document(target.read_text(encoding="utf-8")).ids
                            self.assertIn(unquote(parts.fragment), ids, f"Missing anchor: {url}")

    def test_sitemap(self):
        doc = ET.parse(ROOT / "sitemap.xml")
        locations = [node.text for node in doc.findall(".//{*}loc")]
        projects = generate.load_projects()
        self.assertEqual(len(locations), 4 + len(projects))
        for project in projects:
            self.assertTrue(any(url.endswith(f'/projects/{project["slug"]}.html') for url in locations))

    def test_generator_edit_add_escape_and_domain_persistence(self):
        checks = ROOT / ".checks"
        checks.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=checks) as temporary:
            fixture = Path(temporary)
            for folder in ("assets", "data", "templates"):
                shutil.copytree(ROOT / folder, fixture / folder)
            for page in ("index.html", "experience.html", "projects.html", "contact.html"):
                shutil.copy2(ROOT / page, fixture / page)
            original_root = generate.ROOT
            try:
                generate.ROOT = fixture
                projects = json.loads((fixture / "data/projects.json").read_text(encoding="utf-8"))
                projects[0]["summary"] = "Updated project text from the single source"
                added = copy.deepcopy(projects[0])
                added.update(
                    slug="test-new-project", title='A <new> & "real" project',
                    summary="Summary & evidence", images=[], links=[], year="",
                    note='Independent <concept> & "draft"',
                )
                projects.append(added)
                (fixture / "data/projects.json").write_text(json.dumps(projects), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    generate.generate("https://portfolio.example/repository")
                new_page = fixture / "projects/test-new-project.html"
                text = new_page.read_text(encoding="utf-8")
                self.assertIn("A &lt;new&gt; &amp; &quot;real&quot; project", text)
                self.assertNotIn("<new>", text)
                self.assertIn("Independent &lt;concept&gt; &amp; &quot;draft&quot;", text)
                self.assertNotIn('<dt class="label">Year</dt>', text)
                self.assertIn("No public project links yet.", text)
                self.assertNotIn("TODO: Add project links.", text)
                edited = fixture / "projects" / f'{projects[0]["slug"]}.html'
                self.assertIn(projects[0]["summary"], edited.read_text(encoding="utf-8"))
                self.assertIn("https://portfolio.example/repository/projects/test-new-project.html", text)
                self.assertNotIn("TODO: Set the final domain", (fixture / "sitemap.xml").read_text(encoding="utf-8"))
                self.assertNotIn("TODO: Set your real domain", (fixture / "robots.txt").read_text(encoding="utf-8"))
                self.assertIn("test-new-project.html", (fixture / "projects.html").read_text(encoding="utf-8"))
                before = {path.relative_to(fixture): path.read_bytes() for path in fixture.rglob("*") if path.is_file()}
                with contextlib.redirect_stdout(io.StringIO()):
                    generate.generate()
                after = {path.relative_to(fixture): path.read_bytes() for path in fixture.rglob("*") if path.is_file()}
                self.assertEqual(before, after, "Regeneration must be idempotent and preserve domain/subpath")
                projects[-1]["note"] = ["not plain text"]
                (fixture / "data/projects.json").write_text(json.dumps(projects), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "note must be plain text"):
                    generate.load_projects()
                projects[-1]["note"] = ""
                graphic = projects[-1]["graphic"]
                for invalid in ("https://example.com/icon.svg", "assets/icons/../../README.md", "assets/icons/missing.svg"):
                    projects[-1]["graphic"] = invalid
                    (fixture / "data/projects.json").write_text(json.dumps(projects), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "graphic must be a local SVG"):
                        generate.load_projects()
                projects[-1]["graphic"] = graphic
                projects[-1]["slug"] = "../unsafe"
                (fixture / "data/projects.json").write_text(json.dumps(projects), encoding="utf-8")
                with self.assertRaises(ValueError):
                    generate.load_projects()
            finally:
                generate.ROOT = original_root


if __name__ == "__main__":
    unittest.main(verbosity=2)
