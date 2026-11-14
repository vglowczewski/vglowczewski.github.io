/* Public contact details. Keep the HTML fallback links in sync. */
const CONTACT = {
  email: "vanessaglowczewski@gmail.com",
  linkedin: "https://www.linkedin.com/in/vanessa-glowczewski/",
  github: "https://github.com/vglowczewski/",
};

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
