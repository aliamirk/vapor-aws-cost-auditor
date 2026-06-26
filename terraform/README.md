# Vapor Test Infrastructure

Deliberately wasteful AWS resources for testing Vapor's cost audit detection.

## What Gets Created

| Resource | Count | Vapor Verdict | Est. Monthly Waste |
|----------|-------|---------------|-------------------|
| Unattached EBS volumes | 4 | `unattached` | ~$18.35 |
| Unassociated Elastic IPs | 3 | `unassociated` | ~$10.95 |
| S3 buckets (no lifecycle) | 3 | `no_lifecycle_policy` | $0 (risk) |
| S3 bucket (with lifecycle) | 1 | `healthy` | — |
| Lambda (high memory) | 2 | `high_memory` | $0 |
| Lambda (high timeout) | 2 | `high_timeout` | $0 |
| Lambda (healthy) | 1 | `healthy` | — |
| RDS (idle db.t3.medium) | 1 | `underutilized` | ~$50 |

**Total estimated waste: ~$79/month**

## Usage

```bash
cd terraform

# Initialize
terraform init

# Preview what will be created
terraform plan

# Deploy test resources
terraform apply -auto-approve

# Run Vapor against the account
cd ..
AWS_PROFILE=gatepass python vapor.py --output report.json

# Clean up (IMPORTANT — stop the waste!)
cd terraform
terraform destroy -auto-approve
```

## Important

- These resources incur **real AWS costs** — destroy them after testing
- The RDS instance takes ~5 minutes to create and ~5 minutes to destroy
- Wait 5-10 minutes after `apply` before running Vapor so CloudWatch has data
- The RDS password is hardcoded for testing only — never do this in production
