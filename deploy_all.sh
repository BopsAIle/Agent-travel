#!/bin/bash

set -e

DOCKER_USER="berkayalkn"
TAG="v1"
PROJECT_NAME="travel-agent-project"

echo "AI Travel Agent -  DEPLOYMENT SCRIPT STARTING..."
echo "--------------------------------------------------"

echo "Checking OpenShift connection..."
if ! oc whoami > /dev/null 2>&1; then
  echo "Not logged in. Please login first:"
  echo "   oc login -u developer -p developer https://api.crc.testing:6443"
  exit 1
fi
echo "Connection successful."


echo "Preparing project namespace..."
if oc get project $PROJECT_NAME > /dev/null 2>&1; then
    echo "Project '$PROJECT_NAME' already exists. Delete for a clean install? (y/n)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])+$ ]]; then
        echo "Deleting existing project (this may take a minute)..."
        oc delete project $PROJECT_NAME --wait=true
        
        while oc get project $PROJECT_NAME > /dev/null 2>&1; do
            echo "... deleting (please wait)"
            sleep 5
        done
        
        echo "Creating new project: $PROJECT_NAME"
        oc new-project $PROJECT_NAME
    else
        echo "Continuing with existing project."
        oc project $PROJECT_NAME
    fi
else
    echo "🆕 Creating new project: $PROJECT_NAME"
    oc new-project $PROJECT_NAME
fi


echo "Setting up Infrastructure (Secrets & Storage)..."

if [ -f "server/.env" ]; then
    oc delete secret backend-secrets --ignore-not-found
    oc create secret generic backend-secrets --from-env-file=server/.env
    echo "Secret 'backend-secrets' created."
else
    echo "ERROR: server/.env file not found!"
    exit 1
fi

if ! oc get pvc travel-output-pvc > /dev/null 2>&1; then
    echo "apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: travel-output-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi" | oc apply -f -
    echo "PVC 'travel-output-pvc' created."
fi

if [ -f "openshift/monitoring/monitoring-storage.yaml" ]; then
    oc apply -f openshift/monitoring/monitoring-storage.yaml
    echo "Monitoring PVCs created."
else
    echo "WARNING: openshift/monitoring/monitoring-storage.yaml not found, monitoring data may not persist."
fi

echo "Processing Microservices (Build -> Push -> Deploy)..."

services=(
  "server/services/flight-service travel-flight-service openshift/microservices/flight-service.yaml"
  "server/services/hotel-service travel-hotel-service openshift/microservices/hotel-service.yaml"
  "server/services/activity-service travel-activity-service openshift/microservices/activity-service.yaml"
  "server/services/geocoding-service travel-geocoding-service openshift/microservices/geocoding-service.yaml"
  "server/services/event-service travel-event-service openshift/microservices/event-service.yaml"
)

for service in "${services[@]}"; do
  set -- $service
  folder=$1
  name=$2
  yaml=$3
  
  image_name="$DOCKER_USER/$name:$TAG"
  
  echo "Processing: $name"
  
  docker build -t $image_name $folder > /dev/null
  docker push $image_name > /dev/null
  oc apply -f $yaml
  
  oc set resources deployment $name --requests=memory=32Mi,cpu=20m
  
  echo "Done."
done


echo "Processing Orchestrator (Backend)..."
docker build -t $DOCKER_USER/travel-orchestrator:$TAG server > /dev/null
docker push $DOCKER_USER/travel-orchestrator:$TAG > /dev/null
oc apply -f openshift/backend.yaml


oc set resources deployment travel-orchestrator --requests=memory=64Mi,cpu=50m

echo "Waiting for Backend Route URL..."
sleep 5
while [ -z "$(oc get route travel-orchestrator-route -o jsonpath='{.spec.host}' 2>/dev/null)" ]; do
    echo "   ... waiting for route"
    sleep 3
done

BACKEND_URL="http://$(oc get route travel-orchestrator-route -o jsonpath='{.spec.host}')"
echo "Backend URL Discovered: $BACKEND_URL"


echo "Processing Frontend (Injecting URL)..."
docker build --build-arg VITE_API_URL=$BACKEND_URL -t $DOCKER_USER/travel-frontend:$TAG client > /dev/null
docker push $DOCKER_USER/travel-frontend:$TAG > /dev/null
oc apply -f openshift/frontend.yaml

oc set resources deployment travel-frontend --requests=memory=32Mi,cpu=20m

echo "Setting up Monitoring (Prometheus & Grafana)..."

oc apply -f openshift/monitoring/prometheus-config.yaml || true
oc apply -f openshift/monitoring/prometheus-deployment.yaml || true
oc apply -f openshift/monitoring/grafana-deployment.yaml || true

oc set resources deployment prometheus --requests=memory=32Mi,cpu=20m || true
oc set resources deployment grafana --requests=memory=32Mi,cpu=20m || true

echo "--------------------------------------------------"
echo "DEPLOYMENT SUCCESSFUL!"
echo "--------------------------------------------------"
echo "Frontend Access: http://$(oc get route travel-frontend-route -o jsonpath='{.spec.host}')"
echo "Grafana Access:  http://$(oc get route grafana-route -o jsonpath='{.spec.host}')"
echo "--------------------------------------------------"