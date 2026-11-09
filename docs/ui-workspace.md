# ICPAC workspace design

The job of the working interface is to carry a forecaster from evidence to a reviewed
draft while preserving the selected forecast week and the distinction between products.
The public overview retains its map, country outlook and ICPAC identity.

## Free template selection

| Reference | Fit here |
| --- | --- |
| [shadcn/ui dashboard-01 and sidebar blocks](https://ui.shadcn.com/blocks/dashboard) | Selected: free MIT React/Next.js layout patterns, compact navigation, inset content, accessible primitives. The useful structure is rebuilt in the existing components and tokens. |
| [TailAdmin Next.js free template](https://github.com/TailAdmin/free-nextjs-admin-dashboard) | Relevant Next.js alternative, but importing its complete application would duplicate the existing routing, components and chart system. |
| [Tabler](https://github.com/tabler/tabler) | Strong data-dashboard reference with dark/RTL support; its Bootstrap stack would introduce another styling system here. |

This is a best fit for this repository, not a universal benchmark of every template.
No paid template, external design service, new router, Bootstrap dependency or second
chart library is introduced. See `frontend/THIRD_PARTY_NOTICES.md` for attribution.

## Design contract

* Working pages use an inset workflow rail: data → forecast → verification → maps →
  member states → bulletin. Separate links lead to automation, execution, registry,
  Copilot and service monitoring. All links resolve to existing registered routes.
* Forecast, map, country and bulletin links carry the selected package ID. Country
  cards, comparison tables and country-to-country links preserve it. Copilot's bulletin
  link uses the conversation's selected week. Verification remains an aggregate view.
* The rail shows the actual forecast period and available layers; it does not claim
  an unavailable hybrid is produced. The header retains shared language, theme, search
  and service status. Access controls and review transitions keep their existing logic.
* At widths below 1200 px, the rail becomes an internally scrolling workflow strip.
  Main content follows the existing responsive layouts; the document must not overflow.
  Arabic uses logical borders and the active indicator follows the writing direction.
* Native links/buttons, visible focus, named navigation landmarks, skip-to-content,
  clear pending/error states and meaningful source dates remain part of acceptance.
* Reject invented activity counts, decorative weather numbers, new scientific claims,
  generic sales copy, oversized empty cards and replacement of unavailable products.

Visual checks cover desktop, tablet, mobile, dark mode and Arabic. Automated layout
checks supplement manual screenshot inspection; neither establishes full WCAG compliance.
There is no approved pixel baseline for the new rail, so visual regression comparison
is inconclusive until these reviewed screenshots become a baseline.
