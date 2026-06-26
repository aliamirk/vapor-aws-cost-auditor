# Vapor — Usage Guide

## Quick Start

```bash
# 1. Install Vapor as a CLI command
pip install -e .

# 2. Create a .env file with your OpenAI key
echo "OPENAI_API_KEY=sk-your-key-here" > .env

# 3. Run the audit
vapor --profile your-aws-profile
```

That's it. Vapor will scan your AWS account in `us-east-1`, analyze findings with GPT-5-mini, and print a color-coded report to your terminal.

---

## What Vapor Scans

Vapor runs 7 collectors in parallel against your AWS account:

| Collector | What It Looks For |
|-----------|-------------------|
| **EC2** | Underutilized instances (low CPU avg + max over the lookback window) |
| **RDS** | Underutilized databases (low CPU + few connections) and over-provisioned memory |
| **S3** | Buckets missing lifecycle policies (unbounded storage growth) |
| **Lambda** | Functions with excessive memory (≥1024 MB) or timeout (≥900s) |
| **EBS** | Unattached volumes (status = "available") sitting idle |
| **EIP** | Unassociated Elastic IPs incurring hourly charges |
| **Cost Explorer** | Monthly spend breakdown by service |

After collection, findings are normalized, assigned verdicts and cost estimates, then sent to GPT-5-mini for severity-tagged analysis.

---

## Environment Setup

### Required

Create a `.env` file in the project root (Vapor loads it automatically):

```env
OPENAI_API_KEY=sk-proj-abc123...
```

### AWS Credentials

Vapor uses `boto3`, which reads credentials from the standard chain:

1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. Shared credentials file (`~/.aws/credentials`)
3. AWS SSO / IAM Identity Center
4. EC2 instance metadata (if running on AWS)

If you use named profiles:

```env
AWS_PROFILE=my-readonly-profile
```

### Permissions

Vapor needs read-only access to several AWS services. A minimal IAM policy is included in the project at `iam-policy.json`.

**Option A: Use the included policy file**

```bash
# Create the policy in your AWS account
aws iam create-policy \
  --policy-name VaporAuditPolicy \
  --policy-document file://iam-policy.json \
  --profile gatepass

# Attach to your IAM user
aws iam attach-user-policy \
  --user-name YOUR_USERNAME \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/VaporAuditPolicy \
  --profile gatepass
```

**Option B: Attach to an IAM role (for EC2/SSO)**

```bash
aws iam attach-role-policy \
  --role-name YOUR_ROLE_NAME \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/VaporAuditPolicy \
  --profile gatepass
```

**Option C: Use the AWS managed ReadOnlyAccess policy (broader but simpler)**

```bash
aws iam attach-user-policy \
  --user-name YOUR_USERNAME \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess \
  --profile gatepass
```

The minimum permissions Vapor requires:

| Service | Actions |
|---------|---------|
| EC2 | DescribeInstances, DescribeVolumes, DescribeAddresses |
| RDS | DescribeDBInstances |
| S3 | ListAllMyBuckets, GetLifecycleConfiguration |
| Lambda | ListFunctions |
| CloudWatch | GetMetricData |
| Cost Explorer | ce:GetCostAndUsage |

Cost Explorer must be enabled in the AWS Billing Console — if it's not, Vapor handles this gracefully and reports it as a gap finding.

---

## CLI Reference

```
vapor [OPTIONS]
```

### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--profile` | string | None | AWS CLI profile name to use for authentication |
| `--region` | string | `us-east-1` | AWS region to scan |
| `--window-days` | int | `30` | CloudWatch metrics lookback period (days) |
| `--output` | path | — | Write analysis JSON to this file |
| `--save-raw` | path | — | Write raw collector data to this file (pre-LLM) |
| `--ec2-cpu-avg-threshold` | float | `10.0` | EC2 CPU average % below which = underutilized |
| `--ec2-cpu-max-threshold` | float | `40.0` | EC2 CPU max % below which = underutilized |
| `--rds-cpu-avg-threshold` | float | `10.0` | RDS CPU average % below which = underutilized |
| `--rds-connections-threshold` | int | `5` | RDS max connections below which = idle |
| `--rds-memory-free-pct` | float | `75.0` | RDS free memory % above which = over-provisioned |

---

## Examples

### Basic scan (defaults)

```bash
vapor --profile gatepass
```

Scans `us-east-1` with a 30-day lookback window and prints results to the terminal.

### Scan a different region

```bash
vapor --profile gatepass --region eu-west-1
```

### Save the report as JSON

```bash
vapor --profile gatepass --output report.json
```

The JSON file contains the full LLM analysis with severity-tagged findings, summary counts, and estimated savings.

### Save raw collector data for debugging

```bash
vapor --profile gatepass --save-raw raw_data.json --output report.json
```

`raw_data.json` contains the pre-LLM collector output — useful for debugging or running the analysis offline.

### Shorter lookback window

```bash
vapor --profile gatepass --window-days 7
```

Uses only the last 7 days of CloudWatch metrics. Shorter windows give more recent data but less statistical confidence.

### Adjust underutilization thresholds

```bash
vapor --profile gatepass \
  --ec2-cpu-avg-threshold 5.0 \
  --ec2-cpu-max-threshold 20.0 \
  --rds-cpu-avg-threshold 5.0 \
  --rds-connections-threshold 2
```

Tighter thresholds = fewer false positives (only flags truly idle resources).

### Full audit with all options

```bash
vapor \
  --profile gatepass \
  --region us-west-2 \
  --window-days 14 \
  --output audit-report.json \
  --save-raw raw-collectors.json \
  --ec2-cpu-avg-threshold 15.0 \
  --ec2-cpu-max-threshold 50.0 \
  --rds-cpu-avg-threshold 15.0 \
  --rds-connections-threshold 10 \
  --rds-memory-free-pct 80.0
```

---

## Understanding the Output

### Terminal Report

The terminal output uses Rich panels with color-coded severity:

- 🔴 **Critical** (bold red) — High-cost waste, >$500/month potential savings
- 🟡 **High** (bold yellow) — Significant waste, $100–500/month
- 🔵 **Medium** (bold blue) — Moderate waste, $20–100/month
- 🟢 **Low** (bold green) — Minor optimization opportunity, <$20/month

### Verdicts

Each resource gets a machine-readable verdict before LLM analysis:

| Verdict | Meaning |
|---------|---------|
| `underutilized` | EC2/RDS with CPU below thresholds |
| `no_data` | EC2 instance with no CloudWatch metrics |
| `overprovisioned_memory` | RDS with too much free RAM |
| `no_lifecycle_policy` | S3 bucket missing lifecycle rules |
| `high_memory` | Lambda with ≥1024 MB configured |
| `high_timeout` | Lambda with ≥900s timeout |
| `unattached` | EBS volume not attached to any instance |
| `unassociated` | EIP not associated with a running instance |
| `healthy` | Resource within normal parameters |
| `gap` | Collector encountered an error |

### JSON Output Schema

When using `--output`, the JSON file has this structure:

```json
{
  "summary": {
    "totalFindings": 12,
    "criticalCount": 1,
    "highCount": 3,
    "mediumCount": 5,
    "lowCount": 3,
    "estimatedMonthlySavings": "$450-$800"
  },
  "findings": [
    {
      "title": "Underutilized m5.2xlarge instance",
      "severity": "high",
      "category": "EC2",
      "resource_id": "i-0abc123def456",
      "detail": "CPU avg 2.3%, max 8.1% over 30 days",
      "estimated_savings": "$280/month",
      "fix": "Downsize to m5.large or consider spot instances"
    }
  ]
}
```

---

## How It Works

```
┌─────────────┐
│    vapor     │  Parse args, load .env, build config
└──────┬──────┘
       │
┌──────▼──────┐
│  LangGraph  │  Orchestrates the pipeline
└──────┬──────┘
       │
       ├── collect_ec2 ──────┐
       ├── collect_rds ──────┤
       ├── collect_s3 ───────┤
       ├── collect_lambda ───┼──► aggregate ──► analyze ──► render
       ├── collect_ebs ──────┤       │             │           │
       ├── collect_eip ──────┤   Normalize    GPT-5-mini   Rich panels
       └── collect_cost_explorer    + verdicts  + severity    or JSON
                                    + costs      tagging      file
```

1. **Collectors** run in parallel, each querying a different AWS service
2. **Aggregate** normalizes raw data into uniform Finding structures with pre-computed verdicts and cost estimates
3. **Analyze** sends findings to GPT-5-mini for severity classification and recommendations
4. **Render** displays the report as color-coded terminal panels or writes JSON

---

## Error Handling

Vapor is designed to produce a report even when things go wrong:

- **Collector fails** → other collectors continue; the failure appears as a "gap" finding in the report
- **LLM call fails** → a fallback analysis is produced with the error description
- **Unrecoverable error** → exits with code 1 and prints a red error message

The exit codes are:
- `0` — audit completed successfully (even if some collectors had issues)
- `1` — fatal error prevented the pipeline from completing

---

## Tips

- **Start with defaults** and adjust thresholds after reviewing the initial report
- **Use `--save-raw`** on your first run to inspect what data the collectors gather
- **Shorter windows** (7 days) catch recent changes; longer windows (60+ days) reduce noise from temporary spikes
- **Cost Explorer data** may be delayed by up to 24 hours — yesterday's spend won't appear immediately
- **The memory note** on EC2 findings indicates that RAM metrics require the CloudWatch agent (not installed by default). Only CPU is measured without it.
