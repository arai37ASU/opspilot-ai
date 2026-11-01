import { renderPlaceholder } from "./placeholder.js";

export function render(container) {
  renderPlaceholder(container, {
    title: "Incident radar",
    description: "Two years of daily volume, with unusual bursts of the same issue.",
    step: "F",
    features: [
      "A calendar heatmap of daily tickets",
      "Click a day to see its spikes",
      "Major incidents separated from semester surges",
    ],
  });
}
