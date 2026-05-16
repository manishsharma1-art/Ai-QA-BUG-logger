#!/bin/bash
# Quick deployment script for bug fixes

set -e

echo "=========================================="
echo "QA Bug Logger - Deploying Timeout Fixes"
echo "=========================================="

# Configuration
PROJECT_ID="your-gcp-project-id"  # UPDATE THIS
REGION="asia-south1"
SERVICE_NAME="qa-bugbot"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo ""
echo "Step 1: Building Docker image..."
docker build -t ${SERVICE_NAME} .

echo ""
echo "Step 2: Tagging image for GCR..."
docker tag ${SERVICE_NAME} ${IMAGE_NAME}:latest
docker tag ${SERVICE_NAME} ${IMAGE_NAME}:$(date +%Y%m%d-%H%M%S)

echo ""
echo "Step 3: Pushing to Google Container Registry..."
docker push ${IMAGE_NAME}:latest

echo ""
echo "Step 4: Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME}:latest \
  --platform managed \
  --region ${REGION} \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10

echo ""
echo "=========================================="
echo "✅ Deployment complete!"
echo "=========================================="
echo ""
echo "Verify deployment:"
echo "  gcloud run services describe ${SERVICE_NAME} --region ${REGION}"
echo ""
echo "Check logs:"
echo "  gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --limit 50"
echo ""
echo "Test health endpoint:"
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format='value(status.url)')
echo "  curl ${SERVICE_URL}/health"
echo ""
