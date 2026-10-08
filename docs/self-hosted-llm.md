# Self-hosted Copilot model

The Copilot can use a language model that runs on ICPAC's own infrastructure, so no
question or forecast fact is sent to an outside AI service. The model is
**Qwen3-4B-Instruct-2507** (Apache-2.0), quantised to Q4_K_M (2.5 GB) and served by
llama.cpp's OpenAI-compatible server. It runs on ordinary CPUs; no GPU is needed.

The model never writes text. Python computes every value and writes every sentence; the
model only chooses which validated sentences answer the question (see
[the grounding boundary](chatbot.md#grounding-boundary)). The weekly bulletin uses no
language model at all.

## What it does and how fast it is

- **Most questions need no model call.** When only one answer sentence fits ("Explain the
  forecast", "Where is heavy rainfall?", "And Somalia?", definitions), the backend shows it
  with its labels straight away. The answer's provider then reads `deterministic`.
- **Questions with several possible answers** (comparing raw, MBC and hybrid rainfall; the
  bulletin) are sent to the model. On 2 vCPUs, as on Azure, these took 27-31 seconds in
  testing (600-700 prompt tokens at about 22 tokens per second). 4 vCPUs roughly halve that;
  a GPU server is much faster.
- If the model is slow, unreachable or returns anything but approved IDs, the answer uses
  the full validated outline and says so (`deterministic_fallback`).

The image is [docker/llm.Dockerfile](../docker/llm.Dockerfile). The "Publish model image"
workflow builds it, checks the model file against its SHA256, makes it answer a test request
on 2 CPUs and publishes `ghcr.io/joe254h/icpac-llm`.

## On Azure (the current hosting)

Run this in Azure Cloud Shell after the backend is deployed:

```bash
curl -fsSL https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/main/deploy/azure/llm.sh -o llm.sh
bash llm.sh
```

It creates the container app `icpac-llm` (2 vCPU, 4 GiB) next to `icpac-api`, waits until
the model answers a test request, then redeploys the backend with these settings:

| Setting | Value |
| --- | --- |
| `LLM_PROVIDER` | `openai_compatible` |
| `LLM_BASE_URL` | `https://<icpac-llm address>/v1` |
| `LLM_MODEL` | `qwen3-4b-instruct` |
| `LLM_API_KEY` | secret `llm-api-key` (generated; kept on reruns) |
| `LLM_TIMEOUT_SECONDS` | `120` |
| `LLM_HISTORY_MESSAGES` | `4` |
| `LLM_WARM_UP` | `true` |

These replace earlier Copilot settings such as Groq's. Later `backend.sh` runs keep them.

- **Access.** Azure for Students uses "express" Container Apps environments, which connect
  apps only through their public addresses, so the model requires the key. Only the two
  apps hold it; every request but `/health` without it is refused (401).
- **Starting from zero.** The model app scales to zero when unused, and you pay only while it
  runs. Opening the Copilot page wakes it (`LLM_WARM_UP`). A question asked before it has
  started gets the labelled fallback outline, and the next one uses the model.
- **Larger size.** `LLM_CPU=4 LLM_MEMORY=8Gi bash llm.sh` answers about twice as fast and uses
  twice the compute.
- **Removing it.** Run `az containerapp delete --name icpac-llm --resource-group icpac`. Then
  set the Copilot settings again, for Groq following [groq-setup.md](groq-setup.md) (its
  key secret has to be added again).

## On an ICPAC server with Docker

```bash
docker compose -f docker-compose.yml -f docker-compose.llm.yml up -d
```

[docker-compose.llm.yml](../docker-compose.llm.yml) adds the `llm` service and points the
backend at `http://llm:8080/v1`. The model is reachable only on the compose network, so it
needs no key. It uses every CPU the server has. On a shared server, give the service a
`cpus:` limit and set `LLAMA_ARG_THREADS` to the same number.

## With Ollama or vLLM instead

Any OpenAI-compatible server works. Set the backend's `LLM_*` settings to point at it:

- **Ollama** (tested with Ollama 0.40 and the same Qwen3-4B-Instruct file):
  - `LLM_BASE_URL=http://<host>:11434/v1`, and `LLM_MODEL` = the name `ollama list` shows.
  - Start Ollama with `OLLAMA_NO_CLOUD=1`, so Ollama itself uses no cloud features, and
    `OLLAMA_CONTEXT_LENGTH=8192`.
  - Ollama has no access key, so keep it on a private network.
- **vLLM** (for a GPU server; not tested in this project): `vllm serve
  Qwen/Qwen3-4B-Instruct-2507 --api-key <key>`, with that key as `LLM_API_KEY`.
- **On a CPU server** set `LLM_TIMEOUT_SECONDS=120` and `LLM_HISTORY_MESSAGES=4`. Leave
  `LLM_REASONING_EFFORT` empty.

A reasoning model that writes `<think>…</think>` before its JSON also works, but it is
slower; prefer an instruct (non-thinking) model.

## Model provenance

- **Weights:** `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` from
  [unsloth/Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF),
  a quantisation of [Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
  (Apache-2.0).
- **Checksum:** SHA256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`.
- **Server:** llama.cpp server build b11459 (`ghcr.io/ggml-org/llama.cpp:server-b11459`, MIT).

To change the model or server, edit the Dockerfile's `MODEL_URL`, its checksum and the
alias (`LLAMA_ARG_ALIAS`, which is the backend's `LLM_MODEL`), then let the workflow
publish it.
