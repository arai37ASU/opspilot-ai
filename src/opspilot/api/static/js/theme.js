// Light and dark mode. With no saved choice the page follows the system
// setting; the toggle saves an explicit choice in localStorage.

const KEY = "opspilot-theme";
const listeners = new Set();

export function currentTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Charts read colours from CSS variables, so they redraw when the theme changes.
export function onThemeChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function apply(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(KEY, theme); } catch (error) { /* storage unavailable: still applied */ }
  listeners.forEach((callback) => callback(theme));
}

export function initThemeToggle(button) {
  button.addEventListener("click", () => apply(currentTheme() === "dark" ? "light" : "dark"));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.dataset.theme) listeners.forEach((callback) => callback(currentTheme()));
  });
}
