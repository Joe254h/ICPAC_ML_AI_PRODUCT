# Forecaster Copilot

The Copilot reads checked forecast packages, their country summaries and verification, the rainfall monitoring, the model registry, the data sources and approved references. It cannot run a forecast, promote a model or publish a bulletin.

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
LLM_TIMEOUT_SECONDS=60
```

On Azure, `ANTHROPIC_API_KEY=... bash deploy/azure/backend.sh` stores the key as a Container Apps secret and sets the rest (`CLAUDE_MODEL` picks another model). Claude is the default because it calls tools reliably and answers general climate questions well; the grounding check above holds whichever model is used. Questions and tool results are sent to Anthropic's API; nothing else is.

### Another provider with tool calling

Any OpenAI-compatible chat completions API that supports tools (Azure OpenAI, OpenAI, Groq, Ollama, vLLM, llama.cpp with `--jinja`) works the same way with `LLM_PROVIDER=openai_compatible`, `LLM_TOOLS=true` and the variables below. Small models call tools less reliably; their answers fall back to the fixed sentences more often.

### Fixed sentences only

MockLLMProvider runs by default. Set the following for a Qwen-class instruction model served by Ollama, llama.cpp, vLLM or another compatible server, without `LLM_TOOLS`, to let it choose among the fixed sentences:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:8001/v1
LLM_MODEL=qwen-prototype
LLM_API_KEY=
```

Use the server's actual configured model ID and reachable URL. Compose uses host.docker.internal for a host service; Linux may need an operator-added host-gateway mapping. API keys remain server-side and are not logged. Restart the backend after changing provider configuration.

To keep every question on ICPAC's own infrastructure, run the packaged Qwen3-4B-Instruct server on Azure (`deploy/azure/llm.sh`) or next to the backend (`docker-compose.llm.yml`); see [the self-hosted model guide](self-hosted-llm.md). A model on a CPU server needs `LLM_TIMEOUT_SECONDS` (default 20) raised to about 120 and `LLM_HISTORY_MESSAGES` (default 12 past messages sent with each question) lowered to about 4. `LLM_WARM_UP=true` wakes a model that scales to zero when the Copilot page opens.

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

The Weekly forecast bulletin page uses the owner's retained Word reference and its section order, with a reading preview, regional/Somalia rainfall maps and a Word draft download. Bulletin drafts freeze that same bulletin for review. The template's page settings, header/footer, styles and picture positions are retained, and old forecast text/images are replaced. Missing scientific products remain explicit; the original document is a layout reference, not current weather evidence. Rendered pages were checked against the reference with LibreOffice; check pagination in Word before release.

Reviewer names are self-reported in this localhost prototype. Authentication, role-based review, immutable audits and controlled distribution are production integrations.
