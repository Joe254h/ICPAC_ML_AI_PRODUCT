# Redesign brief: ICPAC Week-2 Rainfall Outlook

This is the brief for the redesign of the web application before it is presented to ICPAC senior management. You can also give it, as written, to a designer or to an AI design tool.

---

## The prompt

You are the lead product designer for the IGAD Climate Prediction and Applications Centre (ICPAC). Redesign the ICPAC Week-2 Rainfall Outlook web application so that it can be presented to ICPAC's senior management (Director General, heads of climate services, partners and donors) and then used every day by forecasters. Keep every working feature. Change how the application is organised, what it shows first and how it looks.

### What the application is

- Every week it downloads the ECMWF ensemble and corrects it in two steps:
  - MBC, a multiplicative bias correction;
  - a machine-learning residual correction (CatBoost).
- It issues a days 8–14 rainfall outlook for the eleven member states: Burundi, Djibouti, Eritrea, Ethiopia, Kenya, Rwanda, Somalia, South Sudan, Sudan, Tanzania and Uganda. The grid is 0.05 degrees, about 5 km.
- It drafts the weekly bulletin in ICPAC's template. Forecasters review and approve it.
- It verifies each forecast against CHIRPS once the week has been observed.
- It monitors observed rainfall from five satellite estimates.
- It has a Copilot that answers questions from the forecast, edits the bulletin on request and compares other models' forecasts.

### The story management must take away in two minutes

1. **This week's outlook, in one look.** A map of the region and one plain sentence about where rain is expected.
2. **It is more accurate than what we had.** On an independent 2022–2024 test the corrected forecast has lower error than raw ECMWF. Show the figure from the verification data, never a typed number.
3. **It runs itself, and people stay in charge.** Every step is automatic and recorded: data → forecast → bulletin draft → human approval → verification.
4. **It serves the member states.** Each country gets its own figures, map and bulletin text.
5. **AI helps the forecaster.** The Copilot explains the forecast and redrafts the bulletin in ICPAC's voice. A person approves every release.

### Principles

- **Natural and calm.** Use the earth and vegetation colours of the region: deep forest green, warm sand neutrals, rain-blue only in the rainfall data and amber for attention. Use warm off-white page backgrounds instead of cold grey. Leave generous space. No gradients and no decorative illustrations. The map is the image.
- **Plain, human language.** Use short sentences with real verbs. Name dates, places and amounts. No jargon in headings: say "Accuracy" before "RMSE". Explain technical terms in one line where they appear. No hype words (revolutionary, cutting-edge, AI-powered), no exclamation marks, no emojis.
- **Show only what helps a decision.** Each page answers one question. Technical detail (grids, lead hours, input checks, model identifiers) moves into a "How this forecast was made" section, collapsed by default, at the end of the page. Nothing is deleted.
- **Honest states.** If something is not ready (the AI/ML layer waiting for upper-air data, a week not yet observed), say so plainly and say when it will be ready. Never fill a gap with sample data.
- **Institutional.** Show the IGAD seal and the ICPAC name, as on icpac.net. It should look like part of ICPAC, not a start-up.

### Information architecture

A single white header on every page:
- **Left:** the IGAD seal, "ICPAC" and the product name "Week-2 Rainfall Outlook".
- **Centre:** six destinations:
  - **Forecast:** this week's forecast, rainfall maps, forecast archive.
  - **Countries:** one page with all eleven member states. Each opens its own page.
  - **Bulletin:** this week's bulletin, drafts and review.
  - **Verification:** live verification, the independent 2022–2024 test, error and skill maps.
  - **Monitoring:** observed rainfall.
  - **Copilot**.
- **Right:**
  - search (press "/");
  - a service-status dot;
  - a quieter **Operations** menu for staff: run the weekly cycle, automation, data sources, model registry, system status;
  - staff sign-in.

Older URLs must keep working. The single forecast layers (raw ECMWF, MBC, MBC + AI/ML), the individual data sources and the countries stay reachable from their pages and from search, not from the header.

On phones, the header becomes the seal and the product name, with search and a menu button. The menu opens as a full-height panel with the same groups.

### The home page, in order

1. **The outlook.** A full-width map of this week's forecast. Beside it on wide screens (over it on phones):
   - the week ("2–8 November 2026");
   - the bulletin's headline sentence;
   - the run it came from;
   - a small switch between raw ECMWF, MBC and MBC + AI/ML;
   - two actions: "Explore the forecast" and "Read the bulletin".
2. **Four key figures:** regional mean, wettest country, highest local total, verification state.
3. **"Why it can be trusted"**, three proof points from live data:
   - **Accuracy:** lower error than raw ECMWF on the independent test, with the number of cases.
   - **Automation:** every step runs on a schedule and is recorded.
   - **Verification:** each week is scored against CHIRPS once it has been observed.
   Each has one link to its evidence.
4. **Country outlook:** eleven cards, wettest first.
5. **This week's bulletin:** the rainfall statements and the bulletin map, with "Read the bulletin".
6. **How each week's forecast is made:** six steps, each with its live state: ECMWF ensemble, forecast, bulletin, observed rainfall, verification, AI/ML layer.

The observed-rainfall section moves to the Monitoring page. The home page links to it from step 6.

### Inner pages

- **Every page header:** breadcrumb, a title of a few words, one sentence on what the page is for, short facts as quiet pills, and at most two actions.
- **Forecast:** the staff confirmation notice (when needed), map, bulletin statements, country table and chart. The forecast products, notes, details and "how it was made" go into one collapsed "How this forecast was made" section at the end.
- **Verification:** start with the answer in one sentence, for example "On 551 independent weeks from 2022 to 2024, the corrected forecast had 12% lower error than raw ECMWF". The table follows.
- **Copilot:** keep it as it is. It already reads like a modern chat.

### Visual system

- **Type:** Inter, with tabular figures in tables and key figures.
  - Page titles 30–34 px, semibold 650 to 700, tight tracking.
  - Section titles 22–24 px.
  - Body text 15.5 px, line height 1.6.
  - Small labels 12–13 px in sentence case; uppercase only for short eyebrows.
- **Colour:**
  - Forest green #0d462d (brand), #125d3b (actions).
  - Warm ground #f6f5f1, hairlines #e5e2da, ink #17211b, text #3b4540, muted #6b736d.
  - Amber #e5a10f only for attention and the active state.
  - The rainfall palette stays exactly as ICPAC's bulletin.
- **Surfaces:** white cards, 12 px radius, a 1 px warm hairline and a very soft shadow. No coloured card backgrounds except for notices.
- **Motion:** none beyond hover and focus states. Menus open on click and close with Escape.
- **Accessibility:**
  - WCAG AA contrast.
  - Visible focus.
  - Every map has an accessible name.
  - The layout works from 360 px wide with no horizontal scroll.

### What to remove or hide

- Header dropdowns longer than six items: the eleven countries and the six data sources.
- Duplicated links. The footer keeps only the ICPAC organisation links and the data credits.
- Technical facts at the top of pages.
- The separate maps menu. Rainfall maps belong to Forecast; error and skill maps belong to Verification.

### Acceptance

- At 1440 px, the home page shows the outlook, its headline and the key figures without scrolling.
- At 390 px, nothing scrolls sideways.
- Every page has one h1 that names it.
- Nothing shows code, IDs, hashes or configuration keys.
- All existing tests pass, and those changed by the new navigation are updated.
