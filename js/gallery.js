const root = new URL("../", import.meta.url);
const grid = document.querySelector("[data-gallery-grid]");
const filters = document.querySelector("[data-gallery-filters]");
const status = document.querySelector("[data-gallery-status]");

function galleryCard(photo) {
  const figure = document.createElement("figure");
  figure.className = "gallery-card";
  figure.dataset.category = photo.category;
  const link = document.createElement("a");
  link.className = "gallery-photo";
  link.href = new URL(`assets/images/gallery/${encodeURIComponent(photo.file.replace(/\.webp$/, "-full.webp"))}`, root);
  const img = document.createElement("img");
  img.src = new URL(`assets/images/gallery/${encodeURIComponent(photo.file)}`, root);
  img.alt = photo.alt;
  img.width = photo.width;
  img.height = photo.height;
  img.loading = "lazy";
  img.decoding = "async";
  img.style.objectPosition = photo.focus || "center";
  link.append(img);
  const caption = document.createElement("figcaption");
  caption.className = "gallery-caption";
  caption.textContent = photo.caption;
  figure.append(link, caption);
  return figure;
}

async function loadGallery() {
  if (!grid) return;
  grid.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(new URL("data/gallery.json", root));
    if (!response.ok) throw new Error("Photo data unavailable.");
    const photos = await response.json();
    const cards = photos.map(galleryCard);
    grid.replaceChildren(...cards);
    const categories = [...new Set(photos.map(photo => photo.category))].sort();
    filters.replaceChildren();
    for (const category of ["all", ...categories]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "filter-button";
      button.dataset.category = category;
      button.textContent = category === "all" ? "All" : category.charAt(0).toUpperCase() + category.slice(1);
      button.setAttribute("aria-controls", "gallery-grid");
      button.setAttribute("aria-pressed", String(category === "all"));
      filters.append(button);
    }
    filters.hidden = categories.length <= 1;
    status.hidden = false;
    status.textContent = `Showing all ${photos.length} photos`;
    filters.addEventListener("click", event => {
      const button = event.target.closest("button[data-category]");
      if (!button || !filters.contains(button)) return;
      const category = button.dataset.category;
      let count = 0;
      cards.forEach(card => {
        card.hidden = category !== "all" && card.dataset.category !== category;
        if (!card.hidden) count += 1;
      });
      filters.querySelectorAll("button").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
      status.textContent = category === "all" ? `Showing all ${count} photos` : `Showing ${count} ${category} photo${count === 1 ? "" : "s"}`;
    });
  } catch {
    // Keep the generated all-photo grid, including on a network failure.
    status.hidden = false;
    status.textContent = "Filters are unavailable. All photos are shown below.";
    filters.hidden = true;
  } finally {
    grid.setAttribute("aria-busy", "false");
  }
}

loadGallery();
