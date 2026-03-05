SHELL := /bin/bash

.PHONY: help test demo monitor k8s-deploy

help:
	@echo "Targets disponibles:"
	@echo "  make test        - Ejecuta la suite completa de tests (incluye MANAGER/tests/test_client_sdk_contract.py)"
	@echo "  make demo        - Levanta el entorno multi-nodo con docker-compose.multi-node.yml"
	@echo "  make monitor     - Levanta el stack de Prometheus/Grafana definido en monitoring/docker-compose.yml"
	@echo "  make k8s-deploy  - Aplica los manifests de Kubernetes en ./k8s y muestra un mensaje de verificación del HPA"

test:
	cd MANAGER && pytest

demo:
	docker compose -f docker-compose.multi-node.yml up -d

monitor:
	cd monitoring && docker compose up -d

k8s-deploy:
	kubectl apply -f k8s/
	@echo ""
	@echo "Triton Client Manager desplegado en Kubernetes con manifests de ./k8s."
	@echo "Para verificar el autoscaling (HPA), ejecuta:"
	@echo "  kubectl get hpa triton-client-manager-hpa"
	@echo "  kubectl describe hpa triton-client-manager-hpa"

