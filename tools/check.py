"""Static-site checks. Run: py tools/check.py"""
import contextlib
import copy
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import generate

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.ids = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if "id" in attrs:
            self.ids.append(attrs["id"])


class SiteChecks(unittest.TestCase):
    def test_computer_hero(self):
        home = Document((ROOT / "index.html").read_text(encoding="utf-8"))
        illustrations = [
            attrs for tag, attrs in home.elements
            if tag == "img" and attrs.get("src") == "assets/images/hero-computer.svg"
        ]
        self.assertEqual(len(illustrations), 1)
        self.assertEqual((illustrations[0]["width"], illustrations[0]["height"]), ("480", "400"))
        svg = ET.parse(ROOT / illustrations[0]["src"]).getroot()
        self.assertEqual(svg.attrib["viewBox"], "0 0 480 400")
        self.assertTrue(svg.findall(".//{*}pattern"))
        self.assertTrue(svg.findall(".//{*}circle[@fill='#2F4BCB']"))
        for element in svg.iter():
            self.assertNotIn(element.tag.rsplit("}", 1)[-1], {"script", "foreignObject", "image"})
            for name, value in element.attrib.items():
                if name.rsplit("}", 1)[-1] == "href":
                    self.assertTrue(value.startswith("#"), "Hero artwork must be self-contained")

    def test_palette_contrast_and_hero_only_gradients(self):
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
            ("sky", "navy"), ("red-text", "paper"), ("red-text", "sky"),
        ):
            with self.subTest(foreground=foreground, background=background):
                a, b = luminance(palette[foreground]), luminance(palette[background])
                self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 4.5)

        gradients = [
            (selector.strip(), body) for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
            if "-gradient(" in body
        ]
        self.assertTrue(gradients, "The hero needs its decorative glow")
        for selector, body in gradients:
            self.assertIn(selector, {".hero-art::before", ".hero-art::after"})
            self.assertIn("radial-gradient(", body)
            self.assertIn("blur(", body)

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
        about = Document((ROOT / "about.html").read_text(encoding="utf-8"))
        self.assertIn("experience", about.ids)
        self.assertTrue(any(tag == "a" and attrs.get("href") == "#experience" for tag, attrs in about.elements))

    def test_supplied_personal_details(self):
        expected = {
            "email": "mailto:vanessaglowczewski@gmail.com",
            "linkedin": "https://www.linkedin.com/in/vanessa-glowczewski/",
            "github": "https://github.com/vglowczewski/",
            "instagram": "https://www.instagram.com/nibblingnessa/",
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
        notion = "https://app.notion.com/p/Vanessa-Glowczewski-4079a6324ded8008bd41fe78583d4305"
        pages = list(ROOT.glob("*.html")) + list((ROOT / "projects").glob("*.html"))
        for page in pages:
            doc = Document(page.read_text(encoding="utf-8"))
            self.assertTrue(any(tag == "a" and attrs.get("href") == notion for tag, attrs in doc.elements), page.name)
        about = (ROOT / "about.html").read_text(encoding="utf-8")
        for fact in ("Columbia University", "Industrial Engineering", "May 2028", "Trophy Foods", "INFORMS", "Gourmand", "Multicultural Business Association"):
            self.assertIn(fact, about)
        self.assertNotIn("TODO: Dates", about)
        portrait = ROOT / "assets/images/vanessa-glowczewski.jpg"
        self.assertTrue(portrait.read_bytes().startswith(b"\xff\xd8\xff"))
        self.assertIn('alt="Vanessa Glowczewski smiling in a navy blazer."', about)

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
                self.assertEqual(len(doc.ids), len(set(doc.ids)), "Duplicate IDs")
                self.assertEqual(sum(tag == "h1" for tag, _ in doc.elements), 1)
                for tag in ("header", "main", "footer", "title"):
                    self.assertTrue(any(t == tag for t, _ in doc.elements), f"Missing {tag}")
                for name, value in (("name", "description"), ("name", "viewport"), ("property", "og:title"), ("property", "og:description")):
                    self.assertTrue(any(t == "meta" and a.get(name) == value and a.get("content") for t, a in doc.elements))
                self.assertTrue(any(t == "html" and a.get("lang") == "en" for t, a in doc.elements))
                self.assertTrue(any(t == "a" and a.get("class") == "skip-link" for t, a in doc.elements))
                for tag, attrs in doc.elements:
                    if tag == "img":
                        self.assertTrue(attrs.get("alt"))
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
            for page in ("index.html", "about.html", "projects.html", "contact.html"):
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
                projects[-1]["slug"] = "../unsafe"
                (fixture / "data/projects.json").write_text(json.dumps(projects), encoding="utf-8")
                with self.assertRaises(ValueError):
                    generate.load_projects()
            finally:
                generate.ROOT = original_root


if __name__ == "__main__":
    unittest.main(verbosity=2)
