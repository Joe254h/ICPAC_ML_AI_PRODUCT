#!/usr/bin/env bash
# Deploy the ICPAC backend (FastAPI, ECMWF Open Data and CHIRPS downloads, MBC and the
# Atmos37 CatBoost registry) to Azure Container Apps.
#
# Run it in Azure Cloud Shell (Bash) at https://shell.azure.com:
#
#   curl -fsSL https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/main/deploy/azure/backend.sh -o backend.sh
#   bash backend.sh
#
# The image comes from the GitHub Container Registry (built by the "Publish backend image"
# workflow), so nothing is built in Azure: registry builds are not available on Azure for
# Students subscriptions. Product packages (NetCDF, maps, countries, verification) are kept
# in Blob Storage, so the app needs no mounted disk: Azure for Students creates "express"
# Container Apps environments, which cannot mount Azure Files. Running the script again
# updates the app to the latest image.
#
# Settings (environment variables, all optional):
#   LOCATION      Azure region (default southafricanorth). Azure for Students allows a fixed
#                 list of regions; if this one is refused, rerun with an allowed one. List them:
#                 az policy assignment list --disable-scope-strict-match \
#                   --query "[].parameters.listOfAllowedLocations.value" -o tsv
#                 Reruns use the region of the existing Container Apps environment.
#   DATABASE_URL  PostgreSQL connection string, e.g. Supabase's (paste it as Supabase shows
#                 it, with your password). Without it the database lives inside the
#                 container and is emptied whenever the app restarts or scales to zero.
#   IMAGE         Container image (default ghcr.io/joe254h/icpac-backend:latest).
#   CPU, MEMORY   Container size (default 2 and 4Gi; a full-grid forecast needs about 1 GB).
#   GROUP, APP, ENVIRONMENT  Resource names (defaults icpac, icpac-api, icpac-env).
#   ANTHROPIC_API_KEY  Optional: the Copilot answers with Claude (Anthropic API) from the
#                 forecast's own data and answers general questions; the key is stored as an
#                 app secret. CLAUDE_MODEL picks the model (default claude-opus-5-5).
#   LLM_OVERRIDES Set by llm.sh: the Copilot settings for the self-hosted model. Without it
#                 (and without ANTHROPIC_API_KEY), the Copilot settings on the app are kept.
set -euo pipefail

LOCATION=${LOCATION:-southafricanorth}
GROUP=${GROUP:-icpac}
APP=${APP:-icpac-api}
ENVIRONMENT=${ENVIRONMENT:-icpac-env}
IMAGE=${IMAGE:-ghcr.io/joe254h/icpac-backend:latest}
DATABASE_URL=${DATABASE_URL:-}
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # Claude replaces every earlier Copilot setting (see docs/chatbot.md).
  LLM_OVERRIDES=$(KEY="$ANTHROPIC_API_KEY" MODEL="${CLAUDE_MODEL:-claude-opus-5-5}" python3 -c '
import json, os
e = os.environ
print(json.dumps({
    "env": [
        {"name": "LLM_PROVIDER", "value": "anthropic"},
        {"name": "LLM_MODEL", "value": e["MODEL"]},
        {"name": "LLM_API_KEY", "secretRef": "llm-api-key"},
        {"name": "LLM_TIMEOUT_SECONDS", "value": "60"},
    ],
    "secrets": [{"name": "llm-api-key", "value": e["KEY"]}],
}))')
fi
CPU=${CPU:-2}
MEMORY=${MEMORY:-4Gi}
PACKAGES=forecast-packages

step() { printf '\n==> %s\n' "$*"; }

step "Subscription"
az account show --query "{subscription:name, user:user.name}" --output table

step "Registering resource providers (first run only; can take a few minutes)"
for namespace in Microsoft.App Microsoft.OperationalInsights Microsoft.Storage; do
  az provider register --namespace "$namespace" --wait
done

step "Resource group $GROUP"
if az group show --name "$GROUP" --output none 2>/dev/null; then
  echo "Using the existing resource group $GROUP"
elif ! az group create --name "$GROUP" --location "$LOCATION" --output none; then
  echo "The region $LOCATION was refused. Azure for Students allows a fixed list of regions:"
  az policy assignment list --disable-scope-strict-match \
    --query "[].parameters.listOfAllowedLocations.value" --output tsv || true
  echo "Rerun with one of them, for example: LOCATION=switzerlandnorth bash backend.sh"
  exit 1
fi

# Storage account names are global: derive one from the subscription so reruns reuse it.
SUFFIX=$(az account show --query id --output tsv | tr -d '-' | cut -c1-12)
STORAGE=${STORAGE:-icpac$SUFFIX}

step "Storage account $STORAGE (forecast packages in the blob container $PACKAGES)"
if ! az storage account show --name "$STORAGE" --resource-group "$GROUP" --output none 2>/dev/null; then
  az storage account create --name "$STORAGE" --resource-group "$GROUP" \
    --location "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false --output none
fi
CONNECTION=$(az storage account show-connection-string --name "$STORAGE" \
  --resource-group "$GROUP" --query connectionString --output tsv)

step "Container Apps environment $ENVIRONMENT"
if ! az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" --output none 2>/dev/null; then
  az containerapp env create --name "$ENVIRONMENT" --resource-group "$GROUP" \
    --location "$LOCATION" --output none
fi
ENVIRONMENT_ID=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --query id --output tsv)
# The app must live in its environment's region, so a rerun takes the region of the
# existing environment whatever LOCATION says (the default may not be allowed for this
# subscription, and an app cannot move region).
ENV_LOCATION=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --query location --output tsv | tr -d ' \r' | tr '[:upper:]' '[:lower:]')
if [ -n "$ENV_LOCATION" ] && [ "$ENV_LOCATION" != "$LOCATION" ]; then
  echo "Using the region of the existing environment: $ENV_LOCATION"
  LOCATION=$ENV_LOCATION
fi

step "Container app $APP from $IMAGE"
KEEP_DATABASE=false
CURRENT_ENV='[]'
CURRENT_SECRETS='[]'
if az containerapp show --name "$APP" --resource-group "$GROUP" --output none 2>/dev/null; then
  # A rerun without DATABASE_URL keeps the database connection stored earlier.
  if [ -z "$DATABASE_URL" ]; then
    DATABASE_URL=$(az containerapp secret list --name "$APP" --resource-group "$GROUP" \
      --show-values --query "[?name=='database-url'].value | [0]" --output tsv)
    [ -n "$DATABASE_URL" ] && KEEP_DATABASE=true
  fi
  # Copilot settings added in the portal (LLM_*, see docs/groq-setup.md) and the secrets
  # they reference are carried over: the update below replaces the whole definition.
  CURRENT_ENV=$(az containerapp show --name "$APP" --resource-group "$GROUP" \
    --query "properties.template.containers[0].env" --output json)
  CURRENT_SECRETS=$(az containerapp secret list --name "$APP" --resource-group "$GROUP" \
    --show-values --output json)
fi
DEFINITION=$(mktemp --suffix .json)
trap 'rm -f "$DEFINITION"' EXIT
# The definition goes to the Azure API as it is (az rest): the CLI's create path adds null
# fields that express environments reject. Python writes it so passwords need no escaping.
APP="$APP" LOCATION="$LOCATION" ENVIRONMENT_ID="$ENVIRONMENT_ID" IMAGE="$IMAGE" \
  DATABASE_URL="$DATABASE_URL" \
  CONNECTION="$CONNECTION" PACKAGES="$PACKAGES" CPU="$CPU" MEMORY="$MEMORY" \
  CURRENT_ENV="$CURRENT_ENV" CURRENT_SECRETS="$CURRENT_SECRETS" \
  LLM_OVERRIDES="${LLM_OVERRIDES:-}" \
  python3 - "$DEFINITION" <<'PY'
import json
import os
import sys
import time

e = os.environ
env = [
    # A changed value makes every run a new revision, which pulls the latest image
    # (express environments do not accept revision suffixes).
    {"name": "DEPLOYED_AT", "value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    {"name": "AUTO_REGISTER_MODELS", "value": "true"},
    # Packages are written to the container disk and copied to Blob Storage, from which a
    # restarted replica fetches them again.
    {"name": "PACKAGE_STORE_CONNECTION", "secretRef": "package-store"},
    {"name": "PACKAGE_STORE_CONTAINER", "value": e["PACKAGES"]},
]
secrets = [{"name": "package-store", "value": e["CONNECTION"]}]
if e["DATABASE_URL"]:
    secrets.append({"name": "database-url", "value": e["DATABASE_URL"]})
    env.append({"name": "DATABASE_URL", "secretRef": "database-url"})
stored = {s["name"]: s.get("value") for s in json.loads(e["CURRENT_SECRETS"] or "[]") or []}
overrides = json.loads(e["LLM_OVERRIDES"] or "null")
if overrides:
    # llm.sh: the self-hosted model replaces every earlier Copilot setting.
    env += overrides["env"]
    secrets += overrides["secrets"]
for setting in [] if overrides else json.loads(e["CURRENT_ENV"] or "[]") or []:
    if not setting.get("name", "").startswith("LLM_"):
        continue
    reference, value = setting.get("secretRef"), setting.get("value")
    if reference:
        if not stored.get(reference):
            print(f"Skipping {setting['name']}: its secret {reference} has no stored value")
            continue
        env.append({"name": setting["name"], "secretRef": reference})
        if reference not in {s["name"] for s in secrets}:
            secrets.append({"name": reference, "value": stored[reference]})
    elif value:
        env.append({"name": setting["name"], "value": value})
    else:
        # Azure refuses a variable without a value; for the app an empty one means unset.
        print(f"Skipping {setting['name']}: it is empty, which the backend treats as unset")
definition = {
    "location": e["LOCATION"],
    "properties": {
        "environmentId": e["ENVIRONMENT_ID"],
        # Only settings express environments support: single revision (built in), HTTP
        # ingress on a fixed port, app secrets, TCP probes, replica limits.
        "configuration": {
            "ingress": {"external": True, "targetPort": 8000},
            "secrets": secrets,
        },
        "template": {
            "containers": [
                {
                    "name": e["APP"],
                    "image": e["IMAGE"],
                    "resources": {"cpu": float(e["CPU"]), "memory": e["MEMORY"]},
                    "env": env,
                    "probes": [
                        # Startup verifies every artifact and loads the model.
                        {
                            "type": "Startup",
                            "tcpSocket": {"port": 8000},
                            "periodSeconds": 10,
                            "failureThreshold": 30,
                        }
                    ],
                }
            ],
            # One replica: forecasts run one at a time and the app keeps one database.
            "scale": {"minReplicas": 0, "maxReplicas": 1},
        },
    },
}
with open(sys.argv[1], "w") as stream:
    json.dump(definition, stream, indent=2)
PY
APP_ID="${ENVIRONMENT_ID%/managedEnvironments/*}/containerApps/$APP"
az rest --method put --url "https://management.azure.com$APP_ID?api-version=2025-07-01" \
  --body "@$DEFINITION" --output none
for _ in $(seq 1 60); do
  STATE=$(az containerapp show --name "$APP" --resource-group "$GROUP" \
    --query properties.provisioningState --output tsv 2>/dev/null || true)
  case "$STATE" in
    Succeeded) break ;;
    Failed | Canceled)
      echo "The container app reported $STATE:"
      az containerapp show --name "$APP" --resource-group "$GROUP" \
        --query "properties.{state:provisioningState, revision:latestRevisionName}" --output table
      exit 1
      ;;
  esac
  sleep 10
done
FQDN=$(az containerapp show --name "$APP" --resource-group "$GROUP" \
  --query properties.configuration.ingress.fqdn --output tsv)
REVISION=$(az containerapp show --name "$APP" --resource-group "$GROUP" \
  --query properties.latestRevisionName --output tsv)

# The previous revision keeps answering until the new one is ready, so wait for Azure to
# report the new revision ready before reading the health of the API.
step "Waiting for the new revision $REVISION (pulls the image, verifies artifacts, loads the model)"
READY=""
for _ in $(seq 1 60); do
  curl -fsS --max-time 20 "https://$FQDN/health" > /dev/null 2>&1 || true
  READY=$(az containerapp show --name "$APP" --resource-group "$GROUP" \
    --query properties.latestReadyRevisionName --output tsv 2>/dev/null || true)
  [ "$READY" = "$REVISION" ] && break
  RUNNING=$(az containerapp revision show --name "$APP" --resource-group "$GROUP" \
    --revision "$REVISION" --query properties.runningState --output tsv 2>/dev/null || true)
  if [ "$RUNNING" = "Failed" ]; then
    break
  fi
  sleep 10
done
if [ "$READY" != "$REVISION" ]; then
  echo "The new revision $REVISION is not ready; the previous version may still be answering."
  az containerapp revision list --name "$APP" --resource-group "$GROUP" --output table || true
  echo "Its startup log: az containerapp logs show -n $APP -g $GROUP --revision $REVISION --tail 80"
fi
curl -fsS --max-time 60 "https://$FQDN/health" | python3 -c '
import json, sys
health = json.load(sys.stdin)
print("Status:", health["status"], "| version:", health.get("version", "previous release"))
for name, value in health["components"].items():
    if name.startswith(("Operational", "Model", "Database", "Storage", "ECMWF", "CHIRPS", "MBC")):
        print(f"  {name}: {value}")
' || echo "The API is not answering yet; check: az containerapp logs show -n $APP -g $GROUP --follow"

if [ -z "$DATABASE_URL" ] && [ "$KEEP_DATABASE" = false ]; then
  echo
  echo "Note: no DATABASE_URL, so the database lives in the container and is emptied when the"
  echo "app scales to zero. Rerun with DATABASE_URL='<Supabase connection string>' to keep it."
fi
cat <<EOF

Backend URL: https://$FQDN
API reference: https://$FQDN/docs
Use the backend URL as API_URL for the Vercel frontend.
Remove everything later with: az group delete --name $GROUP
EOF
