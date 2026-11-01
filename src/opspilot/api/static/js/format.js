// Number and date formatting, so every page shows values the same way.

const MISSING = "—";
const integerFormat = new Intl.NumberFormat("en-US");
const compactFormat = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const formatInteger = (value) => (value == null ? MISSING : integerFormat.format(value));
export const formatCompact = (value) => (value == null ? MISSING : compactFormat.format(value));
export const formatPercent = (value, digits = 1) => (value == null ? MISSING : `${value.toFixed(digits)}%`);
export const formatHours = (value) => (value == null ? MISSING : `${value.toFixed(1)} h`);
export const formatScore = (value) => (value == null ? MISSING : value.toFixed(2));

// Dates arrive as "YYYY-MM-DD"; parsing at local midnight keeps the calendar day.
const asLocalDate = (iso) => new Date(`${iso}T00:00:00`);
export const formatDay = (iso) => asLocalDate(iso).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
export const formatShortDay = (iso) => asLocalDate(iso).toLocaleDateString("en-US", { day: "numeric", month: "short" });
export const formatMonth = (iso) => asLocalDate(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });

// Tickets created this close to the end of the data that were heading for a
// breach were mostly still open at the snapshot, so recent rates read too low.
export const CENSORING_DAYS = 14;

export function daysBetween(startIso, endIso) {
  return Math.round((asLocalDate(endIso) - asLocalDate(startIso)) / 86_400_000) + 1;
}
