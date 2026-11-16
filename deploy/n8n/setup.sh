#!/usr/bin/env bash
# Load the ICPAC workflows and their two credentials into the n8n of docker-compose.yml,
# publish them, and start n8n. Run from the repository root, with n8n stopped:
#
#   export N8N_ENCRYPTION_KEY=...    # 32+ random characters; keep it: n8n needs it later
#   export N8N_WEBHOOK_SECRET=...    # 32+ random characters; the service signs with it
#   export ICPAC_N8N_STAFF_KEY=...   # n8n's operator key in the service's STAFF_CREDENTIALS
#   export SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASSWORD=...   # for the alerts
#   bash deploy/n8n/setup.sh
#
# The keys are passed to the container in its environment and written nowhere on disk.
# Run it again after pulling new workflows: the same ids are replaced, not duplicated.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${N8N_ENCRYPTION_KEY:?set N8N_ENCRYPTION_KEY}"
: "${N8N_WEBHOOK_SECRET:?set N8N_WEBHOOK_SECRET (the service signs its events with it)}"
: "${ICPAC_N8N_STAFF_KEY:?set ICPAC_N8N_STAFF_KEY (an operator key from STAFF_CREDENTIALS)}"
if [ "${#N8N_WEBHOOK_SECRET}" -lt 32 ]; then echo "N8N_WEBHOOK_SECRET needs 32+ characters" >&2; exit 1; fi
if [ "${#N8N_ENCRYPTION_KEY}" -lt 32 ]; then echo "N8N_ENCRYPTION_KEY needs 32+ characters" >&2; exit 1; fi

compose=(docker compose --profile n8n)
"${compose[@]}" stop n8n >/dev/null 2>&1 || true

# Credentials: written inside the container's temporary folder, imported, then deleted.
"${compose[@]}" run --rm --no-deps \
  -e ICPAC_N8N_STAFF_KEY -e SMTP_HOST -e SMTP_PORT -e SMTP_USER -e SMTP_PASSWORD -e SMTP_SECURITY \
  --entrypoint sh n8n -c '
    set -e
    node -e "
      const s = process.env;
      const secure = (s.SMTP_SECURITY || \"starttls\") === \"ssl\";
      console.log(JSON.stringify([
        { id: \"IcpacStaffKey001\", name: \"ICPAC staff key\", type: \"httpHeaderAuth\",
          data: { name: \"Authorization\", value: \"Bearer \" + s.ICPAC_N8N_STAFF_KEY } },
        { id: \"IcpacSmtp0000001\", name: \"ICPAC SMTP\", type: \"smtp\",
          data: { user: s.SMTP_USER || \"\", password: s.SMTP_PASSWORD || \"\",
                  host: s.SMTP_HOST || \"localhost\", port: Number(s.SMTP_PORT || 587),
                  secure, disableStartTls: false } },
      ]));
    " > /tmp/icpac-credentials.json
    n8n import:credentials --input=/tmp/icpac-credentials.json
    rm -f /tmp/icpac-credentials.json
    n8n import:workflow --separate --input=/workflows
    for id in IcpacNotify00005 IcpacErrors00006 IcpacEvents00003 IcpacWeekly00001 IcpacVerify00002 IcpacWatch000004; do
      n8n publish:workflow --id="$id"
    done
  '

# A publish made from the command line is applied when n8n starts.
"${compose[@]}" up -d n8n
echo "n8n is starting on http://localhost:5678. Then send a test event from the service:"
echo "  curl -X POST http://localhost:8000/automations/coordinator/test -H \"Authorization: Bearer <an operator key>\""
