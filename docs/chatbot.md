# Forecaster Copilot

The Copilot reads checked forecast packages, their country summaries and verification, the rainfall monitoring, the model registry, the data sources and approved references. It cannot run a forecast, promote a model or publish a bulletin.

Connect through **Staff access** using a personal key with the `chat` or `admin` role.
Conversation list, read, follow-up, archive and delete actions are restricted to that
identity. Legacy conversations without an owner are not exposed. The key stays in tab
memory and must be entered again after a reload. Limits are 10 questions/minute, 200/day
and 50 questions/conversation. A shared 120-second model budget covers all rounds and
fallbacks. See [access configuration](deployment-powershell.md#access-privacy-and-recovery).

## How it answers

With a tool-calling language model configured (recommended: **Claude through the Anthropic API**), the Copilot is an assistant that looks things up before it answers (`chatbot/agent.py`):

* It has read-only tools: the forecast, one country, a comparison of countries, verification, seasonal skill, the weekly bulletin, rainfall monitoring, data sources, the model, a map and the approved references. It picks the ones a question needs, up to six rounds.
* **Forecast questions** are answered from what the tools return. Before an answer is shown, every rainfall amount (mm) and percentage in it is checked against the tool results at the precision written; an answer quoting any other number is discarded and the checked, fixed sentences below answer instead.
* **General questions** (what is the MJO, how El Niño affects the October–December rains) are answered from the model's own knowledge and are labelled *General background* in the interface; answers built on the service's data show what they are based on (forecast, verification, monitoring, ...).
* The forecast in discussion stays pinned across the conversation; "And Somalia?" or "last week" work as below.

Without such a model, or when the provider fails, the Copilot uses its fixed-sentence path, described under [Grounding boundary](#grounding-boundary).

POST /chat accepts a message, optional session_id and context_mode. context_mode accepts only operational. Optional country, variant (hybrid, mbc, raw), forecast_id and reset_context control the conversation's checked package.

The first forecast question resolves the same latest package as GET /forecasts/latest. Subsequent questions retain its ID, country, method and subject in the persisted session. "And Somalia?", "Tell me more" and "What does that mean?" use that context. Explicit countries or methods override the previous ones. "Latest" selects the newest package; "last week" selects the preceding available package. A date with no package produces an unavailable answer, with no substitution of other values. Definitions and greetings work before a forecast exists.

Responses include context, text, tool_trace, citations, provider/fallback status and session_id. Map questions can return a checked image URL, and bulletin questions link to the weekly preview and Word draft for the same package. Unsupported anomaly, exceptional rainfall, temperature and heat-stress requests stay unavailable. Comparing rainfall methods is distinct from ranking their skill; missing observations never yield mock verification scores.

GET /chat/sessions lists titles, updated dates and contexts; GET /chat/sessions/{id} restores the full saved conversation. Stored messages are retained, while the language-model prompt receives only the latest twelve messages, each bounded in length, plus fresh approved facts. The interface supports saved-conversation selection, Enter to send, Shift+Enter for a newline, automatic scrolling and a jump to the latest message. A failed send restores the draft for retry without leaving a duplicate user message. Sources and tool details remain collapsed until requested.

## Provider configuration

### Claude (recommended)

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...      # or LLM_API_KEY
LLM_MODEL=claude-opus-5-5         # default; claude-sonnet-5-5 costs less
LLM_EFFORT=low                    # default; medium or high think longer (slower, dearer)
LLM_TIMEOUT_SECONDS=60
```

The Copilot calls Claude through Anthropic's official Python SDK (`anthropic`). Current Claude models think before they answer; the thinking counts towards the 16,000-token output limit, and within one answer Claude's turns (thinking included) go back to it unchanged while it calls tools. The system prompt and tools are cached between calls, which lowers the cost of every question after the first. A request Claude's safeguards decline is re-run on the model Anthropic recommends (server-side fallback); a declined or cut-off answer falls back to the checked fixed sentences. `LLM_MODEL` is used only when it names a Claude model, and `LLM_BASE_URL` is ignored for Claude, so an earlier Groq or Qwen setting left on the server does no harm (a proxy for Claude is set with `ANTHROPIC_BASE_URL`).

On Azure, `ANTHROPIC_API_KEY=... bash deploy/azure/backend.sh` stores the key as a Container Apps secret and sets the rest (`CLAUDE_MODEL` picks another model). Claude is the default because it calls tools reliably and answers general climate questions well; the grounding check above holds whichever model is used. Questions and tool results are sent to Anthropic's API; nothing else is.

### Free: Google Gemini

The Gemini API has a free tier (Flash models; key from https://aistudio.google.com/apikey, no card). On Azure (Cloud Shell in PowerShell):

```powershell
$env:GEMINI_API_KEY = Read-Host "Gemini key" -MaskInput   # GEMINI_MODEL picks another model
bash backend.sh
```

In Bash, `GEMINI_API_KEY=... bash backend.sh` does the same.

This sets `LLM_PROVIDER=openai_compatible`, `LLM_TOOLS=true`, Gemini's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`), `gemini-3.8-flash` and `LLM_REASONING_EFFORT=low`. The Copilot then answers the same way as with Claude, and the same figure check applies. Free-tier limits are per minute and per day, and each question uses two or three requests; a request refused for the per-minute limit (or a brief server error) is retried once after the wait Gemini asks for, and when a limit is still reached, the checked fixed sentences answer.

**Which Gemini model.** Since September 2026 Google serves the Gemini 2.5 models only to projects that used them before; a key made since gets every request refused, and the Copilot then answered every question with the fixed sentences. The default is now `gemini-3.8-flash`, and when Google refuses the configured model (unknown, retired or closed to the key) the Copilot tries `gemini-3.8-flash`, `gemini-flash-latest` and `gemini-3.5-flash-lite` in turn and keeps the first that answers (`LLM_FALLBACK_MODELS` replaces that list, for any provider). An app deployed earlier with `gemini-2.5-flash` is switched by the next run of `backend.sh`. Gemini keeps its own temperature (Google asks for its default with the thinking models); other providers get 0.2, or `LLM_TEMPERATURE`.

When an answer falls back, the chat says why in words (for example, the free limit was reached, or the key was refused), and the System page shows the model that answered the last question, or why it did not, followed by what the AI service itself said (its error message, with keys, links and project numbers left out). A refusal the Copilot does not recognise ("no permission for this model or API") is therefore explained there in Google's words. To test a key from Cloud Shell: `curl -s -H "Authorization: Bearer $GEMINI_API_KEY" https://generativelanguage.googleapis.com/v1beta/openai/models` lists the models the key may use, or prints Google's reason for refusing it.

Without the language model, forecast questions still get checked answers: the bulletin's rainfall classes for the country or the region (where heavy, moderate and light rainfall are expected), its ranking among the member states, the median and range, and any country's map. A question outside the forecast ("what is love?") is answered with a plain statement that it needs the AI assistant, and with examples of what still works.

Gemini is strict about tool definitions: it refuses the whole request when a tool's parameter schema is an object with no properties, or uses JSON Schema keywords it does not support. Each tool is therefore sent with only the keywords Gemini accepts (`type`, `description`, `properties`, `required`, `enum`, `items`), and a tool without inputs is sent without parameters. Gemini's thinking models also attach a signature to each tool call that must come back unchanged with the tool's result; the Copilot returns the calls exactly as Gemini sent them. When Gemini refuses a request, the server log says why (`Copilot model ... answered 400: ...`). On the free tier Google may use what is sent to improve its products: the Copilot sends the question and the forecast figures, which are public, but forecasters should not type anything confidential. Check the current limits in Google AI Studio.

### Cheapest Claude

`CLAUDE_MODEL=claude-haiku-5-5` with `ANTHROPIC_API_KEY` costs $0.10 per million tokens read and $0.50 per million written; a Copilot question uses roughly 8,000 to 15,000 tokens, about $0.002, so $5 of credit lasts for thousands of questions.

### Another provider with tool calling

Any OpenAI-compatible chat completions API that supports tools (Azure OpenAI, OpenAI, Groq, Ollama, vLLM, llama.cpp with `--jinja`) works the same way with `LLM_PROVIDER=openai_compatible`, `LLM_TOOLS=true` and the variables below; `LLM_REASONING_EFFORT` is passed to the model and `LLM_MAX_TOKENS` (default 4096) leaves room for a thinking model's reasoning. Small models call tools less reliably, and free plans with low per-minute token limits (such as Groq's) cut multi-step answers short; their answers fall back to the fixed sentences more often.

### Fixed sentences only

MockLLMProvider runs by default. Set the following for a Qwen-class instruction model served by Ollama, llama.cpp, vLLM or another compatible server, without `LLM_TOOLS`, to let it choose among the fixed sentences:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:8001/v1
LLM_MODEL=qwen-prototype
LLM_API_KEY=
```

Use the server's actual configured model ID and reachable URL. Compose uses host.docker.internal for a host service; Linux may need an operator-added host-gateway mapping. API keys remain server-side and are not logged. Restart the backend after changing provider configuration.

To keep every question on ICPAC's own infrastructure, run the packaged Qwen3-4B-Instruct server on Azure (`deploy/azure/llm.sh`) or next to the backend (`docker-compose.llm.yml`); see [the self-hosted model guide](self-hosted-llm.md). For a CPU server, use `LLM_TIMEOUT_SECONDS=60` and lower `LLM_HISTORY_MESSAGES` to about 4. The total model budget remains 120 seconds by default (maximum 180). `LLM_WARM_UP=true` wakes a model that scales to zero when the Copilot page opens.

## Grounding boundary
This is the fixed-sentence path: the default without a tool-calling model, and the fallback when one fails or quotes an unsupported number. Python tools calculate all values. The evidence for each question is a set of approved sentences: labels that every answer shows (scope, synthetic-input and model-status labels, metric and comparison scope) and the answer sentences. The provider receives the answer sentences and their IDs, the labels as context, reference metadata and bounded conversation history, then returns only a JSON outline: the IDs of the answer sentences that answer the question, most relevant first. The backend accepts only approved IDs, each once, and at least one answer; it keeps the labels in their place around the chosen answers and renders the sentences itself. The LLM cannot invent text, drop a label, reorder field associations or alter numeric values. An unknown ID, an outline with no answer, an invalid response or an unavailable server falls back to a labelled deterministic outline (`deterministic_fallback`). When a question has one possible answer sentence or none, there is nothing to choose: the backend answers without calling the model (`deterministic`).

Questions such as "What is climate?" that name a term outside the built-in definitions are answered from the approved glossary (fixtures/references/glossary.md, cited as a source). Questions with no forecast, data or model subject, no country and no date get a short guide to what the Copilot can answer instead of a forecast summary.

On this path the model writes no prose and selects no tools. On either path, questions and reference documents are treated as data, never executable instructions, and no Python, shell, filesystem command, model promotion or publication tool exists.

## Retrieval
LocalDocumentIngestor reads fixtures/references/manifest.json and bounded local text files. Each entry needs id, title, category, path and approved=true. Paths must stay within the reference directory. ReferenceIndex ranks documents by lexical token overlap; it is replaceable by an embedding/vector index later. Categories separate scientific_reference, historical_bulletin and operational_documentation from live structured tool evidence. Historical demonstration bulletins are marked synthetic. Citations expose title, ID, excerpt and SHA256; GET /references/{id} shows the source.

Add only reviewed prototype references to the manifest. Future adapters can ingest official ICPAC bulletins, weekly archives, SOPs, GHACOF, PRECOF, sector advisories and model documentation through DocumentIngestor. No uploaded document is automatically promoted to an approved operational source.

## Bulletins
Once an operational forecast exists, Generate draft freezes the ICPAC weekly bulletin of the latest forecast (or of `forecast_id`; a revision keeps its parent's forecast): the template sections, the Word document made from the retained reference and the regional rainfall map, each with its SHA256, plus the package's manifest checksum and provenance. The consistency check compares the draft's text with its frozen sections, and every transition re-checks the frozen map and Word document; an approval seals both. Export gives the frozen Word document (`format=docx`) or that document as a web page (`format=html`, built from the .docx itself: the same words, bold leads, bullets and maps in order), followed by the review history and provenance. Once approved, published or rejected, the exported document's page header names that decision, its reviewer and date in place of "DRAFT - NOT APPROVED"; its text and maps stay the reviewed ones. Frozen files are also kept in Blob Storage; a file lost with the server disk is restored from it, or produced again from the package and accepted only if its checksum matches. Before the first forecast there is nothing to draft, and generation says so.

Allowed human transitions: draft → under_review → approved → published; under_review → rejected. Each action needs reviewer name, confirmation and justification. Drafts cannot publish directly. The Bulletin drafts page shows a weekly draft as its document and supports revisions, side-by-side comparison, review history, Word download and self-contained HTML export. Published records the release in the service; ICPAC disseminates the bulletin through its own channels.

The Weekly forecast bulletin page uses the owner's retained Word reference and its section order, with a reading preview, the regional rainfall map, the country focus (the member state with the most distinctive outlook, and why) and a Word draft download. Bulletin drafts freeze that same bulletin for review. The template's page settings, header/footer, styles and picture positions are retained, and old forecast text/images are replaced. Products the service does not have (anomalies, temperature, heat stress) are left out; the original document is a layout reference, not current weather evidence. Rendered pages were checked against the reference with LibreOffice; check pagination in Word before release.

Manual bulletin writes require the configured operator credential; personal email decisions
require their signed, expiring, single-use token. See [manual access setup](deployment.md#manual-bulletin-access).
Operator review names remain self-reported. Per-person role-based login and authenticated
access to the remaining model, operation and chat APIs are still production integrations.

## Changing the bulletin in the conversation

Ask the Copilot to show this week's bulletin and it appears in the conversation as a card:
version, review status and sections. Ask for a change ("make the headline about western
Kenya", "add an advisory for farmers", "drop the impacts note") and the Copilot writes a new
draft version with `revise_bulletin`. The newest draft of the forecast is revised (one is
made first if there is none). The new version shows in the conversation with the changed
sections marked, a link to review it and its Word document.

- What can change: the headline, the decision-support note, the regional rainfall
  statements, the country focus and its explanation, and up to four sections of the
  forecaster's own (an advisory, impacts, guidance for a sector), added before the forecast
  note. The country table and the forecast note come from the forecast and stay as they are.
- Figures: every number in new wording must come from the forecast, the tools' results or
  the forecaster's own messages in the conversation; a figure from nowhere is sent back to the
  model and the draft is not made.
- Tone: the paragraphs are checked against the humanizer patterns (Wikipedia's "Signs of AI
  writing"): dashes used as punctuation, stock AI and sales words, inflated importance,
  chatbot phrases, filler, emojis and markdown (chatbot/tone.py). Flagged paragraphs go back
  to the model to rewrite; quotes and spacing are fixed directly. The same rules are in the
  model's instructions.
- Review: each version is an ordinary draft with its own frozen Word document, checksum and
  consistency check, the asker's name and their request. Submitting, approving and publishing
  stay on the Bulletin page with named reviewers; the Copilot has no tool for them.

## Comparing another model's forecast

The paperclip in the Copilot uploads another model's Week-2 forecast: a NetCDF file (up to
4 MB through the website) with the week's total rainfall, or its seven daily totals, on a
regular latitude-longitude grid. Name the model, and give the week's first day if the file
has no dates. The file is read in a separate process with no secrets in its environment and
limits on time, memory and output (climate_engine/inputs/external_forecast.py). Units in mm,
kg m-2 or m are accepted, daily amounts are summed over seven steps, and ensemble members are
averaged. Rates per second, other time lengths and curvilinear grids are refused with the
reason. The field is put bilinearly on the 0.05 degree model grid.

The Copilot then compares it with ICPAC's forecast of the same week (regional and country
means, pattern correlation). Once CHIRPS covers the week, the verification pass scores both
forecasts against CHIRPS on the same cells (MAE, RMSE, bias, correlation), and against ARC
2.0, RFE 2.0 and GPM IMERG where held. It says which came closer, for the region and country
by country. The Verification page lists every upload with its scores. One week is one case:
compare several weeks before concluding that one model is better.

Copilot forecast dates distinguish `valid:YYYY-MM-DD` (any day inside the valid week,
end date exclusive) from `run:YYYY-MM-DD` (ECMWF initialization). An ambiguous bare date
requests clarification. The fixed-answer fallback keeps both countries and selected
methods across comparison follow-ups, until the user changes them or resets context.

The numerical check uses unit-bearing quantities returned by successful tools, excludes
user-supplied figures, dates, identifiers and ranks, separates millimetres from percentages,
and checks signed numbers and both ends of ranges. It checks numerical support, not every
semantic association in free-form prose; forecaster review remains necessary.

## Wikipedia and the web

The Copilot can look things up beyond ICPAC's data: `search_wikipedia` (summaries from any
of eleven Wikipedia editions, including Kiswahili, Amharic and Somali), `search_web` (titles,
links and snippets) and `read_web_page` (the text of one page). Pages it used are listed
under the answer's sources. Only http(s) pages on public internet addresses are read: every
address a name resolves to is checked, the connection goes to that checked address,
redirects are checked the same way, and pages are cut to a few thousand characters. What a
page says is information for the answer, never an instruction; web text never replaces the
forecast, observed rainfall or verification figures, and those figures are still checked.

| Setting | Effect |
|---|---|
| `COPILOT_WEB=false` | Switches the three lookups off |
| `BRAVE_SEARCH_API_KEY` | Uses the Brave Search API for `search_web`; without it the search reads DuckDuckGo's HTML results |

## Answer language

The chat request carries `language` (en, sw, am, so, ar, fr, ti, om, rw, rn, lg), chosen
from the menu on the Copilot page. The choice is the site's: the bulletin page's
*Translate this draft* uses the same one, and choosing a language in either place changes it
in both (`frontend/lib/language.ts`). The model writes the whole answer in that language,
keeps every figure, unit and date as the tools gave them, and says when it cannot write the
language well.

Asked for the bulletin, the Copilot shows the newest draft in the chosen language when
there is one (a draft's language is kept through later edits); when there is none, it can
make one with `translate_bulletin`, the same checked translation as the bulletin page: a new
draft version, kept only if every paragraph keeps its figures, that a speaker of the
language reviews before approval. See `docs/language_training.md` for the translation model
that will take over the less-resourced languages.

## Files, editing and retrying

Files of any format go with a question (`chatbot/attachments.py`): text, PDF, Word,
PowerPoint and Excel are read; images go to an AI service that reads them; NetCDF forecasts
go to the comparison above. Files over 4 MB are sent in parts, up to 20 MB. When the AI
service cannot answer, a question with files shows what was read from them (the start of
each document's text) instead of this week's forecast.

Each question can be copied or edited and asked again (the answers after it are replaced,
its files kept); the latest answer can be copied or asked for again.
