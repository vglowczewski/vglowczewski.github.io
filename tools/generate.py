"""Regenerate static project pages and sitemap. Python standard library only."""
import argparse
import html
import json
from pathlib import Path
import re
from string import Template
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "slug", "title", "graphic", "tags", "summary", "year", "role",
    "problem", "approach", "outcome", "links", "images",
}
TAGS = {"Product", "Coded", "Case Study"}
SOCIAL_IMAGE = "https://vglowczewski.github.io/assets/images/social-preview.png"


def escape(value):
    return html.escape(str(value), quote=True)


def load_projects():
    projects = json.loads((ROOT / "data/projects.json").read_text(encoding="utf-8"))
    if not isinstance(projects, list) or not projects:
        raise ValueError("projects.json must contain a nonempty array.")
    slugs = set()
    for project in projects:
        if not REQUIRED.issubset(project):
            raise ValueError(f"Missing fields: {REQUIRED - project.keys()}")
        slug = project["slug"]
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in slugs:
            raise ValueError(f"Invalid or duplicate slug: {slug}")
        slugs.add(slug)
        for field in REQUIRED - {"tags", "images", "links"}:
            if not isinstance(project[field], str) or (field != "year" and not project[field].strip()):
                raise ValueError(f"{slug}: {field} must be a string, and only year may be empty.")
        graphic = project["graphic"]
        icon_path = (ROOT / graphic).resolve()
        if not graphic.startswith("assets/icons/") or icon_path.suffix != ".svg" or not icon_path.is_relative_to(ROOT / "assets/icons") or not icon_path.is_file():
            raise ValueError(f"{slug}: graphic must be a local SVG inside assets/icons/.")
        if not isinstance(project.get("note", ""), str):
            raise ValueError(f"{slug}: note must be plain text.")
        if not project["tags"] or not set(project["tags"]).issubset(TAGS):
            raise ValueError(f"{slug}: use only {sorted(TAGS)} for tags.")
        if not isinstance(project["links"], list) or not isinstance(project["images"], list):
            raise ValueError(f"{slug}: links and images must be arrays.")
        for link in project["links"]:
            if not link.get("label") or not isinstance(link.get("url"), str):
                raise ValueError(f"{slug}: links need a label and URL (or empty URL).")
            url = link["url"]
            if url and (urlsplit(url).scheme != "https" or not urlsplit(url).netloc):
                raise ValueError(f"{slug}: project links must be full HTTPS URLs.")
        for image in project["images"]:
            src = image.get("src", "")
            local_path = (ROOT / src).resolve()
            if not src.startswith("assets/") or not local_path.is_relative_to(ROOT / "assets") or not local_path.is_file():
                raise ValueError(f"{slug}: image must exist inside assets/: {src}")
            if not image.get("alt") or not all(isinstance(image.get(key), int) and image[key] > 0 for key in ("width", "height")):
                raise ValueError(f"{slug}: images need alt text and positive integer dimensions.")
    return projects


def figure(image, eager=False):
    loading = "eager" if eager else "lazy"
    return (
        '<figure class="case-figure">'
        f'<img src="../{escape(image["src"])}" alt="{escape(image["alt"])}" '
        f'width="{image["width"]}" height="{image["height"]}" loading="{loading}" decoding="async">'
        f'<figcaption>{escape(image.get("caption", ""))}</figcaption></figure>'
    )


def site_meta(site_url, path, include_preview=True):
    metadata = []
    if site_url:
        url = escape(f"{site_url}/{path}")
        metadata.extend((
            f'<link rel="canonical" href="{url}">',
            f'<meta property="og:url" content="{url}">',
        ))
    if include_preview:
        metadata.extend((
            f'<meta property="og:image" content="{escape(SOCIAL_IMAGE)}">',
            f'<meta name="twitter:image" content="{escape(SOCIAL_IMAGE)}">',
            '<meta name="twitter:card" content="summary_large_image">',
        ))
    return "\n  ".join(metadata)


def generate(site_url=None):
    projects = load_projects()
    # Preserve the deployment URL on subsequent plain runs.
    if not site_url and (ROOT / "sitemap.xml").exists():
        match = re.search(r"<loc>(https://[^<]+?)/index\.html</loc>", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))
        if match and match[1] != "https://example.com":
            site_url = html.unescape(match[1])
    template = Template((ROOT / "templates/project.html").read_text(encoding="utf-8"))
    output = ROOT / "projects"
    output.mkdir(exist_ok=True)
    for number, project in enumerate(projects, start=1):
        values = {key: escape(project[key]) for key in REQUIRED - {"tags", "links", "images"}}
        images = project["images"]
        links = []
        for link in project["links"]:
            if link["url"]:
                links.append(f'<li><a class="text-link" href="{escape(link["url"])}">{escape(link["label"])} <span aria-hidden="true">↗</span></a></li>')
            else:
                links.append(f'<li class="note">{escape(link.get("todo", "TODO: Add " + link["label"] + " URL."))}</li>')
        values.update(
            number=f"{number:02d}",
            tags="".join(f'<span class="tag">{escape(tag)}</span>' for tag in project["tags"]),
            hero_image=figure(images[0], eager=True) if images else "",
            extra_images=('<div class="case-gallery">\n' + "\n".join(figure(image) for image in images[1:]) + "\n</div>") if len(images) > 1 else "",
            links="\n".join(links) or '<li>No public project links yet.</li>',
            year_fact=f'<div><dt class="label">Year</dt><dd>{escape(project["year"])}</dd></div>' if project["year"].strip() else "",
            project_note=f'<p class="note">{escape(project["note"])}</p>' if project.get("note") else "",
            site_meta=site_meta(site_url, f'projects/{project["slug"]}.html', include_preview=False),
        )
        rendered = "\n".join(line.rstrip() for line in template.substitute(values).splitlines()) + "\n"
        (output / f'{project["slug"]}.html').write_text(rendered, encoding="utf-8", newline="\n")

    # Keep the no-JavaScript index in sync with the same source of truth.
    index_path = ROOT / "projects.html"
    index = index_path.read_text(encoding="utf-8")
    entries = "\n".join(f'              <li><a href="projects/{p["slug"]}.html">{escape(p["title"])}</a></li>' for p in projects)
    replacement = f"<!-- PROJECT_INDEX_START -->\n            <ul>\n{entries}\n            </ul>\n            <!-- PROJECT_INDEX_END -->"
    index, count = re.subn(r"<!-- PROJECT_INDEX_START -->.*?<!-- PROJECT_INDEX_END -->", lambda _: replacement, index, flags=re.S)
    if count != 1:
        raise ValueError("projects.html must contain exactly one generated project-index marker.")
    index_path.write_text(index, encoding="utf-8", newline="\n")

    base = site_url or "https://example.com"
    pages = ["index.html", "experience.html", "projects.html", "contact.html"]
    paths = pages + [f'projects/{p["slug"]}.html' for p in projects]
    urls = "\n".join(f"  <url><loc>{escape(base + '/' + path)}</loc></url>" for path in paths)
    sitemap_comment = "Generated by tools/generate.py." if site_url else "TODO: Set the final domain with tools/generate.py before publishing."
    robots_comment = "Generated by tools/generate.py" if site_url else "TODO: Set your real domain with tools/generate.py --site-url"
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!-- {sitemap_comment} -->\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
        encoding="utf-8", newline="\n",
    )
    (ROOT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /templates/\nDisallow: /tools/\n\n"
        f"# {robots_comment}\nSitemap: {base}/sitemap.xml\n",
        encoding="utf-8", newline="\n",
    )
    if site_url:
        for page in pages:
            path = ROOT / page
            content = path.read_text(encoding="utf-8")
            marker = f"<!-- SITE_META_START -->\n  {site_meta(site_url, page)}\n  <!-- SITE_META_END -->"
            if "<!-- SITE_META_START -->" in content:
                content = re.sub(r"<!-- SITE_META_START -->.*?<!-- SITE_META_END -->", lambda _: marker, content, flags=re.S)
            else:
                content = content.replace("</head>", "  " + marker + "\n</head>", 1)
            path.write_text(content, encoding="utf-8", newline="\n")
    print(f"Generated {len(projects)} project pages, the accessible index, sitemap.xml, and robots.txt.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-url", help="Your full HTTPS site URL, including a GitHub Pages subdirectory if needed.")
    args = parser.parse_args()
    if args.site_url:
        args.site_url = args.site_url.rstrip("/")
        parsed = urlsplit(args.site_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
            parser.error("--site-url must be a public HTTPS URL without credentials, query, or fragment.")
    generate(args.site_url)
