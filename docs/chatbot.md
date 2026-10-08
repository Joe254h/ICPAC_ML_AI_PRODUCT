# Forecaster Copilot

The Copilot reads checked forecast packages, their country summaries and verification, the model registry, observation registration and approved references. It cannot run a forecast, promote a model or publish a bulletin. The demonstration interface retains its ten original climate tools for explicitly selected demonstration requests.

POST /chat accepts a message, optional session_id and context_mode. The Copilot UI sends context_mode=operational; it never uses the shell's hidden mock-v1 selection. Optional country, variant (hybrid, mbc, raw), forecast_id and reset_context control the conversation's checked package. The default demonstration mode preserves the original API contract for demonstration clients using Selection.

The first forecast question resolves the same latest package as GET /forecasts/latest. Subsequent questions retain its ID, country, method and subject in the persisted session. "And Somalia?", "Tell me more" and "What does that mean?" use that context. Explicit countries or methods override the previous ones. "Latest" selects the newest package; "last week" selects the preceding available package. A date with no package produces an unavailable answer, with no substitution of demonstration values. Definitions and greetings work before a forecast exists.

Responses include context, text, tool_trace, citations, provider/fallback status and session_id. Map questions can return a checked image URL, and bulletin questions link to the weekly preview and Word draft for the same package. Unsupported anomaly, exceptional rainfall, temperature and heat-stress requests stay unavailable. Comparing rainfall methods is distinct from ranking their skill; missing observations never yield mock verification scores.

GET /chat/sessions lists titles, updated dates and contexts; GET /chat/sessions/{id} restores the full saved conversation. Stored messages are retained, while the language-model prompt receives only the latest twelve messages, each bounded in length, plus fresh approved facts. The interface supports saved-conversation selection, Enter to send, Shift+Enter for a newline, automatic scrolling and a jump to the latest message. A failed send restores the draft for retry without leaving a duplicate user message. Sources and tool details remain collapsed until requested.

## Provider configuration
MockLLMProvider runs by default. Set the following for a Qwen-class instruction model served by Ollama, llama.cpp, vLLM or another compatible server:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:8001/v1
LLM_MODEL=qwen-prototype
LLM_API_KEY=
```

Use the server's actual configured model ID and reachable URL. Compose uses host.docker.internal for a host service; Linux may need an operator-added host-gateway mapping. API keys remain server-side and are not logged. Restart the backend after changing provider configuration.

## Grounding boundary
Python tools calculate all values. The provider receives approved evidence-rendered sentences, the IDs that must always appear (scope, synthetic-input and model-status labels, metric and comparison scope), reference metadata and bounded conversation history, then returns only a JSON outline of sentence IDs: the sentences that answer the question, in order. The backend accepts only approved IDs, each once, appends any required ID the model left out and renders the sentences itself. The LLM cannot invent text, reorder field associations or alter numeric values. An unknown ID, an invalid response or an unavailable server falls back to a labelled deterministic outline.

Questions such as "What is climate?" that name a term outside the built-in definitions are answered from the approved glossary (fixtures/references/glossary.md, cited as a source). Questions with no forecast, data or model subject, no country and no date get a short guide to what the Copilot can answer instead of a forecast summary.

This deliberately constrained interpretation prototype does not offer unrestricted free-form LLM prose or autonomous tool selection. Broader generation requires evaluated claim-level grounding first. Questions and reference documents are treated as data, never executable instructions. No Python, shell, filesystem command, model promotion or publication tool exists.

## Retrieval
LocalDocumentIngestor reads fixtures/references/manifest.json and bounded local text files. Each entry needs id, title, category, path and approved=true. Paths must stay within the reference directory. ReferenceIndex ranks documents by lexical token overlap; it is replaceable by an embedding/vector index later. Categories separate scientific_reference, historical_bulletin and operational_documentation from live structured tool evidence. Historical demonstration bulletins are marked synthetic. Citations expose title, ID, excerpt and SHA256; GET /references/{id} shows the source.

Add only reviewed prototype references to the manifest. Future adapters can ingest official ICPAC bulletins, weekly archives, SOPs, GHACOF, PRECOF, sector advisories and model documentation through DocumentIngestor. No uploaded document is automatically promoted to an approved operational source.

## Bulletins
Once an operational forecast exists, Generate draft freezes the ICPAC weekly bulletin of the latest forecast (or of `forecast_id`; a revision keeps its parent's forecast): the template sections, the Word document made from the retained reference and the regional rainfall map, each with its SHA256, plus the package's manifest checksum and provenance. The consistency check compares the draft's text with its frozen sections, and every transition re-checks the frozen map and Word document; an approval seals both. Export gives the frozen Word document (`format=docx`) or that document as a web page (`format=html`, built from the .docx itself: the same words, bold leads, bullets and maps in order), followed by the review history and provenance. Once approved, published or rejected, the exported document's page header names that decision, its reviewer and date in place of "DRAFT - NOT APPROVED"; its text and maps stay the reviewed ones. Frozen files are also kept in Blob Storage; a file lost with the server disk is restored from it, or produced again from the package and accepted only if its checksum matches. Before the first forecast, drafts summarise the synthetic demonstration grid from get_bulletin_context with deterministic sentences and an HTML export, as in the first release.

Allowed human transitions: draft → under_review → approved → published; under_review → rejected. Each action needs reviewer name, confirmation and justification. Drafts cannot publish directly. The Bulletin drafts page shows a weekly draft as its document and supports revisions, side-by-side comparison, review history, Word download and self-contained HTML export. Published means a **local demo record**, never external dissemination.

The Weekly forecast bulletin page uses the owner's retained Word reference and its section order, with a reading preview, regional/Somalia rainfall maps and a Word draft download. Bulletin drafts freeze that same bulletin for review. The template's page settings, header/footer, styles and picture positions are retained, and old forecast text/images are replaced. Missing scientific products remain explicit; the original document is a layout reference, not current weather evidence. Rendered pages were checked against the reference with LibreOffice; check pagination in Word before release.

Reviewer names are self-reported in this localhost prototype. Authentication, role-based review, immutable audits and controlled distribution are production integrations.
