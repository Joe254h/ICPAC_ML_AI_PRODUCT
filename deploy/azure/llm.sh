#!/usr/bin/env bash
# Run the Copilot's language model in your own Azure subscription, so no outside AI service
# is used, and point the backend at it. Run it in Azure Cloud Shell after backend.sh:
#
#   curl -fsSL https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/main/deploy/azure/llm.sh -o llm.sh
#   bash llm.sh
#
# It creates (or updates) the container app icpac-llm from ghcr.io/joe254h/icpac-llm:
# Qwen3-4B-Instruct served by llama.cpp on CPUs (docker/llm.Dockerfile, built by the "Publish
# model image" workflow). Express environments connect apps only through their public
# addresses, so the model requires a key, which only the two apps hold. The script then
# redeploys the backend with backend.sh, set to use the model. It scales to zero when unused;
# opening the Copilot page wakes it. See docs/self-hosted-llm.md.
#
# Settings (environment variables, all optional):
#   GROUP, APP, ENVIRONMENT  As for backend.sh (defaults icpac, icpac-api, icpac-env).
#   LLM_APP               The model's container app (default icpac-llm).
#   LLM_IMAGE             Its image (default ghcr.io/joe254h/icpac-llm:latest).
#   LLM_CPU, LLM_MEMORY   Its size (default 2 and 4Gi; 4 and 8Gi answer about twice as fast).
#   DATABASE_URL, IMAGE, CPU, MEMORY  Passed on to backend.sh for the backend.
set -euo pipefail

GROUP=${GROUP:-icpac}
APP=${APP:-icpac-api}
ENVIRONMENT=${ENVIRONMENT:-icpac-env}
LLM_APP=${LLM_APP:-icpac-llm}
LLM_IMAGE=${LLM_IMAGE:-ghcr.io/joe254h/icpac-llm:latest}
LLM_CPU=${LLM_CPU:-2}
LLM_MEMORY=${LLM_MEMORY:-4Gi}
MODEL=qwen3-4b-instruct
BACKEND_SCRIPT=https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/main/deploy/azure/backend.sh

step() { printf '\n==> %s\n' "$*"; }

step "Backend $APP in $GROUP"
if ! az containerapp show --name "$APP" --resource-group "$GROUP" --output none 2>/dev/null; then
  echo "Deploy the backend first (bash backend.sh), then run this script again."
  exit 1
fi
ENVIRONMENT_ID=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --query id --output tsv)
# The environment's region, written as backend.sh expects it (switzerlandnorth).
LOCATION=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --query location --output tsv | tr -d ' ' | tr '[:upper:]' '[:lower:]')

step "Container app $LLM_APP from $LLM_IMAGE ($LLM_CPU vCPU, $LLM_MEMORY)"
KEY=""
if az containerapp show --name "$LLM_APP" --resource-group "$GROUP" --output none 2>/dev/null; then
  KEY=$(az containerapp secret list --name "$LLM_APP" --resource-group "$GROUP" \
    --show-values --query "[?name=='llm-api-key'].value | [0]" --output tsv)
fi
[ -n "$KEY" ] || KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
DEFINITION=$(mktemp --suffix .json)
BACKEND=$(mktemp --suffix .sh)
trap 'rm -f "$DEFINITION" "$BACKEND"' EXIT
LLM_APP="$LLM_APP" LOCATION="$LOCATION" ENVIRONMENT_ID="$ENVIRONMENT_ID" \
  LLM_IMAGE="$LLM_IMAGE" LLM_CPU="$LLM_CPU" LLM_MEMORY="$LLM_MEMORY" KEY="$KEY" \
  python3 - "$DEFINITION" <<'PY'
import json
import os
import sys
import time

e = os.environ
definition = {
    "location": e["LOCATION"],
    "properties": {
        "environmentId": e["ENVIRONMENT_ID"],
        "configuration": {
            "ingress": {"external": True, "targetPort": 8080},
            "secrets": [{"name": "llm-api-key", "value": e["KEY"]}],
        },
        "template": {
            "containers": [
                {
                    "name": e["LLM_APP"],
                    "image": e["LLM_IMAGE"],
                    "resources": {"cpu": float(e["LLM_CPU"]), "memory": e["LLM_MEMORY"]},
                    "env": [
                        # A changed value makes every run a new revision with the latest image.
                        {
                            "name": "DEPLOYED_AT",
                            "value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        },
                        # Every request but /health needs "Authorization: Bearer <key>".
                        {"name": "LLAMA_API_KEY", "secretRef": "llm-api-key"},
                        # One thread per vCPU: the host has more CPUs than the container.
                        {"name": "LLAMA_ARG_THREADS", "value": str(max(1, int(float(e["LLM_CPU"]))))},
                    ],
                    # Loading the model takes seconds; pulling the 2.5 GB image takes longer.
                    "probes": [
                        {
                            "type": "Startup",
                            "tcpSocket": {"port": 8080},
                            "periodSeconds": 10,
                            "failureThreshold": 30,
                        }
                    ],
                }
            ],
            "scale": {"minReplicas": 0, "maxReplicas": 1},
        },
    },
}
with open(sys.argv[1], "w") as stream:
    json.dump(definition, stream, indent=2)
PY
APP_ID="${ENVIRONMENT_ID%/managedEnvironments/*}/containerApps/$LLM_APP"
az rest --method put --url "https://management.azure.com$APP_ID?api-version=2025-07-01" \
  --body "@$DEFINITION" --output none
for _ in $(seq 1 60); do
  STATE=$(az containerapp show --name "$LLM_APP" --resource-group "$GROUP" \
    --query properties.provisioningState --output tsv 2>/dev/null || true)
  case "$STATE" in
    Succeeded) break ;;
    Failed | Canceled)
      echo "The container app reported $STATE; check: az containerapp logs show -n $LLM_APP -g $GROUP"
      exit 1
      ;;
  esac
  sleep 10
done
FQDN=$(az containerapp show --name "$LLM_APP" --resource-group "$GROUP" \
  --query properties.configuration.ingress.fqdn --output tsv)

step "Waiting for the model (the first start pulls a 2.5 GB image)"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 20 "https://$FQDN/health" > /dev/null 2>&1; then
    break
  fi
  sleep 10
done
curl -fsS --max-time 300 "https://$FQDN/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{
    "model": "'"$MODEL"'", "temperature": 0, "max_tokens": 100,
    "response_format": {"type": "json_object"},
    "messages": [
      {"role": "system", "content": "Return ONLY JSON {\"sentence_ids\":[...]}: the IDs, taken from answer_ids, of the answer_sentences that answer the question."},
      {"role": "user", "content": "{\"answer_sentences\": {\"rain\": \"Kenya: 40 mm of rain.\", \"maps\": \"Maps are in the bulletin.\"}, \"answer_ids\": [\"rain\", \"maps\"], \"question\": \"How much rain will Kenya get?\"}"}
    ]}' | python3 -c '
import json, sys
reply = json.load(sys.stdin)["choices"][0]["message"]["content"]
print("The model answered a test request:", reply)
' || {
  echo "The model did not answer yet. Check: az containerapp logs show -n $LLM_APP -g $GROUP --follow"
  echo "Then run this script again; the backend is not changed until the model answers."
  exit 1
}

step "Redeploying the backend with the self-hosted model for the Copilot"
# CPU servers are slower than hosted endpoints: a longer wait and a shorter conversation
# window. The key reaches the backend only as an app secret.
LLM_OVERRIDES=$(FQDN="$FQDN" KEY="$KEY" MODEL="$MODEL" python3 -c '
import json, os
e = os.environ
print(json.dumps({
    "env": [
        {"name": "LLM_PROVIDER", "value": "openai_compatible"},
        {"name": "LLM_BASE_URL", "value": "https://" + e["FQDN"] + "/v1"},
        {"name": "LLM_MODEL", "value": e["MODEL"]},
        {"name": "LLM_API_KEY", "secretRef": "llm-api-key"},
        {"name": "LLM_TIMEOUT_SECONDS", "value": "120"},
        {"name": "LLM_HISTORY_MESSAGES", "value": "4"},
        {"name": "LLM_WARM_UP", "value": "true"},
    ],
    "secrets": [{"name": "llm-api-key", "value": e["KEY"]}],
}))')
# Always the current backend.sh: an older copy would keep the earlier Copilot settings.
curl -fsSL "$BACKEND_SCRIPT" -o "$BACKEND"
LOCATION="$LOCATION" GROUP="$GROUP" APP="$APP" ENVIRONMENT="$ENVIRONMENT" \
  LLM_OVERRIDES="$LLM_OVERRIDES" bash "$BACKEND"

cat <<EOF

The Copilot now uses Qwen3-4B-Instruct at https://$FQDN (key held by both apps).
Answers that need the model show "openai_compatible"; most answers need no model call.
Remove the model later with: az containerapp delete --name $LLM_APP --resource-group $GROUP
(then set the backend's LLM_PROVIDER back to mock or Groq, see docs/groq-setup.md).
EOF
