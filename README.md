# Vapor

AWS cost audit CLI tool powered by LangGraph and GPT-5-mini. Vapor scans your AWS account for waste — underutilized EC2/RDS instances, unattached EBS volumes, unassociated Elastic IPs, S3 buckets without lifecycle policies, over-provisioned Lambda functions, and Cost Explorer spend breakdowns — then produces severity-tagged recommendations via LLM analysis.

## Prerequisites

- Python 3.11+
- AWS credentials configured (via environment variables, `~/.aws/credentials`, or AWS SSO)
- OpenAI API key

## Installation

```bash
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-your-openai-api-key

# Optional: override AWS profile/region (defaults to us-east-1)
AWS_PROFILE=your-profile
AWS_REGION=us-east-1
```

Vapor loads `.env` automatically via `python-dotenv` on startup.

## Usage

Minimal invocation (uses defaults: us-east-1, 30-day window):

```bash
python vapor.py
```

Specify a region:

```bash
python vapor.py --region eu-west-1
```

Full options:

```bash
python vapor.py \
  --region us-west-2 \
  --window-days 14 \
  --output report.json \
  --save-raw raw.json \
  --ec2-cpu-avg-threshold 15.0 \
  --ec2-cpu-max-threshold 50.0
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--region` | `us-east-1` | Target AWS region |
| `--window-days` | `30` | CloudWatch metrics lookback window (days) |
| `--output` | None | Path to write analysis JSON |
| `--save-raw` | None | Path to write raw collector JSON |
| `--ec2-cpu-avg-threshold` | `10.0` | EC2 CPU avg % underutilization threshold |
| `--ec2-cpu-max-threshold` | `40.0` | EC2 CPU max % underutilization threshold |
| `--rds-cpu-avg-threshold` | `10.0` | RDS CPU avg % underutilization threshold |
| `--rds-connections-threshold` | `5` | RDS idle connections threshold |
| `--rds-memory-free-pct` | `75.0` | RDS memory over-provisioned % threshold |

## IAM Policy

Vapor requires read-only access to multiple AWS services. The recommended approach is to attach the AWS managed **ReadOnlyAccess** policy (`arn:aws:iam::aws:policy/ReadOnlyAccess`) to the IAM user or role running Vapor.

For Cost Explorer access, ensure the policy also includes:

```json
{
  "Effect": "Allow",
  "Action": [
    "ce:GetCostAndUsage"
  ],
  "Resource": "*"
}
```

> **Note:** Cost Explorer must be enabled in the **AWS Billing Console** before the Cost Explorer collector can retrieve spend data. If it's not enabled, Vapor will handle this gracefully and report it as a collector error rather than crashing.
# vapor-aws-cost-auditor
