from typing import Any, Dict, List, Optional


class ServiceEndpoint:
    """Represents an OpenStack service endpoint"""

    def __init__(
        self,
        name: str,
        service_id: str,
        service_type: str,
        endpoint_public: Optional[str] = None,
        endpoint_internal: Optional[str] = None,
    ):

        self.id = service_id
        self.name = name
        self.type = service_type
        self.endpoint_public = endpoint_public
        self.endpoint_internal = endpoint_internal

    def __repr__(self) -> str:
        return f"{self.type}({self.name})"


class Catalog:
    """Parses and stores OpenStack service catalog"""

    def __init__(self, catalog_data: List[Dict[str, Any]], region: str = "RegionOne"):
        """
        Initialize catalog from OpenStack auth response.

        Args:
            catalog_data: List of service dictionaries from token response
            region: OpenStack region to use (default: RegionOne)
        """
        self.region = region
        self.services: Dict[str, ServiceEndpoint] = {}

        # Parse catalog and create service endpoints
        self._parse_catalog(catalog_data)

        # Service shortcuts (direct property access)
        self.image = self.services.get("image")
        self.panel = self.services.get("panel")
        self.metric = self.services.get("metric")
        self.compute = self.services.get("compute")
        self.network = self.services.get("network")
        self.identity = self.services.get("identity")
        self.placement = self.services.get("placement")
        self.orchestration = self.services.get("orchestration")
        self.cloudformation = self.services.get("cloudformation")
        self.container_infra = self.services.get("container-infra")

    # --------------- PARSING ---------------
    def _parse_catalog(self, catalog_data: List[Dict[str, Any]]):
        """Parse catalog data and create service endpoint instances"""
        for service in catalog_data:
            endpoints = service.get("endpoints", [])
            service_id = service.get("id")
            service_type = service.get("type")
            service_name = service.get("name")

            # Extract internal and public endpoints for the specified region
            endpoint_public = None
            endpoint_internal = None

            for endpoint in endpoints:
                if endpoint.get("region") == self.region:
                    interface = endpoint.get("interface")
                    url = endpoint.get("url")

                    if interface == "internal":
                        endpoint_internal = url
                    elif interface == "public":
                        endpoint_public = url

            # Create service endpoint and store it
            if service_type:
                service_endpoint = ServiceEndpoint(
                    name=service_name,
                    service_id=service_id,
                    service_type=service_type,
                    endpoint_public=endpoint_public,
                    endpoint_internal=endpoint_internal,
                )
                self.services[service_type] = service_endpoint

    # --------------- UTILS ---------------
    def get_service(self, service_type: str) -> Optional[ServiceEndpoint]:
        """Get a service endpoint by type"""
        return self.services.get(service_type)

    def __repr__(self) -> str:
        service_names = [f"{svc.type}" for svc in self.services.values()]
        return f"Catalog(region={self.region}, services=[{', '.join(service_names)}])"
