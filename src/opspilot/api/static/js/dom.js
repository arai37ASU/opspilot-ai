// Small helpers for building the page.
//
// el() only ever inserts text with document.createTextNode, never HTML
// strings, so values that come from the API (ticket ids, subcategory names)
// cannot be interpreted as markup or scripts.

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function replaceChildren(node, ...children) {
  node.replaceChildren();
  append(node, children);
}

export function pageHeader(title, description) {
  return el("header", { class: "page-header" },
    el("h1", { tabindex: "-1" }, title),
    description && el("p", {}, description));
}
