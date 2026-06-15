"""Provider-specific helpers and HCL snippets."""

AZURE_PROVIDER_BLOCK = """\
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "tags" {
  description = "Common resource tags"
  type        = map(string)
  default = {
    managed_by  = "TerraAI"
    environment = "dev"
  }
}
"""

AWS_PROVIDER_BLOCK = """\
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}
"""

GCP_PROVIDER_BLOCK = """\
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}
"""

PROVIDER_BLOCKS = {
    "azure": AZURE_PROVIDER_BLOCK,
    "aws": AWS_PROVIDER_BLOCK,
    "gcp": GCP_PROVIDER_BLOCK,
}
