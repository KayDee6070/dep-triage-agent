#!/usr/bin/env bash
# Deploy the service to Azure Container Apps.
#
# STATUS: committed as cloud-deployment evidence, NOT the live demo, and
# honestly labelled as such in the README. Hugging Face Spaces carries the
# public link because it needs no card and therefore cannot die of billing.
#
# Azure Container Apps has a real monthly free grant, but the account still
# requires a payment method on file. That is a liability the project explicitly
# declined to take on for a six-month-plus demo link, so the live deployment
# target is Spaces and this script exists because the target job ads name Azure.
#
# An unrun script is weak evidence. If it has not been executed, say so rather
# than implying otherwise — the README does.
#
#   az login
#   RESOURCE_GROUP=dep-triage-rg ./deploy/azure.sh          # dry run
#   RESOURCE_GROUP=dep-triage-rg ./deploy/azure.sh --confirm
#
# Running this provisions billable resources. Delete them afterwards with the
# teardown command printed at the end.

set -euo pipefail

CONFIRM=0
[[ "${1:-}" == "--confirm" ]] && CONFIRM=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RESOURCE_GROUP="${RESOURCE_GROUP:-dep-triage-rg}"
LOCATION="${LOCATION:-westeurope}"
APP_NAME="${APP_NAME:-dep-triage-agent}"
ENVIRONMENT="${ENVIRONMENT:-dep-triage-env}"

# Scale to zero. An idle demo should cost nothing, and the first request paying
# a cold start is the correct trade for a portfolio link.
MIN_REPLICAS="${MIN_REPLICAS:-0}"
MAX_REPLICAS="${MAX_REPLICAS:-1}"
CPU="${CPU:-0.5}"
MEMORY="${MEMORY:-1.0Gi}"

if ! command -v az >/dev/null 2>&1; then
  echo "azure-cli is not installed. See https://aka.ms/InstallAzureCLI" >&2
  exit 1
fi

if [[ ! -f results/report.html ]]; then
  echo "results/report.html is missing. Build it first:" >&2
  echo "  uv run dep-triage report --output results/report.html" >&2
  exit 1
fi

cat <<EOF
Azure Container Apps deployment plan
  resource group : $RESOURCE_GROUP
  location       : $LOCATION
  environment    : $ENVIRONMENT
  app            : $APP_NAME
  replicas       : $MIN_REPLICAS..$MAX_REPLICAS   (scale to zero when idle)
  resources      : ${CPU} vCPU / ${MEMORY}
  ingress        : external, target port 8000
  source build   : this directory, via the committed Dockerfile

Not configured here, deliberately:
  - no model credential. Set DEP_TRIAGE_LLM_* as container-app secrets after
    deploying, or leave them unset: /ask then returns 503 with a notice and the
    evaluation report still serves.
EOF

if [[ $CONFIRM -eq 0 ]]; then
  cat <<'EOF'

DRY RUN — nothing was provisioned.

This creates billable Azure resources. The free grant usually covers an
idle scale-to-zero app, but a payment method must be on file and overage is
possible. Re-run with --confirm to proceed.
EOF
  exit 0
fi

az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
az containerapp env create \
  --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" --output none

# `up` builds the image from this directory and deploys it in one step, which
# avoids standing up a container registry purely to hold one demo image.
az containerapp up \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT" \
  --source . \
  --target-port 8000 \
  --ingress external \
  --output none

az containerapp update \
  --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --min-replicas "$MIN_REPLICAS" --max-replicas "$MAX_REPLICAS" \
  --cpu "$CPU" --memory "$MEMORY" --output none

FQDN="$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn --output tsv)"

cat <<EOF

Deployed: https://$FQDN
  report : https://$FQDN/
  health : https://$FQDN/health
  metrics: https://$FQDN/metrics

Tear down when finished, or it keeps consuming the free grant:
  az group delete --name $RESOURCE_GROUP --yes --no-wait
EOF
