// Plain-language names and value formatting for the model's features, so the
// simulator and the ticket lookup explain predictions the same way.

import { formatHours, formatInteger, formatPercent } from "./format.js";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const FEATURES = {
  priority: { label: "Priority" },
  subcategory: { label: "Issue", format: (v) => humanize(v) },
  assigned_team: { label: "Assigned team" },
  academic_period: { label: "Academic period", format: (v) => humanize(v) },
  requester_type: { label: "Requester", format: (v) => humanize(v) },
  channel: { label: "Channel", format: (v) => humanize(v) },
  sla_hours: { label: "SLA target", format: formatHours },
  hours_until_staffed: { label: "Hours until the team is next staffed", format: formatHours },
  hour_of_day: { label: "Hour of day", format: (v) => `${String(Math.floor(v)).padStart(2, "0")}:00` },
  day_of_week: { label: "Day of week", format: (v) => DAYS[v - 1] ?? String(v) },  // ISO: 1 = Monday
  is_weekend: { label: "Weekend", format: yesNo },
  is_holiday: { label: "Holiday", format: yesNo },
  team_open_per_agent: { label: "Team's open tickets per agent", format: (v) => v.toFixed(1) },
  subcategory_arrivals_prev_2h: { label: "Similar tickets in the last 2 hours", format: formatInteger },
  subcategory_arrivals_prev_24h: { label: "Similar tickets in the last 24 hours", format: formatInteger },
  team_breach_rate_prev_30d: { label: "Team's breach rate, last 30 days", format: (v) => formatPercent(v * 100) },
  team_resolved_prev_30d: { label: "Team's resolved tickets, last 30 days", format: formatInteger },
  subcategory_breach_rate_prev_90d: { label: "Issue's breach rate, last 90 days", format: (v) => formatPercent(v * 100) },
  subcategory_resolved_prev_90d: { label: "Issue's resolved tickets, last 90 days", format: formatInteger },
};

function yesNo(value) {
  return value ? "Yes" : "No";
}

// "projector_display" -> "Projector display"
export function humanize(value) {
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function featureLabel(name) {
  return FEATURES[name]?.label ?? humanize(name);
}

// A missing history rate (no resolved tickets in the window) arrives as null.
export function featureValue(name, value) {
  if (value === null || value === undefined) return "No history";
  const format = FEATURES[name]?.format;
  return format ? format(value) : String(value);
}
