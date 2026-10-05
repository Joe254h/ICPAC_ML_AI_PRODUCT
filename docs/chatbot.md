# Forecaster Copilot

The Copilot executes only ten read-only climate tools: get_latest_forecast, get_country_forecast, get_verification_metrics, compare_models, compare_observations, get_qc_status, get_available_datasets, get_model_metadata, get_recent_products and get_bulletin_context. Country/source/model/period context is validated before calculation. Named countries override the current region; "last week" selects the preceding configured forecast cycle.

POST /chat accepts message, optional session_id and Selection. Responses include text, tool_trace, source citations, provider/fallback status and session_id. GET /chat/sessions and /chat/sessions/{id} expose persisted history. The UI restores the last local conversation and supports a new conversation. Unknown dates, missing inputs and QC failures produce an explicit unavailable response.

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
Python tools calculate all values. The provider receives approved evidence-rendered sentences and reference context, then returns only a JSON outline of sentence IDs. The backend requires every approved ID exactly once and renders the sentences itself. The LLM cannot invent, reorder field associations or alter numeric values. An invalid response or unavailable server falls back to a labelled deterministic outline.

This deliberately constrained interpretation prototype does not offer unrestricted free-form LLM prose or autonomous tool selection. Broader generation requires evaluated claim-level grounding first. Questions and reference documents are treated as data, never executable instructions. No Python, shell, filesystem command, model promotion or publication tool exists.

## Retrieval
LocalDocumentIngestor reads fixtures/references/manifest.json and bounded local text files. Each entry needs id, title, category, path and approved=true. Paths must stay within the reference directory. ReferenceIndex ranks documents by lexical token overlap; it is replaceable by an embedding/vector index later. Categories separate scientific_reference, historical_bulletin and operational_documentation from live structured tool evidence. Historical demonstration bulletins are marked synthetic. Citations expose title, ID, excerpt and SHA256; GET /references/{id} shows the source.

Add only reviewed prototype references to the manifest. Future adapters can ingest official ICPAC bulletins, weekly archives, SOPs, GHACOF, PRECOF, sector advisories and model documentation through DocumentIngestor. No uploaded document is automatically promoted to an approved operational source.

## Bulletins
Generate a frozen draft from get_bulletin_context. The service retains facts/SHA256, model/source/config provenance, citation versions and a frozen checksummed map. Automated consistency checks compare sentences and text to deterministic fields.

Allowed human transitions: draft → under_review → approved → published; under_review → rejected. Each action needs reviewer name, confirmation and justification. Drafts cannot publish directly. The Bulletin page supports revisions, side-by-side comparison, review history and portable self-contained HTML export. Published means a **local demo record**, never external dissemination. HTMLBulletinExporter implements the export contract; WordTemplateExporter explicitly awaits a validated official template.

Reviewer names are self-reported in this localhost prototype. Authentication, role-based review, immutable audits and controlled distribution are production integrations.
