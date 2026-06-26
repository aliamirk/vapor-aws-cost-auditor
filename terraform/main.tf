##############################################################################
# Vapor Test Infrastructure — Deliberately Wasteful AWS Resources
#
# This creates resources that Vapor will flag:
# - Unattached EBS volumes (various types/sizes)
# - Unassociated Elastic IPs
# - S3 buckets without lifecycle policies
# - Lambda functions with excessive memory/timeout
# - RDS instance that will be underutilized
#
# WARNING: This will incur real AWS costs. Destroy after testing.
# terraform destroy -auto-approve
##############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
}

variable "region" {
  description = "AWS region to deploy test resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile to use"
  type        = string
  default     = "gatepass"
}

variable "project_tag" {
  description = "Tag for all resources"
  type        = string
  default     = "vapor-test"
}

locals {
  common_tags = {
    Project     = var.project_tag
    Environment = "test"
    ManagedBy   = "terraform"
    Purpose     = "vapor-cost-audit-testing"
  }
}
