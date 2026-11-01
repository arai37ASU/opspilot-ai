// Calls to the OpsPilot API. The page is served from the same origin, so
// paths are relative and no cross-origin setup is needed.

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : `request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" }, ...options });
  } catch (error) {
    throw new ApiError(0, "The API could not be reached.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? response.statusText);
  return body;
}

export function getJSON(path) {
  return request(path);
}

export function postJSON(path, data) {
  return request(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
