#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "Error: Please provide the service name to update."
  echo "Usage: ./update_service.sh [service-name] [optional-tag]"
  echo "Examples:"
  echo "  ./update_service.sh flight-service"
  echo "  ./update_service.sh flight-service v2"
  exit 1
fi

SERVICE_NAME=$1
NEW_TAG=${2:-latest} 
DOCKER_USER="berkayalkn"

if [[ "$SERVICE_NAME" != travel-* ]]; then
    FULL_SERVICE_NAME="travel-$SERVICE_NAME"
    SHORT_SERVICE_NAME="$SERVICE_NAME"
else
    FULL_SERVICE_NAME="$SERVICE_NAME"
    SHORT_SERVICE_NAME="${SERVICE_NAME#travel-}"
fi

if [ "$SHORT_SERVICE_NAME" == "orchestrator" ]; then
    DOCKER_CONTEXT="server"
elif [ "$SHORT_SERVICE_NAME" == "frontend" ]; then
    DOCKER_CONTEXT="client"
else
    DOCKER_CONTEXT="server/services/$SHORT_SERVICE_NAME"
fi

IMAGE_NAME="$DOCKER_USER/$FULL_SERVICE_NAME:$NEW_TAG"

echo "Updating Service: $FULL_SERVICE_NAME"
echo "Source Folder: $DOCKER_CONTEXT"
echo "Target Image: $IMAGE_NAME"

echo "Building..."

if [ "$SHORT_SERVICE_NAME" == "frontend" ]; then
    BACKEND_URL="http://$(oc get route travel-orchestrator-route -o jsonpath='{.spec.host}')"
    echo "Backend URL: $BACKEND_URL"
    docker build --build-arg VITE_API_URL=$BACKEND_URL -t $IMAGE_NAME $DOCKER_CONTEXT
else
    docker build -t $IMAGE_NAME $DOCKER_CONTEXT
fi

echo "Pushing..."
docker push $IMAGE_NAME

echo "Deploying to OpenShift..."
DEPLOYMENT_NAME=$FULL_SERVICE_NAME


if [ "$SHORT_SERVICE_NAME" == "orchestrator" ]; then
    CONTAINER_NAME="orchestrator" 
elif [ "$SHORT_SERVICE_NAME" == "frontend" ]; then
    CONTAINER_NAME="frontend" 
else
    CONTAINER_NAME="$SHORT_SERVICE_NAME" 
fi

echo "Target: Deployment=$DEPLOYMENT_NAME, Container=$CONTAINER_NAME"

oc set image deployment/$DEPLOYMENT_NAME $CONTAINER_NAME=$IMAGE_NAME

echo "Monitoring rollout status..."
oc rollout status deployment/$DEPLOYMENT_NAME

echo "$FULL_SERVICE_NAME successfully updated!"