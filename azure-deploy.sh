#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Azure Container Apps — deploy script for Quant Model
#
# Prerequisites:
#   brew install azure-cli
#   az login
#
# Usage:
#   chmod +x azure-deploy.sh
#   ./azure-deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration — edit these ────────────────────────────────────────────────
APP_NAME="quant-model"
RESOURCE_GROUP="quant-model-rg"
LOCATION="westeurope"
ACR_NAME="quantmodelregistry"          # must be globally unique, lowercase, no hyphens
ENVIRONMENT_NAME="quant-model-env"
IMAGE_TAG="latest"

# ── Derived ───────────────────────────────────────────────────────────────────
IMAGE="${ACR_NAME}.azurecr.io/${APP_NAME}:${IMAGE_TAG}"

echo "==> [1/7] Creating resource group: ${RESOURCE_GROUP}"
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

echo "==> [2/7] Creating Azure Container Registry: ${ACR_NAME}"
az acr create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --sku Basic \
  --admin-enabled true \
  --output none

echo "==> [3/7] Logging in to ACR"
az acr login --name "${ACR_NAME}"

echo "==> [4/7] Building and pushing Docker image"
docker build -t "${IMAGE}" .
docker push "${IMAGE}"

echo "==> [5/7] Creating Container Apps environment"
az containerapp env create \
  --name "${ENVIRONMENT_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

echo "==> [6/7] Deploying Container App"
# Read ACR credentials
ACR_USERNAME=$(az acr credential show --name "${ACR_NAME}" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "${ACR_NAME}" --query "passwords[0].value" -o tsv)

az containerapp create \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --environment "${ENVIRONMENT_NAME}" \
  --image "${IMAGE}" \
  --registry-server "${ACR_NAME}.azurecr.io" \
  --registry-username "${ACR_USERNAME}" \
  --registry-password "${ACR_PASSWORD}" \
  --target-port 8501 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
      SAXO_ENV=sim \
  --output none

echo "==> [7/7] Deployment complete"
APP_URL=$(az containerapp show \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv)

echo ""
echo "  App URL:  https://${APP_URL}"
echo ""
echo "  To add secrets (SAXO_ACCESS_TOKEN etc.) run:"
echo "  az containerapp secret set \\"
echo "    --name ${APP_NAME} \\"
echo "    --resource-group ${RESOURCE_GROUP} \\"
echo "    --secrets saxo-token=<your-token>"
echo ""
echo "  Then reference it in the container env:"
echo "  az containerapp update \\"
echo "    --name ${APP_NAME} \\"
echo "    --resource-group ${RESOURCE_GROUP} \\"
echo "    --set-env-vars SAXO_ACCESS_TOKEN=secretref:saxo-token"
