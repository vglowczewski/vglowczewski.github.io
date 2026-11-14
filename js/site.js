/* Public contact details. Keep contact.html's no-JavaScript links in sync. */
const CONTACT = {
  email: "vanessaglowczewski@gmail.com",
  linkedin: "https://www.linkedin.com/in/vanessa-glowczewski/",
  github: "https://github.com/vglowczewski/",
  instagram: "https://www.instagram.com/nibblingnessa/",
  notion: "https://app.notion.com/p/Vanessa-Glowczewski-4079a6324ded8008bd41fe78583d4305",
};

/* Section emojis live here; project emojis live in data/projects.json. */
const EMOJI = { featured: "📌", about: "👋", projects: "🗂️", contact: "✉️" };
document.querySelectorAll("[data-emoji]").forEach((element) => {
  element.textContent = EMOJI[element.dataset.emoji] || "";
});

document.querySelectorAll("[data-contact]").forEach((element) => {
  const kind = element.dataset.contact;
  const value = CONTACT[kind];
  if (!value) return;
  element.href = kind === "email" ? `mailto:${value}` : value;
  const valueElement = element.querySelector("[data-contact-value]");
  if (valueElement && kind === "email") {
    valueElement.textContent = value;
  }
});
