#!/usr/bin/env bash
# Deploy the ICPAC backend (FastAPI + MBC + Atmos37 CatBoost) to Azure Container Apps.
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
#   DATABASE_URL  PostgreSQL connection string, e.g. Supabase's (paste it as Supabase shows
#                 it, with your password). Without it the database lives inside the
#                 container and is emptied whenever the app restarts or scales to zero.
#   SYNTHETIC     "true" (default) allows labelled synthetic test forecasts; set "false" once
#                 real ECMWF input is connected.
#   IMAGE         Container image (default ghcr.io/joe254h/icpac-backend:latest).
#   CPU, MEMORY   Container size (default 2 and 4Gi; a full-grid forecast needs about 1 GB).
#   GROUP, APP, ENVIRONMENT  Resource names (defaults icpac, icpac-api, icpac-env).
set -euo pipefail

LOCATION=${LOCATION:-southafricanorth}
GROUP=${GROUP:-icpac}
APP=${APP:-icpac-api}
ENVIRONMENT=${ENVIRONMENT:-icpac-env}
IMAGE=${IMAGE:-ghcr.io/joe254h/icpac-backend:latest}
SYNTHETIC=${SYNTHETIC:-true}
DATABASE_URL=${DATABASE_URL:-}
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

step "Resource group $GROUP in $LOCATION"
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

step "Container app $APP from $IMAGE"
KEEP_DATABASE=false
if az containerapp show --name "$APP" --resource-group "$GROUP" --output none 2>/dev/null; then
  # A rerun without DATABASE_URL keeps the database connection stored earlier.
  if [ -z "$DATABASE_URL" ]; then
    DATABASE_URL=$(az containerapp secret list --name "$APP" --resource-group "$GROUP" \
      --show-values --query "[?name=='database-url'].value | [0]" --output tsv)
    [ -n "$DATABASE_URL" ] && KEEP_DATABASE=true
  fi
fi
DEFINITION=$(mktemp --suffix .json)
trap 'rm -f "$DEFINITION"' EXIT
# The definition goes to the Azure API as it is (az rest): the CLI's create path adds null
# fields that express environments reject. Python writes it so passwords need no escaping.
APP="$APP" LOCATION="$LOCATION" ENVIRONMENT_ID="$ENVIRONMENT_ID" IMAGE="$IMAGE" \
  SYNTHETIC="$SYNTHETIC" DATABASE_URL="$DATABASE_URL" \
  CONNECTION="$CONNECTION" PACKAGES="$PACKAGES" CPU="$CPU" MEMORY="$MEMORY" \
  python3 - "$DEFINITION" <<'PY'
import json
import os
import sys
import time

e = os.environ
env = [
    {"name": "ALLOW_SYNTHETIC_FORECASTS", "value": e["SYNTHETIC"]},
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
definition = {
    "location": e["LOCATION"],
    "properties": {
        "environmentId": e["ENVIRONMENT_ID"],
        "configuration": {
            "activeRevisionsMode": "Single",
            "ingress": {"external": True, "targetPort": 8000, "transport": "auto"},
            "secrets": secrets,
        },
        "template": {
            # A new suffix makes every run a new revision, which pulls the latest image.
            "revisionSuffix": time.strftime("r%Y%m%d%H%M%S"),
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

step "Waiting for the API to start (first start pulls the image and loads the model)"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 20 "https://$FQDN/health" > /dev/null 2>&1; then
    break
  fi
  sleep 10
done
curl -fsS --max-time 60 "https://$FQDN/health" | python3 -c '
import json, sys
health = json.load(sys.stdin)
print("Status:", health["status"])
for name, value in health["components"].items():
    if name.startswith(("Operational", "Model", "Database", "Storage")):
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
