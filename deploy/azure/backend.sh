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
# Students subscriptions. Running the script again updates the app to the latest image.
#
# Settings (environment variables, all optional):
#   LOCATION      Azure region (default southafricanorth). Azure for Students allows a fixed
#                 list of regions; if this one is refused, rerun with an allowed one.
#   DATABASE_URL  PostgreSQL connection string, e.g. Supabase's (paste it as Supabase shows
#                 it, with your password). Without it the database lives inside the
#                 container and is emptied whenever the app restarts or scales to zero.
#   SYNTHETIC     "true" (default) allows labelled synthetic test forecasts; set "false" once
#                 real ECMWF input is connected.
#   IMAGE         Container image (default ghcr.io/joe254h/icpac-backend:latest).
#   GROUP, APP, ENVIRONMENT  Resource names (defaults icpac, icpac-api, icpac-env).
set -euo pipefail

LOCATION=${LOCATION:-southafricanorth}
GROUP=${GROUP:-icpac}
APP=${APP:-icpac-api}
ENVIRONMENT=${ENVIRONMENT:-icpac-env}
IMAGE=${IMAGE:-ghcr.io/joe254h/icpac-backend:latest}
SYNTHETIC=${SYNTHETIC:-true}
DATABASE_URL=${DATABASE_URL:-}
SHARE=forecast-data
STORAGE_LINK=forecast-data
MOUNT=/mnt/data

step() { printf '\n==> %s\n' "$*"; }

step "Subscription"
az account show --query "{subscription:name, user:user.name}" --output table

step "Registering resource providers (first run only; can take a few minutes)"
for namespace in Microsoft.App Microsoft.OperationalInsights Microsoft.Storage; do
  az provider register --namespace "$namespace" --wait
done

step "Resource group $GROUP in $LOCATION"
if ! az group create --name "$GROUP" --location "$LOCATION" --output none; then
  echo "The region $LOCATION was refused. Azure for Students allows a fixed list of regions;"
  echo "rerun with one of them, for example: LOCATION=westeurope bash backend.sh"
  exit 1
fi

# Storage account names are global: derive one from the subscription so reruns reuse it.
SUFFIX=$(az account show --query id --output tsv | tr -d '-' | cut -c1-12)
STORAGE=${STORAGE:-icpac$SUFFIX}

step "Storage account $STORAGE and file share $SHARE (forecast packages and inputs)"
if ! az storage account show --name "$STORAGE" --resource-group "$GROUP" --output none 2>/dev/null; then
  az storage account create --name "$STORAGE" --resource-group "$GROUP" \
    --location "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false --output none
fi
if ! az storage share-rm show --resource-group "$GROUP" --storage-account "$STORAGE" \
  --name "$SHARE" --output none 2>/dev/null; then
  az storage share-rm create --resource-group "$GROUP" --storage-account "$STORAGE" \
    --name "$SHARE" --quota 20 --output none
fi
KEY=$(az storage account keys list --resource-group "$GROUP" --account-name "$STORAGE" \
  --query "[0].value" --output tsv)

step "Container Apps environment $ENVIRONMENT"
if ! az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" --output none 2>/dev/null; then
  az containerapp env create --name "$ENVIRONMENT" --resource-group "$GROUP" \
    --location "$LOCATION" --output none
fi
az containerapp env storage set --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --storage-name "$STORAGE_LINK" --azure-file-account-name "$STORAGE" \
  --azure-file-account-key "$KEY" --azure-file-share-name "$SHARE" \
  --access-mode ReadWrite --output none
ENVIRONMENT_ID=$(az containerapp env show --name "$ENVIRONMENT" --resource-group "$GROUP" \
  --query id --output tsv)

step "Container app $APP from $IMAGE"
APP_EXISTS=false
KEEP_DATABASE=false
if az containerapp show --name "$APP" --resource-group "$GROUP" --output none 2>/dev/null; then
  APP_EXISTS=true
  # A rerun without DATABASE_URL keeps the database connection stored earlier.
  if [ -z "$DATABASE_URL" ] && [ -n "$(az containerapp secret list --name "$APP" \
    --resource-group "$GROUP" --query "[?name=='database-url'].name" --output tsv)" ]; then
    KEEP_DATABASE=true
  fi
fi
DEFINITION=$(mktemp --suffix .yaml)
trap 'rm -f "$DEFINITION"' EXIT
# JSON is valid YAML; python writes it so passwords need no escaping.
APP="$APP" LOCATION="$LOCATION" ENVIRONMENT_ID="$ENVIRONMENT_ID" IMAGE="$IMAGE" \
  SYNTHETIC="$SYNTHETIC" DATABASE_URL="$DATABASE_URL" KEEP_DATABASE="$KEEP_DATABASE" \
  STORAGE_LINK="$STORAGE_LINK" MOUNT="$MOUNT" python3 - "$DEFINITION" <<'PY'
import json
import os
import sys
import time

e = os.environ
env = [
    {"name": "ALLOW_SYNTHETIC_FORECASTS", "value": e["SYNTHETIC"]},
    {"name": "AUTO_REGISTER_MODELS", "value": "true"},
    {"name": "RUN_ROOT", "value": e["MOUNT"]},
    {"name": "FORECAST_INPUT_ROOT", "value": e["MOUNT"] + "/inputs/ecmwf"},
    {"name": "DATA_ROOT", "value": e["MOUNT"] + "/inputs/chirps"},
    # Azure Files (SMB) does not support the HDF5 file locks used by NetCDF writers.
    {"name": "HDF5_USE_FILE_LOCKING", "value": "FALSE"},
]
secrets = []
if e["DATABASE_URL"]:
    secrets.append({"name": "database-url", "value": e["DATABASE_URL"]})
elif e["KEEP_DATABASE"] == "true":
    secrets.append({"name": "database-url"})  # the update keeps the stored value
if secrets:
    env.append({"name": "DATABASE_URL", "secretRef": "database-url"})
definition = {
    "location": e["LOCATION"],
    "properties": {
        "managedEnvironmentId": e["ENVIRONMENT_ID"],
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
                    "resources": {"cpu": 2.0, "memory": "4Gi"},
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
                    "volumeMounts": [{"volumeName": "data", "mountPath": e["MOUNT"]}],
                }
            ],
            # One replica: forecasts run one at a time and the app keeps one database.
            "scale": {"minReplicas": 0, "maxReplicas": 1},
            "volumes": [
                {
                    "name": "data",
                    "storageType": "AzureFile",
                    "storageName": e["STORAGE_LINK"],
                    # The image runs as user 1000 (climate).
                    "mountOptions": "dir_mode=0777,file_mode=0777,uid=1000,gid=1000",
                }
            ],
        },
    },
}
with open(sys.argv[1], "w") as stream:
    json.dump(definition, stream, indent=2)
PY
if [ "$APP_EXISTS" = true ]; then
  az containerapp update --name "$APP" --resource-group "$GROUP" --yaml "$DEFINITION" --output none
else
  az containerapp create --name "$APP" --resource-group "$GROUP" --yaml "$DEFINITION" --output none
fi
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
