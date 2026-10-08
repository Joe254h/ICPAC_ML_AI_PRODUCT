# syntax=docker/dockerfile:1.7
# The Copilot's language model on ICPAC's own infrastructure: Qwen3-4B-Instruct-2507
# (Apache-2.0, Q4_K_M quantisation, 2.5 GB) served by llama.cpp's OpenAI-compatible server.
# It runs on CPUs; no GPU and no outside service is needed. The model only chooses among
# sentences the backend has already validated (chatbot/providers.py).
#
# Set LLAMA_API_KEY whenever the server is reachable from outside a private network (requests
# then need "Authorization: Bearer <key>"; /health stays open), and LLAMA_ARG_THREADS to the
# container's CPU count when the host has more CPUs than the container may use.
ARG SERVER_IMAGE=ghcr.io/ggml-org/llama.cpp:server-b11459
FROM ${SERVER_IMAGE}
ARG MODEL_URL=https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
# The download must match this checksum, so a changed or tampered file stops the build.
ADD --chmod=644 --checksum=sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597 \
    ${MODEL_URL} /models/qwen3-4b-instruct.gguf
ENV LLAMA_ARG_MODEL=/models/qwen3-4b-instruct.gguf \
    LLAMA_ARG_ALIAS=qwen3-4b-instruct \
    LLAMA_ARG_HOST=0.0.0.0 \
    LLAMA_ARG_PORT=8080 \
    LLAMA_ARG_CTX_SIZE=8192 \
    LLAMA_ARG_N_PARALLEL=1
EXPOSE 8080
# The server's chat web page is not needed: the backend uses the API only.
CMD ["--no-ui"]
