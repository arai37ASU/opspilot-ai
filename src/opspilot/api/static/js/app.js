// Entry point: navigation between pages, the theme toggle, and the API
// status pill. Pages live in ./pages and each exports
// render(container, params), which may return a cleanup function.
//
// Routing uses the URL hash (#/overview), so every page has a shareable link
// and the server only ever serves one HTML file.

import { el, replaceChildren } from "./dom.js";
import { initThemeToggle } from "./theme.js";
import { initStatus } from "./status.js";
import * as overview from "./pages/overview.js";
import * as simulator from "./pages/simulator.js";
import * as teams from "./pages/teams.js";
import * as tickets from "./pages/tickets.js";
import * as incidents from "./pages/incidents.js";
import * as model from "./pages/model.js";

const PAGES = {
  overview: { label: "Overview", module: overview },
  simulator: { label: "Risk simulator", module: simulator },
  teams: { label: "Teams", module: teams },
  tickets: { label: "Ticket lookup", module: tickets },
  incidents: { label: "Incident radar", module: incidents },
  model: { label: "The model", module: model },
};
const DEFAULT_PAGE = "overview";

let cleanupCurrentPage = null;

function buildNav(list) {
  replaceChildren(list, Object.entries(PAGES).map(([name, page]) =>
    el("li", {}, el("a", { href: `#/${name}`, dataset: { page: name } }, page.label))));
}

// "#/overview?start=2025-09-01" -> page "overview" with its query parameters,
// so a filtered view can be shared as a link.
function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return { name: path || DEFAULT_PAGE, params: new URLSearchParams(query) };
}

async function showPage(main, nav) {
  const { name, params } = parseHash();
  const page = PAGES[name];
  if (!page) {
    location.replace(`#/${DEFAULT_PAGE}`);
    return;
  }

  for (const link of nav.querySelectorAll("a")) {
    if (link.dataset.page === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${page.label} · OpsPilot Control Room`;

  if (cleanupCurrentPage) cleanupCurrentPage();
  cleanupCurrentPage = null;
  main.replaceChildren();
  cleanupCurrentPage = (await page.module.render(main, params)) ?? null;

  // Move focus to the new heading so keyboard and screen-reader users land on the page.
  main.querySelector("h1")?.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

function start() {
  const main = document.getElementById("main");
  const nav = document.getElementById("nav-links");
  buildNav(nav);
  initThemeToggle(document.getElementById("theme-toggle"));
  initStatus(document.getElementById("api-status"));
  window.addEventListener("hashchange", () => showPage(main, nav));
  showPage(main, nav);
}

start();
