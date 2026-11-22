---
name: bulletin-humanizer
description: Rewrite ICPAC weekly bulletin text, or a Copilot answer about the forecast, so it reads like a forecaster wrote it and not like AI output, keeping every figure, place and date exactly. Use when asked to humanize, de-AI, polish or make more natural the bulletin's headline, decision-support note, rainfall statements, country focus or a forecast answer, or when bulletin text "sounds like AI".
---

# Bulletin humanizer

ICPAC's weekly Week-2 bulletin goes to national meteorological services, farmers, water
managers and disaster officers. It must read like a forecaster wrote it: plain, direct,
specific to this week. This skill rewrites bulletin wording to that voice. It never changes
a figure.

## The one rule that overrides the rest

Every number, unit, range, date, place and country in the original stays exactly as
written (`50-200 mm`, `12.6 mm`, `15-21 November 2026`, `central to southern parts of
Kenya`). Add none. If a sentence needs a figure the text does not have, leave the sentence
without it. The forecast has no climatology: never write above or below normal, wetter or
drier than usual, or record.

## Keep the length

The humanized bulletin is no longer than the original: each paragraph at most about a third
longer than before (a short line may gain a few words), and shorter is better. The service
refuses AI-written paragraphs beyond that limit (`chatbot/bulletin_writer.py`,
`word_limit`). Cut filler before adding detail.

## How to work

1. Get the text. From a file the person gives, the Bulletin page's editor, or a draft's
   sections (`GET /api/bulletins/{id}`: `facts.sections[].text` for the keys `headline`,
   `decision_support`, `rainfall`, `focus`). Keep one paragraph per original paragraph: the
   Word template has one slot for each, and its maps sit between them.
2. Save the original to a scratch file (for example `original.txt`, paragraphs separated by
   an empty line).
3. Rewrite with the voice rules below.
4. Check it, and fix every line the checker prints:

   ```bash
   python -m scripts.check_bulletin_tone rewrite.txt --against original.txt
   ```

   The checker applies the same rules the service applies before it saves AI-written or
   Copilot-revised bulletin text (`chatbot/tone.py`), and confirms that no figure was
   dropped or added. Repeat until it prints `OK`.
5. Give back the rewrite paragraph by paragraph, and say in one line what changed. To save
   it as a new draft version, the forecaster pastes it into **Edit the text** on the
   Bulletin page (each section) or asks the Copilot to revise the bulletin with it.

## The voice

- Lead with what happens: where rain is concentrated, where it is light, what stands out.
  "Moderate rainfall (50-200 mm) is expected over central to southern Kenya", not "Kenya
  is expected to experience a range of rainfall conditions".
- Describe the pattern as a forecaster sees it: the contrast between highlands and
  lowlands, the Lake Victoria basin, the coast, the northern sector. Use only places the
  original names.
- Name the season when it helps (the October-December short rains or vuli in the equatorial
  sector, the March-May long rains or masika, Kiremt in Ethiopia's highlands, the single
  November-April season in central and southern Tanzania), without numbers.
- Say what to do, concretely: plant, prepare drainage, plan water use, watch river levels.
  "Farmers in these areas can plan planting", not "stakeholders should leverage the
  forecast".
- Likely, expected, may: never certain. One hedge per claim is enough.
- Simple verbs: is, are, has, expect. Vary sentence length. One idea per sentence.
- Plain text only: no markdown, bullets, bold or emojis inside the wording.

## Remove these (the checker flags most of them)

| Pattern | Instead |
|---|---|
| Inflated importance: crucial, pivotal, vital role, a testament, underscores, marks a shift | State the fact |
| Stock AI words: delve, tapestry, landscape, intricate, interplay, showcase, foster, garner, additionally, robust, seamless, leverage | Plain words |
| Essay connectives: Moreover, Furthermore, Overall, In summary, In conclusion, It should be noted, Notably, In light of | Start with the content |
| "-ing" add-ons: ", highlighting...", ", ensuring...", ", reflecting..." | A separate sentence, or cut |
| Weather cliches: remain vigilant, brace for, a mix of, Mother Nature | The specific action or condition |
| "Not only ... but", forced lists of three, false "from X to Y" ranges | Say the two things plainly |
| Em or en dashes as punctuation, `--` | Full stop, comma, colon or brackets (number ranges keep a hyphen: 50-200 mm) |
| Three sentences in a row opening with the same word | Merge them or start with the place or the action |
| Vague sources: experts say, observers note | Cut, or name ICPAC's forecast |
| Chatbot leftovers: Certainly, I hope this helps, let me know, here is | Cut |
| Faceless audiences: stakeholders, the rainfall landscape | Name who acts: farmers, pastoralists, water managers, disaster officers |

## Example

Original (computed):

> Moderate rainfall (50-200 mm) expected over central to southern parts of Kenya, central
> to southern parts of Burundi, central to northern parts of Tanzania and isolated areas in
> both southern Uganda and southwestern Somalia.

AI-sounding rewrite (fails the checker):

> Moreover, the region is poised to experience a vibrant mix of rainfall, with moderate
> totals (50-200 mm) underscoring the pivotal role of the short rains — stakeholders should
> remain vigilant.

Humanized:

> The short rains are most active in the south of the region. Moderate rainfall (50-200
> mm) is expected over central to southern parts of Kenya and Burundi, central to northern
> parts of Tanzania, and isolated areas of southern Uganda and southwestern Somalia.

The service gives the writer this same example (`chatbot/tone.py`, `EXAMPLE`); a test keeps
the two word for word, so change both together.

The humanized version keeps the one range, every place and the meaning, and adds the season
without a number.

## Other languages

For a translated draft (Kiswahili, French, Amharic and the others), apply the same voice in
that language and keep the figures; the checker's figure test (`--against`) still applies,
its English word lists do not. A speaker of the language checks the result before a
reviewer approves it.
