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

  function requestId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `request-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function setSubmissionState(form, state, message) {
    const button = form?.querySelector("[data-submit-button]");
    const status = form?.querySelector("[data-submit-status]");
    if (!form) return;
    if (state === "loading") {
      form.setAttribute("aria-busy", "true");
      if (button) button.disabled = true;
      if (status) {
        status.classList.remove("submit-error");
        status.textContent = message || "Saving…";
      }
    } else {
      form.removeAttribute("aria-busy");
      if (button) button.disabled = false;
      if (status && state === "error") {
        status.classList.add("submit-error");
        status.textContent = message || "Unable to save. Check your connection and try again.";
      }
    }
  }

  function filterInputValue(field) {
    if (!field || typeof field.value !== "string") return;
    if (field.dataset.inputFilter === "phone") {
      field.value = field.value
        .replace(/[^\d+ ()-]/g, "")
        .replace(/(?!^)\+/g, "");
      return;
    }
    if (field.dataset.inputFilter === "blood-pressure") {
      field.value = field.value.replace(/[^0-9/ ]/g, "");
      return;
    }
    if (field.type === "number") {
      const decimal = field.step && field.step !== "1";
      const cleaned = field.value.replace(/[^0-9.]/g, "");
      if (!decimal) {
        field.value = cleaned.replace(/\./g, "");
        return;
      }
      const firstDot = cleaned.indexOf(".");
      field.value = firstDot < 0
        ? cleaned
        : `${cleaned.slice(0, firstDot + 1)}${cleaned.slice(firstDot + 1).replace(/\./g, "")}`;
    }
  }

  function openMenu() {
    if (!menu || !backdrop) return;
    backdrop.hidden = false;
    menu.dataset.open = "true";
    menu.inert = false;
    menu.setAttribute("aria-hidden", "false");
    backdrop.dataset.open = "true";
    body.classList.add("menu-open");
    menuButton?.setAttribute("aria-expanded", "true");
    closeButton?.focus();
  }

  function closeMenu() {
    if (!menu || !backdrop) return;
    menu.dataset.open = "false";
    menu.inert = true;
    menu.setAttribute("aria-hidden", "true");
    backdrop.dataset.open = "false";
    body.classList.remove("menu-open");
    menuButton?.setAttribute("aria-expanded", "false");
    window.setTimeout(() => {
      if (menu.dataset.open !== "true") backdrop.hidden = true;
    }, 180);
    menuButton?.focus();
  }

  if (menu) menu.inert = true;
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

  document.querySelectorAll("[data-idempotency-form]").forEach((form) => {
    const field = form.querySelector("[data-idempotency-key]");
    if (field && !field.value) field.value = requestId();
  });

  document.addEventListener("input", (event) => {
    filterInputValue(event.target);
  });

  menuButton?.addEventListener("click", openMenu);
  closeButton?.addEventListener("click", closeMenu);
  backdrop?.addEventListener("click", closeMenu);
  menu?.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu?.dataset.open === "true") {
      closeMenu();
      return;
    }
    const dialog = document.querySelector(".mobile-slide-over[role='dialog']");
    if (event.key === "Escape" && dialog) {
      dialog.querySelector("button[aria-label='Close'], button")?.click();
      return;
    }
    if (event.key !== "Tab" || menu?.dataset.open !== "true") return;
    const focusable = [...menu.querySelectorAll("a, button, input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter((element) => !element.hasAttribute("disabled"));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  document.body.addEventListener("htmx:beforeRequest", (event) => {
    const form = event.detail.elt?.closest?.("form[data-idempotency-form]");
    setSubmissionState(form, "loading", "Saving…");
  });
  document.body.addEventListener("htmx:afterRequest", (event) => {
    const form = event.detail.elt?.closest?.("form[data-idempotency-form]");
    const status = event.detail.xhr?.status || 0;
    if (status >= 400) {
      setSubmissionState(form, "error", "Unable to save. Check your connection and try again.");
    } else {
      setSubmissionState(form, "done");
    }
  });
  document.body.addEventListener("htmx:sendError", (event) => {
    const form = event.detail.elt?.closest?.("form[data-idempotency-form]");
    setSubmissionState(form, "error", "Connection lost. Nothing was duplicated; try again.");
  });
  document.body.addEventListener("htmx:responseError", (event) => {
    const form = event.detail.elt?.closest?.("form[data-idempotency-form]");
    setSubmissionState(form, "error", "The server could not save this yet. Try again.");
  });
})();