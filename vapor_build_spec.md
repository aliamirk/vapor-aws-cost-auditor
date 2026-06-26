# Vapor — AWS Cost Audit Agent: Build Specification

> Feed this entire document to Amazon Kiro as your project prompt. It contains every architectural decision, file structure, implementation detail, and gotcha needed to build Vapor end-to-end.

---

## What Is Vapor?

Vapor is a CLI tool and agentic pipeline that scans an AWS account for cost waste, passes the findings to an LLM for analysis, and outputs a structured, severity-tagged report. The name reflects the core idea: cloud spend that disappears unnoticed.

**One-line summary:** `vapor --region us-east-1 --window-days 30` → scans AWS → analyzes with GPT → prints a findings report.

---

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| AWS SDK | `boto3` |
| Agent orchestration | `langgraph` |
| LLM | OpenAI `gpt-4o-mini` via `openai` Python SDK |
| CLI parsing | `argparse` (stdlib, no extra deps) |
| Output formatting | `rich` (terminal cards with color) |

---

## Project Structure

Create exactly this directory and file layout:

```
vapor/
  vapor.py                        # Entry point — CLI parsing, graph invocation
  config.py                       # AuditConfig dataclass + all threshold defaults
  requirements.txt                # All dependencies pinned
  README.md                       # Usage instructions
  graph/
    __init__.py
    state.py                      # VaporState, Finding, AnalysisResult TypedDicts
    graph.py                      # Builds and compiles the LangGraph graph
    nodes/
      __init__.py
      collect_ec2.py
      collect_rds.py
      collect_s3.py
      collect_lambda.py
      collect_ebs.py
      collect_eip.py
      collect_cost_explorer.py
      aggregate.py                # Normalizes raw collector output → Finding list
      analyze.py                  # Sends findings to GPT, parses response
      render.py                   # Renders AnalysisResult to terminal or file
  prompts/
    __init__.py
    system.py                     # System prompt string
    user.py                       # Builds user message from Finding list
```

---

## `requirements.txt`

```
boto3>=1.34.0
langgraph>=0.2.0
openai>=1.30.0
rich>=13.7.0
python-dotenv>=1.0.0
```

---

## Environment Variables

Vapor reads credentials from environment variables or a `.env` file in the project root:

```
OPENAI_API_KEY=sk-...
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1   # overridden by --region flag
```

Use `python-dotenv` to load `.env` at startup in `vapor.py`.

---

## CLI Interface (`vapor.py`)

The entry point must support this exact interface:

```bash
# Minimal — uses all defaults
vapor --region us-east-1

# Full options
vapor \
  --region eu-west-1 \
  --window-days 14 \
  --output report.json \
  --save-raw raw.json \
  --ec2-cpu-avg-threshold 15 \
  --rds-connections-threshold 3
```

### Arguments

| Flag | Type | Default | Description |
|---|---|---|---|
| `--region` | str | `us-east-1` | AWS region to scan |
| `--window-days` | int | `30` | Lookback window for CloudWatch metrics |
| `--output` | str | None | Path to write final JSON report. If omitted, print to terminal |
| `--save-raw` | str | None | Path to write pre-LLM collector JSON. Optional debug flag |
| `--ec2-cpu-avg-threshold` | float | `10.0` | EC2 CPU avg % below which instance is underutilized |
| `--ec2-cpu-max-threshold` | float | `40.0` | EC2 CPU max % below which instance is underutilized |
| `--rds-cpu-avg-threshold` | float | `10.0` | RDS CPU avg % below which DB is underutilized |
| `--rds-connections-threshold` | int | `5` | RDS max connections below which DB is considered idle |
| `--rds-memory-free-pct` | float | `75.0` | RDS free memory % above which DB is over-provisioned |

`vapor.py` must:
1. Parse all args using `argparse`
2. Load `.env` using `python-dotenv`
3. Build an `AuditConfig` dataclass from the parsed args
4. Instantiate and invoke the LangGraph graph with initial state
5. Exit with code 0 on success, 1 on error

---

## `config.py`

```python
from dataclasses import dataclass

@dataclass
class AuditConfig:
    region: str = "us-east-1"
    window_days: int = 30
    ec2_cpu_avg_threshold: float = 10.0
    ec2_cpu_max_threshold: float = 40.0
    rds_cpu_avg_threshold: float = 10.0
    rds_connections_threshold: int = 5
    rds_memory_free_pct_threshold: float = 75.0
    save_raw: str | None = None
    output: str | None = None
```

---

## `graph/state.py`

Define all TypedDicts here. This is the single source of truth for data shapes across the entire pipeline.

```python
from typing import TypedDict, Annotated
import operator

def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}

def merge_lists(a: list, b: list) -> list:
    return a + b

class Finding(TypedDict):
    resource_id: str           # e.g. "i-0abc123def", "my-bucket", "arn:aws:lambda:..."
    resource_type: str         # EC2 | RDS | S3 | Lambda | EBS | EIP | CloudWatch | CostExplorer
    region: str
    issue: str                 # machine-readable descriptor e.g. "underutilized_instance"
    verdict: str               # underutilized | healthy | overutilized | unknown | no_data | gap
    estimated_monthly_cost_usd: float | None   # rough on-demand cost, None if unknown
    data: dict                 # all raw facts relevant to this resource
    tags: dict                 # AWS resource tags, empty dict if none

class AnalysisResult(TypedDict):
    summary: dict              # totalFindings, criticalCount, highCount, mediumCount, lowCount, estimatedMonthlySavings
    findings: list[dict]       # LLM-produced findings list

class VaporState(TypedDict):
    config: AuditConfig
    raw: Annotated[dict, merge_dicts]          # each collector writes to its own key
    errors: Annotated[list, merge_lists]       # non-fatal errors from any collector
    findings: list[Finding]                    # populated by aggregate node
    analysis: AnalysisResult                   # populated by analyze node
    report: str                                # populated by render node
```

---

## `graph/graph.py`

Build the LangGraph graph with **static parallel fan-out** (Option A). All collector nodes run concurrently from a single dispatch fan-out. After all collectors complete, state merges automatically and flows to `aggregate`.

```python
from langgraph.graph import StateGraph, START, END
from graph.state import VaporState
from graph.nodes.collect_ec2 import collect_ec2
from graph.nodes.collect_rds import collect_rds
from graph.nodes.collect_s3 import collect_s3
from graph.nodes.collect_lambda import collect_lambda
from graph.nodes.collect_ebs import collect_ebs
from graph.nodes.collect_eip import collect_eip
from graph.nodes.collect_cost_explorer import collect_cost_explorer
from graph.nodes.aggregate import aggregate
from graph.nodes.analyze import analyze
from graph.nodes.render import render

def build_graph():
    builder = StateGraph(VaporState)

    # Register all nodes
    builder.add_node("collect_ec2", collect_ec2)
    builder.add_node("collect_rds", collect_rds)
    builder.add_node("collect_s3", collect_s3)
    builder.add_node("collect_lambda", collect_lambda)
    builder.add_node("collect_ebs", collect_ebs)
    builder.add_node("collect_eip", collect_eip)
    builder.add_node("collect_cost_explorer", collect_cost_explorer)
    builder.add_node("aggregate", aggregate)
    builder.add_node("analyze", analyze)
    builder.add_node("render", render)

    # Parallel fan-out from START to all collectors
    collectors = [
        "collect_ec2", "collect_rds", "collect_s3",
        "collect_lambda", "collect_ebs", "collect_eip",
        "collect_cost_explorer"
    ]
    for node in collectors:
        builder.add_edge(START, node)
        builder.add_edge(node, "aggregate")

    # Linear pipeline after aggregation
    builder.add_edge("aggregate", "analyze")
    builder.add_edge("analyze", "render")
    builder.add_edge("render", END)

    return builder.compile()
```

---

## Collector Nodes

Every collector node has this signature:

```python
def collect_X(state: VaporState) -> dict:
    config = state["config"]
    # ... collect data ...
    return {
        "raw": {"X": result},       # writes to its own key only
        "errors": []                 # or list of error strings
    }
```

If a collector fails entirely (permissions error, service not available), it must NOT raise an exception. It must return:
```python
return {
    "raw": {"X": {"error": str(e), "data": []}},
    "errors": [f"collect_X failed: {str(e)}"]
}
```

---

### `collect_ec2.py`

**Purpose:** Describe all EC2 instances and collect CPU utilization metrics from CloudWatch.

**AWS APIs used:**
- `ec2.get_paginator("describe_instances")` — paginate through all instances
- `cloudwatch.get_metric_data` — batch all instance CPU queries in ONE call

**What to collect per instance:**
- `instance_id`, `instance_type`, `state` (running/stopped), `launch_time`, `availability_zone`
- Tags dict (key-value pairs from the Tags list)
- Attached EBS volume IDs and their sizes
- CloudWatch CPU metrics: `avg`, `max`, `p95` over the configured window

**CloudWatch batching — critical implementation detail:**

Build `MetricDataQueries` dynamically, one entry per instance per stat. The query `Id` field must match the regex `^[a-z][a-zA-Z0-9_]*$`. Since instance IDs contain dashes (e.g. `i-0abc123`), transform them: strip the `i-` prefix and prepend a label.

Example for instance `i-0abc123def`:
```python
# cpu_avg_0abc123def  ← valid Id
# cpu_max_0abc123def
# cpu_p95_0abc123def
```

For p95, use `stat="p95"` in the `MetricStat` block.

Period: always `3600` (1 hour). StartTime: `datetime.utcnow() - timedelta(days=config.window_days)`. EndTime: `datetime.utcnow()`.

After the call, match results back to instances using the `Id` field.

**Handle missing data:** If an instance returns zero datapoints for all metrics (e.g. it was stopped), set `cpu: {"avg": null, "max": null, "p95": null, "no_data": true}`.

**Output format** (stored in `raw["ec2"]`):
```json
[
  {
    "instance_id": "i-0abc123def",
    "instance_type": "m5.xlarge",
    "state": "running",
    "launch_time": "2024-01-15T10:23:00Z",
    "availability_zone": "us-east-1a",
    "tags": {"Name": "prod-web-01", "Env": "production"},
    "ebs_volumes": [{"volume_id": "vol-0abc", "size_gb": 100}],
    "cpu": {"avg": 4.2, "max": 18.1, "p95": 11.3, "no_data": false}
  }
]
```

---

### `collect_rds.py`

**Purpose:** Describe all RDS instances and collect CPU, memory, and connection metrics.

**AWS APIs used:**
- `rds.get_paginator("describe_db_instances")`
- `cloudwatch.get_metric_data` — batch all DB queries in ONE call

**What to collect per DB instance:**
- `db_instance_id`, `db_instance_class`, `engine`, `engine_version`
- `status`, `multi_az` (bool), `publicly_accessible` (bool)
- `allocated_storage_gb`, `storage_type`

**CloudWatch metrics to collect** (namespace `AWS/RDS`):
- `CPUUtilization` — avg and max
- `FreeableMemory` — avg (comes back in **bytes**, divide by `1024^3` to get GB before storing)
- `DatabaseConnections` — max

**RAM lookup for % free calculation:**

Maintain a hardcoded dict of common RDS instance classes and their total RAM. Use this to compute `memory_free_pct`. If the instance class is not in the dict, set `memory_free_pct: null` and `memory_lookup: "unknown"`.

```python
RDS_RAM_GB = {
    "db.t3.micro": 1, "db.t3.small": 2, "db.t3.medium": 4,
    "db.t3.large": 8, "db.t3.xlarge": 16, "db.t3.2xlarge": 32,
    "db.m5.large": 8, "db.m5.xlarge": 16, "db.m5.2xlarge": 32,
    "db.m5.4xlarge": 64, "db.r5.large": 16, "db.r5.xlarge": 32,
    "db.r5.2xlarge": 64, "db.r5.4xlarge": 128,
}
```

**Output format** (stored in `raw["rds"]`):
```json
[
  {
    "db_instance_id": "prod-mysql-01",
    "db_instance_class": "db.t3.medium",
    "engine": "mysql",
    "status": "available",
    "multi_az": true,
    "publicly_accessible": false,
    "allocated_storage_gb": 100,
    "cpu": {"avg": 3.1, "max": 12.4},
    "memory_free_gb": 3.2,
    "memory_total_gb": 4,
    "memory_free_pct": 80.0,
    "connections_max": 2
  }
]
```

---

### `collect_s3.py`

**Purpose:** List all S3 buckets and check for lifecycle policies.

**AWS APIs used:**
- `s3.list_buckets()` — global, returns all buckets regardless of region
- `s3.get_bucket_lifecycle_configuration(Bucket=name)` — per bucket

**Critical gotcha:** `get_bucket_lifecycle_configuration` raises `ClientError` with code `NoSuchLifecycleConfiguration` when no policy exists. This is NOT a permissions error — catch it explicitly and set `has_lifecycle_policy: false`. Any other `ClientError` should be caught separately and stored as an error.

**Output format** (stored in `raw["s3"]`):
```json
[
  {
    "name": "my-app-logs",
    "creation_date": "2022-03-10T14:00:00Z",
    "has_lifecycle_policy": false
  }
]
```

---

### `collect_lambda.py`

**Purpose:** List all Lambda functions in the region.

**AWS APIs used:**
- `lambda_.get_paginator("list_functions")`

**What to collect per function:**
- `function_name`, `runtime`, `memory_size`, `timeout`, `last_modified`, `code_size_bytes`

**Output format** (stored in `raw["lambda"]`):
```json
[
  {
    "function_name": "process-images",
    "runtime": "python3.11",
    "memory_size": 1024,
    "timeout": 900,
    "last_modified": "2024-06-01T12:00:00Z",
    "code_size_bytes": 5242880
  }
]
```

---

### `collect_ebs.py`

**Purpose:** Find unattached EBS volumes (state = `available`). These incur storage costs with no compute attached.

**AWS APIs used:**
- `ec2.get_paginator("describe_volumes")` with filter `[{"Name": "status", "Values": ["available"]}]`

**Output format** (stored in `raw["ebs"]`):
```json
[
  {
    "volume_id": "vol-0abc123",
    "size_gb": 100,
    "volume_type": "gp3",
    "create_time": "2023-11-20T09:00:00Z",
    "availability_zone": "us-east-1a",
    "tags": {}
  }
]
```

---

### `collect_eip.py`

**Purpose:** Find unassociated Elastic IPs. AWS charges for EIPs not attached to a running instance.

**AWS APIs used:**
- `ec2.describe_addresses()` — no paginator needed, typically small result set

Filter for addresses where `AssociationId` is absent or `InstanceId` is absent.

**Output format** (stored in `raw["eip"]`):
```json
[
  {
    "allocation_id": "eipalloc-0abc123",
    "public_ip": "54.123.45.67",
    "tags": {}
  }
]
```

---

### `collect_cost_explorer.py`

**Purpose:** Retrieve last N days of cost grouped by service.

**Critical gotcha:** Cost Explorer client MUST be instantiated with `region_name="us-east-1"` regardless of the `--region` flag. This is an AWS requirement — Cost Explorer is a global service only accessible via the us-east-1 endpoint. Add a comment in the code explaining this.

**Critical gotcha 2:** Cost Explorer must be enabled in the account's Billing Console. If it is not, the API returns a specific error. Catch it and store as a gap finding rather than crashing.

**AWS APIs used:**
- `ce.get_cost_and_usage()` with:
  - `TimePeriod`: last `window_days` days
  - `Granularity`: `MONTHLY`
  - `GroupBy`: `[{"Type": "DIMENSION", "Key": "SERVICE"}]`
  - `Metrics`: `["UnblendedCost"]`

**Output format** (stored in `raw["cost_explorer"]`):
```json
{
  "available": true,
  "window_days": 30,
  "costs_by_service": [
    {"service": "Amazon EC2", "cost_usd": 284.50},
    {"service": "Amazon RDS", "cost_usd": 112.30}
  ],
  "total_cost_usd": 396.80
}
```

If unavailable:
```json
{"available": false, "error": "Cost Explorer not enabled or insufficient permissions"}
```

---

## `graph/nodes/aggregate.py`

This is the most important node. It takes all raw collector outputs and produces a clean, normalized list of `Finding` objects. It also pre-computes verdicts and estimated costs — the LLM should interpret and recommend, not do threshold math.

### Responsibilities

1. **Normalize shape** — every finding has the same TypedDict structure regardless of source
2. **Compute `verdict`** — apply thresholds from `config`
3. **Compute `estimated_monthly_cost_usd`** — use the lookup table below
4. **Surface collector errors** — each error in `state["errors"]` becomes a `gap` verdict finding
5. **Surface missing CloudWatch agent** — EC2 instances with no memory data get a note in `data`

### Verdict rules

**EC2:**
- `no_data` — `cpu.no_data == true` (instance was stopped or metric not publishing)
- `underutilized` — `cpu.avg < config.ec2_cpu_avg_threshold` AND `cpu.max < config.ec2_cpu_max_threshold`
- `healthy` — otherwise

**RDS:**
- `underutilized` — `cpu.avg < config.rds_cpu_avg_threshold` AND `connections_max < config.rds_connections_threshold`
- `overprovisioned_memory` — `memory_free_pct > config.rds_memory_free_pct_threshold` (separate issue key)
- `healthy` — otherwise

**S3:**
- `no_lifecycle_policy` — `has_lifecycle_policy == false`
- `healthy` — otherwise

**Lambda:**
- `high_memory` — `memory_size >= 1024`
- `high_timeout` — `timeout >= 900` (15 minutes)
- `healthy` — otherwise

**EBS:**
- All unattached volumes: `verdict = "unattached"` — they are always waste by definition

**EIP:**
- All unassociated EIPs: `verdict = "unassociated"`

### EC2 on-demand cost lookup

Use this dict to estimate `estimated_monthly_cost_usd` (730 hours/month):

```python
EC2_HOURLY_USD = {
    "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416,
    "t3.large": 0.0832, "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768, "m5.8xlarge": 1.536,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
}
# monthly = hourly * 730
```

If instance type not in dict, set `estimated_monthly_cost_usd: null`.

### EBS cost lookup

gp3: `$0.08/GB/month`, gp2: `$0.10/GB/month`, io1: `$0.125/GB/month`. Multiply by `size_gb`.

### EIP cost

Unassociated EIP: `$0.005/hour` → `$3.65/month` each.

---

## `graph/nodes/analyze.py`

**Purpose:** Send the normalized `Finding` list to GPT-4o-mini and parse the structured response.

### OpenAI client setup

```python
from openai import OpenAI
client = OpenAI()  # reads OPENAI_API_KEY from environment
```

### Call parameters

```python
response = client.chat.completions.create(
    model="gpt-4o-mini",
    max_tokens=4000,
    temperature=0,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
)
```

Using `response_format={"type": "json_object"}` forces JSON output — no need to strip markdown fences.

Parse: `result = json.loads(response.choices[0].message.content)`

### Error handling

If the API call fails or JSON parsing fails, store a fallback `AnalysisResult` with one finding describing the failure. Do not crash the pipeline.

---

## `prompts/system.py`

```python
SYSTEM_PROMPT = """
You are an expert AWS cost optimization engineer. You will receive a list of findings from an automated AWS account scan. Each finding describes a resource with a pre-computed verdict and relevant metrics.

Your job is to analyze these findings and produce a structured cost audit report.

RULES:
- Only produce findings for resources that appear in the input data. Do not hallucinate resources.
- Base severity on actual impact: critical = active waste costing >$100/mo or a security risk, high = $20–$100/mo waste, medium = $5–$20/mo or best practice gap, low = minor optimization.
- Savings estimates must be a range, never a single number. Use the estimated_monthly_cost_usd field from findings where available.
- The window_days value tells you how long the metrics were observed. A 7-day window is less conclusive than a 30-day window — reflect this in your confidence.
- Flag publicly accessible RDS instances as critical regardless of utilization.
- Flag missing billing alerts (absent CloudWatch billing alarms) as high severity.
- Gap findings (collector errors, missing permissions) should be surfaced as medium severity — the user cannot optimize what they cannot see.
- Sort findings by severity descending: critical → high → medium → low.

OUTPUT FORMAT:
Return a single JSON object with this exact structure:
{
  "summary": {
    "totalFindings": <int>,
    "criticalCount": <int>,
    "highCount": <int>,
    "mediumCount": <int>,
    "lowCount": <int>,
    "estimatedMonthlySavings": "<string range like '$120–$340/mo'>"
  },
  "findings": [
    {
      "title": "<short descriptive title>",
      "severity": "critical|high|medium|low",
      "category": "Compute|Storage|Database|Networking|Observability|Security|Visibility",
      "resource_id": "<the resource_id from the input finding>",
      "detail": "<2–3 sentences explaining the problem and its cost impact>",
      "estimated_savings": "<range like '$80–$150/mo' or 'Unquantifiable'>",
      "fix": "<1–2 sentences describing the specific remediation action>"
    }
  ]
}
"""
```

---

## `prompts/user.py`

Build the user message from the Finding list and config:

```python
import json
from graph.state import Finding
from config import AuditConfig

def build_user_message(findings: list[Finding], config: AuditConfig) -> str:
    return f"""AWS Cost Audit Findings
Region: {config.region}
Observation window: {config.window_days} days
Total resources scanned: {len(findings)}

Thresholds used:
- EC2 CPU avg underutilized threshold: {config.ec2_cpu_avg_threshold}%
- EC2 CPU max underutilized threshold: {config.ec2_cpu_max_threshold}%
- RDS CPU avg underutilized threshold: {config.rds_cpu_avg_threshold}%
- RDS idle connections threshold: {config.rds_connections_threshold}
- RDS over-provisioned memory threshold: {config.rds_memory_free_pct_threshold}%

Findings data:
{json.dumps(findings, indent=2, default=str)}
"""
```

---

## `graph/nodes/render.py`

**Purpose:** Render the `AnalysisResult` to terminal using `rich`, or write to a JSON file.

### Terminal output (when `config.output` is None)

Use `rich` to render a visually clear report:

1. Print a header panel: "Vapor — AWS Cost Audit Report" with region and timestamp
2. Print a summary row: total findings, critical+high count, estimated savings
3. For each finding, print a `rich.panel.Panel` with:
   - Title: finding title + severity badge (color-coded: red=critical, yellow=high, blue=medium, green=low)
   - Category label
   - Resource ID
   - Detail text
   - Estimated savings line
   - Fix line (prefixed with "→ Fix:")

**Severity colors:**
- `critical` → `bold red`
- `high` → `bold yellow`
- `medium` → `bold blue`
- `low` → `bold green`

### File output (when `config.output` is set)

Write the full `AnalysisResult` as pretty-printed JSON to the path specified in `config.output`. Also print a short summary to terminal confirming the file was written.

### Save raw (when `config.save_raw` is set)

Write `state["raw"]` as pretty-printed JSON to the path specified in `config.save_raw`. Do this at the start of the render node before rendering the report.

---

## Important Implementation Notes

These are the non-obvious gotchas that will cause bugs if missed. Address each one explicitly.

### 1. CloudWatch metric query ID format
The `Id` field in `MetricDataQueries` must match `^[a-z][a-zA-Z0-9_]*$`. Instance IDs like `i-0abc123def` are invalid. Strip the `i-` prefix and prepend a safe label:
```python
safe_id = "cpu_avg_" + instance_id.replace("i-", "").replace("-", "_")
```
Apply the same pattern for RDS DB identifiers.

### 2. S3 lifecycle exception
`get_bucket_lifecycle_configuration` raises `botocore.exceptions.ClientError` with `error_response["Error"]["Code"] == "NoSuchLifecycleConfiguration"` when no policy exists. This must be caught separately from other `ClientError` exceptions. Not catching it will make every bucket without a policy look like a permissions failure.

### 3. RDS FreeableMemory units
The `FreeableMemory` CloudWatch metric returns values in **bytes**. Always divide by `1024 ** 3` to convert to GB before storing or computing percentages.

### 4. Cost Explorer region
Always instantiate the Cost Explorer client with `region_name="us-east-1"`:
```python
ce_client = boto3.client("ce", region_name="us-east-1")
```
This is true regardless of what `config.region` is set to. Comment this in the code.

### 5. LangGraph parallel state merging
The `raw` field in `VaporState` uses `Annotated[dict, merge_dicts]` where `merge_dicts` does `{**a, **b}`. Each collector must write to its own key in `raw` (e.g. `{"raw": {"ec2": [...]}}`) and never touch another collector's key. LangGraph calls the reducer after all parallel nodes complete.

### 6. Pagination
`describe_instances`, `describe_db_instances`, and `list_functions` all paginate. Always use `get_paginator()` and iterate through all pages. Never assume a single-page response.

### 7. Missing tags
Many resources have no tags. Always use `.get("Tags", [])` and convert to a dict safely:
```python
tags = {t["Key"]: t["Value"] for t in resource.get("Tags", [])}
```

### 8. EC2 memory visibility
The CloudWatch agent is required for memory metrics. Vapor does not attempt to collect memory for EC2. In the aggregate node, add a note to each EC2 finding's `data` dict:
```python
"memory": {"available": False, "reason": "CloudWatch agent required — not collected"}
```
The LLM prompt will surface this as a visibility gap if it seems relevant.

### 9. Datetime serialization
`boto3` returns `datetime` objects for timestamps. These are not JSON-serializable by default. In `render.py` when writing JSON files, use `default=str` in `json.dumps()`. In `aggregate.py`, convert all datetimes to ISO strings using `.isoformat()` before storing in the `Finding.data` dict.

---

## `README.md` Content

Include a README with:
1. One-paragraph description of what Vapor does
2. Prerequisites (Python 3.11+, AWS credentials with ReadOnly access, OpenAI API key)
3. Installation steps (`pip install -r requirements.txt`)
4. `.env` setup instructions
5. All CLI examples from the CLI Interface section above
6. Recommended IAM policy (ReadOnlyAccess managed policy is sufficient)
7. Note that Cost Explorer must be enabled separately in AWS Billing Console

---

## Build Order Recommendation

Build and test in this order to get a working end-to-end pass as early as possible:

1. `config.py` and `graph/state.py` — foundation, no AWS calls
2. `collect_ec2.py` — most complex collector, validates CloudWatch batching pattern
3. `aggregate.py` — wire EC2 findings through normalization
4. `prompts/system.py` and `prompts/user.py`
5. `analyze.py` — get one full EC2 → LLM → result pass working
6. `render.py` — verify terminal output looks correct
7. `graph/graph.py` — wire everything into the graph
8. `vapor.py` — CLI entry point
9. Remaining collectors: `collect_rds`, `collect_s3`, `collect_lambda`, `collect_ebs`, `collect_eip`, `collect_cost_explorer`

This order means you have a working pipeline after step 6, before building all collectors.
