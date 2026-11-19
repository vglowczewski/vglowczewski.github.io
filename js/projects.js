const root = new URL("../", import.meta.url);
const grid = document.querySelector("[data-project-grid]");
const status = document.querySelector("[data-project-status]");
const filters = document.querySelector("[data-project-filters]");

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function projectCard(project, index) {
  const article = node("article", "project-card");
  article.dataset.tags = project.tags.join("|");
  const thumb = node("div", "project-thumb");
  const image = project.images[0];
  if (image) {
    const img = document.createElement("img");
    img.src = new URL(image.src, root);
    img.alt = image.alt;
    img.width = image.width;
    img.height = image.height;
    img.loading = "lazy";
    img.decoding = "async";
    thumb.append(img);
  } else {
    thumb.classList.add("is-placeholder");
    const placeholder = node("span", "project-placeholder");
    placeholder.setAttribute("aria-hidden", "true");
    thumb.append(placeholder);
  }
  const frame = node("span", "frame-number", `► ${String(index + 1).padStart(2, "0")}A`);
  frame.setAttribute("aria-hidden", "true");
  thumb.append(frame);
  const info = node("div", "project-info");
  const meta = node("div", "project-meta");
  meta.append(node("span", "label", `PROJECT / ${String(index + 1).padStart(2, "0")}`));
  const heading = node("h3");
  const link = node("a", "", project.title);
  link.href = new URL(`projects/${encodeURIComponent(project.slug)}.html`, root);
  const arrow = node("span", "arrow", "↗");
  arrow.setAttribute("aria-hidden", "true");
  link.append(arrow);
  heading.append(link);
  const tags = node("div", "tags");
  project.tags.forEach((tag) => tags.append(node("span", "tag", tag)));
  info.append(meta, heading, node("p", "", project.summary), tags);
  article.append(thumb, info);
  return article;
}

async function loadProjects() {
  if (!grid) return;
  try {
    const response = await fetch(new URL("data/projects.json", root));
    if (!response.ok) throw new Error("Project data could not be loaded.");
    const projects = await response.json();
    const limit = Number(grid.dataset.limit) || projects.length;
    const selected = projects.slice(0, limit);
    const cards = selected.map(projectCard);
    grid.replaceChildren(...cards);
    grid.setAttribute("aria-busy", "false");
    if (status) status.textContent = `Showing all ${selected.length} projects`;
    if (filters) {
      filters.hidden = false;
      filters.addEventListener("click", (event) => {
        const button = event.target.closest("[data-filter]");
        if (!button || !filters.contains(button)) return;
        const filter = button.dataset.filter;
        filters.querySelectorAll("[data-filter]").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
        let count = 0;
        cards.forEach((card, index) => {
          const visible = filter === "All" || selected[index].tags.includes(filter);
          card.hidden = !visible;
          if (visible) count += 1;
        });
        status.textContent = filter === "All"
          ? `Showing all ${count} projects`
          : `Showing ${count} ${filter} project${count === 1 ? "" : "s"}`;
      });
    }
  } catch {
    grid.setAttribute("aria-busy", "false");
    const error = node("p", "load-error", "Projects could not load. Please try again, or visit ");
    const link = node("a", "", "the contact page");
    link.href = new URL("contact.html", root);
    error.append(link, document.createTextNode(". If you opened a file directly, please use a local server (see README)."));
    grid.replaceChildren(error);
    if (status) status.textContent = "Project data unavailable.";
  }
}

loadProjects();
