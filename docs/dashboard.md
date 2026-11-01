# OpsPilot dashboard

A web dashboard for the service desk, served by the API at http://localhost:8000. It is plain HTML, CSS and JavaScript with no build step, in `src/opspilot/api/static/`. Run it the same way as the API; see [api.md](api.md).

The data is synthetic, so the numbers show what the system can do and are not facts about a real organization.

## Pages

| Page | Question it answers | Main endpoints |
|---|---|---|
| Overview | How is the desk doing in any period? | `/metrics/overview`, `/metrics/trend`, `/metrics/daily` |
| Risk simulator | How likely is this ticket to miss its SLA, why, and how does that change with the time it arrives? | `/predictions`, `/predictions/batch`, `/reference` |
| Teams | Which teams are under pressure, and on what measure? | `/metrics/teams` |
| Ticket lookup | What did the model predict for a past ticket, and was it right? | `/tickets/{id}/risk`, `/model/evaluation` |
| Incident radar | Which days had unusual bursts, and were they incidents or seasonal? | `/metrics/daily`, `/metrics/spikes` |
| The model | How good is the model, and where does it fall short? | `/model/evaluation` |

Filtered views keep their state in the link (for example `#/teams?start=2025-09-01&end=2025-12-31`), so any view can be shared.

## Design decisions

**A custom site rather than Streamlit.** Streamlit would have been faster to build, but interactions such as dragging the time slider, clicking through linked charts and sharing a filtered link needed more control than it gives. The cost is more front-end code to maintain.

**No front-end framework or build step.** Six pages with small amounts of state do not need one. The code is ES modules loaded directly by the browser, so there is nothing to compile and the Docker image needs no Node.js.

**Served by the API.** One origin means no cross-origin setup and one thing to deploy.

**The browser calculates nothing.** Every number comes from the API, and classification rules such as which bursts are suspected incidents live in tested Python and SQL. Other clients, including the planned AI layer, get the same answers.

**ECharts is vendored.** The library is a file in the repository with a recorded checksum that a test verifies, so the site does not depend on a CDN being available.

**API text is never parsed as HTML.** Pages are built with text nodes through one helper, a test forbids `innerHTML`, and values placed in chart tooltips are escaped.

**Files are rechecked, not re-downloaded.** Static files are sent with `Cache-Control: no-cache`, so a browser never runs old JavaScript after a deploy. An unchanged file costs a small 304 response.

## Chart rules

- One y-axis per chart. Volume and breach rate are two aligned charts, because a dual axis would suggest a relationship the data does not show.
- One series gets one colour and no legend; the title names it. Two series differ in more than colour, as with solid precision and dashed recall.
- Risk colours were checked with a colour-vision validator in both themes, and flags always come with words.
- Every chart has the same values in a table, so nothing is reachable only by hovering.
- Anything that could mislead says so on the page: the falling breach rate in the last 14 days, scores for tickets in the training data, and the blind spots of the incident rule.

## Tests

`tests/test_web.py` checks that the site is served correctly and stays in step with the rest of the project: every API path the front end calls exists in the API, every page module and asset exists, every model feature has a plain-language label, and the vendored library matches its checksum.

The page behaviour itself (clicks, sorting, the slider) was checked by hand in a browser at phone, tablet and desktop widths, in both themes. There are no automated browser tests.

## Limitations

- Agent counts are today's headcount, because past staffing is not recorded. The Teams page says so and shows no tickets-per-agent figure for past periods.
- The incident rule was chosen after seeing the 24 spike days, so finding the four planted incidents is not independent proof. Two outages of the same kind would count as recurring, and a seasonal surge looks like an incident the first time it happens.
- The simulator scores tickets only inside the period covered by the data, because the queue features are computed from stored tickets.
- There is no sign-in. The dashboard is for local use and must not be exposed as it stands.
