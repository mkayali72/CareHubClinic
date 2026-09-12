(function () {
  "use strict";

  const root = document.documentElement;
  const body = document.body;
  const menu = document.getElementById("mobile-sidebar");
  const backdrop = document.getElementById("mobile-menu-backdrop");
  const menuButton = document.querySelector("[data-mobile-menu-open]");
  const closeButton = document.querySelector("[data-mobile-menu-close]");

  function preference(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (error) {
      return fallback;
    }
  }

  function savePreference(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      // Preferences are an enhancement; the application remains usable without storage.
    }
  }

  function applyTheme(value) {
    root.dataset.theme = value;
    savePreference("obgyn-theme", value);
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const dark = value === "dark";
      button.setAttribute("aria-pressed", String(dark));
      button.querySelector("[data-theme-label]")?.replaceChildren(document.createTextNode(dark ? "Light" : "Dark"));
      button.title = dark ? "Switch to light mode" : "Switch to dark mode";
    });
  }

  function applyFontSize(value) {
    root.dataset.fontSize = value;
    savePreference("obgyn-font-size", value);
    document.querySelectorAll("[data-font-size]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.fontSize === value));
    });
  }

  function applyContrast(value) {
    root.dataset.contrast = value;
    savePreference("obgyn-contrast", value);
    document.querySelectorAll("[data-contrast-toggle]").forEach((button) => {
      const enabled = value === "high";
      button.setAttribute("aria-pressed", String(enabled));
      button.querySelector("[data-contrast-label]")?.replaceChildren(document.createTextNode(enabled ? "Standard" : "Contrast"));
      button.title = enabled ? "Use standard contrast" : "Use high contrast";
    });
  }

  function openMenu() {
    if (!menu || !backdrop) return;
    backdrop.hidden = false;
    menu.dataset.open = "true";
    menu.setAttribute("aria-hidden", "false");
    backdrop.dataset.open = "true";
    body.classList.add("menu-open");
    menuButton?.setAttribute("aria-expanded", "true");
    closeButton?.focus();
  }

  function closeMenu() {
    if (!menu || !backdrop) return;
    menu.dataset.open = "false";
    menu.setAttribute("aria-hidden", "true");
    backdrop.dataset.open = "false";
    body.classList.remove("menu-open");
    menuButton?.setAttribute("aria-expanded", "false");
    window.setTimeout(() => {
      if (menu.dataset.open !== "true") backdrop.hidden = true;
    }, 180);
    menuButton?.focus();
  }

  applyTheme(preference("obgyn-theme", root.dataset.theme || "light"));
  applyFontSize(preference("obgyn-font-size", root.dataset.fontSize || "normal"));
  applyContrast(preference("obgyn-contrast", root.dataset.contrast || "standard"));

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => applyTheme(root.dataset.theme === "dark" ? "light" : "dark"));
  });
  document.querySelectorAll("[data-font-size]").forEach((button) => {
    button.addEventListener("click", () => applyFontSize(button.dataset.fontSize));
  });
  document.querySelectorAll("[data-contrast-toggle]").forEach((button) => {
    button.addEventListener("click", () => applyContrast(root.dataset.contrast === "high" ? "standard" : "high"));
  });

  menuButton?.addEventListener("click", openMenu);
  closeButton?.addEventListener("click", closeMenu);
  backdrop?.addEventListener("click", closeMenu);
  menu?.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu?.dataset.open === "true") closeMenu();
  });
})();