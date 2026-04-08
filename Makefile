SHELL := /bin/bash

.PHONY: help test demo monitor k8s-deploy

help:
	@echo "Available targets:"
	@echo "  make test        - Run the full test suite (includes apps/manager/tests/test_client_sdk_contract.py)"
	@echo "  make demo        - Start the multi-node environment with docker-compose.multi-node.yml"
	@echo "  make monitor     - Start the Prometheus/Grafana stack defined in infra/monitoring/docker-compose.yml"
	@echo "  make k8s-deploy  - Apply Kubernetes manifests in ./infra/k8s and print HPA verification tips"

test:
	cd apps/manager && pytest

demo:
	docker compose -f docker-compose.multi-node.yml up -d

monitor:
	cd infra/monitoring && docker compose up -d

k8s-deploy:
	kubectl apply -f infra/k8s/
	@echo ""
	@echo "Triton Client Manager deployed to Kubernetes using manifests from ./k8s."
	@echo "To verify autoscaling (HPA), run:"
	@echo "  kubectl get hpa triton-client-manager-hpa"
	@echo "  kubectl describe hpa triton-client-manager-hpa"

