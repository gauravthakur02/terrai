from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal

BackendType = Literal[
    "local", "azurerm", "s3", "gcs", "pg", "consul", "kubernetes", "http"
]

BACKEND_DISPLAY = {
    "local":      ("🗂️",  "Local filesystem",         "No sharing — single user/machine"),
    "azurerm":    ("☁️",  "Azure Blob Storage",        "Shared, cloud-managed, MSI/SPN auth"),
    "s3":         ("🟠",  "AWS S3 + DynamoDB lock",    "Shared, cloud-managed, IAM auth"),
    "gcs":        ("🔵",  "Google Cloud Storage",      "Shared, cloud-managed, SA auth"),
    "pg":         ("🐘",  "PostgreSQL (self-hosted)",  "Shared, open-source, SQL-based"),
    "consul":     ("🔶",  "HashiCorp Consul",          "Shared, service-mesh native"),
    "kubernetes": ("⎈",   "Kubernetes Secret",         "K8s-native, namespace-scoped"),
    "http":       ("🌐",  "HTTP backend",              "Generic REST — bring your own"),
}


@dataclass
class BackendConfig:
    type: BackendType
    params: dict = field(default_factory=dict)
    environment: str = "default"
    encrypt: bool = True

    def to_hcl(self) -> str:
        """Generate terraform backend block HCL."""
        lines = ["terraform {", f'  backend "{self.type}" {{']
        for k, v in self.params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                lines.append(f"    {k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"    {k} = {v}")
            else:
                lines.append(f'    {k} = "{v}"')
        lines += ["  }", "}"]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"type": self.type, "params": self.params, "environment": self.environment, "encrypt": self.encrypt}

    @classmethod
    def from_dict(cls, d: dict) -> "BackendConfig":
        return cls(
            type=d["type"],
            params=d.get("params", {}),
            environment=d.get("environment", "default"),
            encrypt=d.get("encrypt", True),
        )


class BackendBuilder:
    """Builds BackendConfig from user-provided parameters."""

    @staticmethod
    def local(path: str = "./terraform.tfstate") -> BackendConfig:
        return BackendConfig(type="local", params={"path": path})

    @staticmethod
    def azurerm(
        resource_group: str,
        storage_account: str,
        container: str = "tfstate",
        key: str = "terraform.tfstate",
        use_msi: bool = False,
        subscription_id: str = "",
        tenant_id: str = "",
        client_id: str = "",
    ) -> BackendConfig:
        params: dict = {
            "resource_group_name": resource_group,
            "storage_account_name": storage_account,
            "container_name": container,
            "key": key,
        }
        if use_msi:
            params["use_msi"] = True
        if subscription_id:
            params["subscription_id"] = subscription_id
        if tenant_id:
            params["tenant_id"] = tenant_id
        if client_id:
            params["client_id"] = client_id
        return BackendConfig(type="azurerm", params=params)

    @staticmethod
    def s3(
        bucket: str,
        key: str = "terraform/terraform.tfstate",
        region: str = "us-east-1",
        dynamodb_table: str = "",
        encrypt: bool = True,
        profile: str = "",
    ) -> BackendConfig:
        params: dict = {
            "bucket": bucket,
            "key": key,
            "region": region,
            "encrypt": encrypt,
        }
        if dynamodb_table:
            params["dynamodb_table"] = dynamodb_table
        if profile:
            params["profile"] = profile
        return BackendConfig(type="s3", params=params, encrypt=encrypt)

    @staticmethod
    def gcs(bucket: str, prefix: str = "terraform/state") -> BackendConfig:
        return BackendConfig(type="gcs", params={"bucket": bucket, "prefix": prefix})

    @staticmethod
    def pg(conn_str: str = "", schema_name: str = "terraform_state") -> BackendConfig:
        params: dict = {"schema_name": schema_name}
        if conn_str:
            params["conn_str"] = conn_str
        return BackendConfig(type="pg", params=params)

    @staticmethod
    def consul(address: str, path: str = "terraform", scheme: str = "http") -> BackendConfig:
        return BackendConfig(type="consul", params={"address": address, "path": path, "scheme": scheme})

    @staticmethod
    def kubernetes(secret_suffix: str, namespace: str = "default", config_path: str = "") -> BackendConfig:
        params: dict = {"secret_suffix": secret_suffix, "namespace": namespace}
        if config_path:
            params["config_path"] = config_path
        return BackendConfig(type="kubernetes", params=params)

    @staticmethod
    def http(address: str, lock_address: str = "", unlock_address: str = "", username: str = "", password: str = "") -> BackendConfig:
        params: dict = {"address": address}
        if lock_address:
            params["lock_address"] = lock_address
        if unlock_address:
            params["unlock_address"] = unlock_address
        if username:
            params["username"] = username
        return BackendConfig(type="http", params=params)
