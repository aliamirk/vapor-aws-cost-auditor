# Implementation Plan: Vapor CLI

## Overview

Vapor is a Python CLI tool that scans AWS accounts for cost waste using 7 parallel LangGraph collectors, aggregates findings with pre-computed verdicts, sends them to GPT-5-mini for severity-tagged analysis, and renders a color-coded Rich terminal report. Implementation follows the build order: foundation → EC2 collector → aggregate → prompts → analyze → render → graph → CLI → remaining collectors → README.

## Tasks

- [x] 1. Set up project structure and dependencies
  - [x] 1.1 Create requirements.txt and project directory structure
    - Create the full directory layout: `vapor/`, `graph/`, `graph/nodes/`, `prompts/`, `tests/`
    - Create all `__init__.py` files for packages
    - Write `requirements.txt` with pinned dependencies: boto3>=1.34.0, langgraph>=0.2.0, openai>=1.30.0, rich>=13.7.0, python-dotenv>=1.0.0
    - Add test dependencies: pytest>=7.0.0, hypothesis>=6.0.0, pytest-cov>=4.0.0
    - _Requirements: 2.1, 14.1_

  - [x] 1.2 Implement config.py with AuditConfig dataclass
    - Define `AuditConfig` dataclass with all fields and defaults: region="us-east-1", window_days=30, ec2_cpu_avg_threshold=10.0, ec2_cpu_max_threshold=40.0, rds_cpu_avg_threshold=10.0, rds_connections_threshold=5, rds_memory_free_pct_threshold=75.0, save_raw=None, output=None
    - _Requirements: 1.2, 1.4, 1.8, 1.10, 1.12, 1.14, 1.16_

  - [x] 1.3 Implement graph/state.py with VaporState, Finding, AnalysisResult TypedDicts
    - Define `merge_dicts(a, b)` reducer returning `{**a, **b}`
    - Define `merge_lists(a, b)` reducer returning `a + b`
    - Define `Finding` TypedDict with all required fields: resource_id, resource_type, region, issue, verdict, estimated_monthly_cost_usd, data, tags
    - Define `AnalysisResult` TypedDict with summary (dict) and findings (list[dict])
    - Define `VaporState` TypedDict with Annotated reducers for raw (merge_dicts) and errors (merge_lists)
    - _Requirements: 2.4, 2.5, 10.1_

  - [x]* 1.4 Write property tests for merge_dicts and merge_lists
    - **Property 2: merge_dicts preserves all keys**
    - **Property 3: merge_lists produces correct concatenation**
    - **Validates: Requirements 2.4, 2.5**

- [x] 2. Implement EC2 collector with CloudWatch batching
  - [x] 2.1 Implement graph/nodes/collect_ec2.py
    - Create `_safe_metric_id(instance_id, stat)` helper: strip `i-` prefix, replace dashes with underscores, prepend label (e.g., `cpu_avg_0abc123def`)
    - Create `_build_metric_queries(instance_ids, config)` that builds MetricDataQueries for avg, max, p95 with period=3600
    - Implement `collect_ec2(state)` that paginates describe_instances, batches CloudWatch get_metric_data, matches results back to instances
    - Handle missing data: set `cpu: {"avg": null, "max": null, "p95": null, "no_data": true}` when zero datapoints
    - Extract tags safely with `.get("Tags", [])` → dict conversion
    - Wrap entire function in try/except returning error dict on failure
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x]* 2.2 Write property test for CloudWatch metric ID validity
    - **Property 4: CloudWatch metric ID validity**
    - Test that for any valid instance ID matching `i-[0-9a-f]+` and any stat label, `_safe_metric_id` produces a string matching `^[a-z][a-zA-Z0-9_]*$`
    - **Validates: Requirements 3.4**

  - [x]* 2.3 Write property test for tag extraction
    - **Property 5: Tag extraction correctness**
    - Test that for any list of `{"Key": str, "Value": str}` dicts, extraction produces correct key→value mapping and empty list → empty dict
    - **Validates: Requirements 3.6**

- [x] 3. Implement aggregate node with verdict logic and cost estimation
  - [x] 3.1 Implement graph/nodes/aggregate.py
    - Define `EC2_HOURLY_USD` lookup dict for on-demand pricing
    - Define `EBS_MONTHLY_PER_GB` dict: gp3=0.08, gp2=0.10, io1=0.125
    - Define `EIP_MONTHLY_USD = 3.65`
    - Implement `_compute_ec2_verdict(instance, config)` returning (verdict, issue) tuple
    - Implement `_compute_rds_verdict(db, config)` returning list of (verdict, issue) tuples (RDS can have multiple issues)
    - Implement `_estimate_ec2_cost(instance_type)` → hourly × 730, None if unknown
    - Implement `_estimate_ebs_cost(size_gb, volume_type)` → per-GB monthly rate × size
    - Implement `aggregate(state)` that normalizes all raw data into Finding list
    - Convert all datetime objects to ISO strings with `.isoformat()`
    - Add memory visibility note to each EC2 finding: `{"available": False, "reason": "CloudWatch agent required — not collected"}`
    - Create gap findings for each error in `state["errors"]`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10, 10.11, 10.12, 10.13, 10.14, 10.15, 10.16_

  - [x]* 3.2 Write property tests for EC2 verdict logic
    - **Property 8: EC2 verdict correctness**
    - Test all three branches: no_data → "no_data", below both thresholds → "underutilized", otherwise → "healthy"
    - **Validates: Requirements 10.2, 10.3**

  - [x]* 3.3 Write property tests for RDS verdict logic
    - **Property 9: RDS verdict correctness**
    - Test: cpu.avg < threshold AND connections_max < threshold → "underutilized", memory_free_pct > threshold → "overprovisioned_memory", otherwise → "healthy"
    - **Validates: Requirements 10.4, 10.5**

  - [x]* 3.4 Write property tests for Lambda verdict logic
    - **Property 10: Lambda verdict correctness**
    - Test: memory_size >= 1024 → "high_memory", timeout >= 900 → "high_timeout", otherwise → "healthy"
    - **Validates: Requirements 10.7, 10.8**

  - [x]* 3.5 Write property tests for simple resource verdicts
    - **Property 11: Simple resource verdict invariants**
    - Test: S3 without lifecycle → "no_lifecycle_policy", EBS always → "unattached", EIP always → "unassociated"
    - **Validates: Requirements 10.6, 10.9, 10.10**

  - [x]* 3.6 Write property tests for cost estimation
    - **Property 12: Cost estimation correctness**
    - Test: EC2 known type → hourly × 730, EBS known type → rate × size_gb, EIP → 3.65
    - **Validates: Requirements 10.11, 10.12, 10.13**

  - [x]* 3.7 Write property tests for datetime serialization
    - **Property 13: Datetime serialization in findings**
    - Test that any datetime object in raw data becomes an ISO 8601 string after aggregation
    - **Validates: Requirements 10.14**

  - [x]* 3.8 Write property tests for EC2 memory note and gap findings
    - **Property 14: EC2 memory visibility note invariant**
    - **Property 15: Collector errors produce gap findings**
    - Test: every EC2 finding has memory note, every error produces gap finding
    - **Validates: Requirements 10.15, 10.16**

  - [x]* 3.9 Write property test for aggregate producing complete Finding structures
    - **Property 20: Aggregate produces complete Finding structures**
    - Test that for any valid raw collector output, all Finding fields are present and correctly typed
    - **Validates: Requirements 10.1**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement prompts and analyze node
  - [x] 5.1 Implement prompts/system.py and prompts/user.py
    - Define `SYSTEM_PROMPT` constant with expert AWS cost optimization engineer instructions
    - Include all LLM rules: severity-based-on-impact ranges, savings as range, window confidence, sort by severity, JSON output format
    - Implement `build_user_message(findings, config)` formatting findings with region, window_days, resource count, and all threshold values
    - _Requirements: 11.1, 11.2_

  - [x]* 5.2 Write property test for user message construction
    - **Property 17: User message includes all context**
    - Test that for any AuditConfig and non-empty findings list, the message contains region, window_days, finding count, and all thresholds
    - **Validates: Requirements 11.2**

  - [x] 5.3 Implement graph/nodes/analyze.py
    - Initialize OpenAI client (reads OPENAI_API_KEY from environment)
    - Call `client.chat.completions.create()` with model="gpt-5-mini", max_tokens=4000, temperature=0, response_format={"type": "json_object"}
    - Parse JSON response into AnalysisResult
    - Implement `_build_fallback_analysis(error_msg)` for API or parse failures
    - Handle openai.APIError, json.JSONDecodeError, KeyError with fallback
    - _Requirements: 11.1, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x]* 5.4 Write property test for analysis result schema
    - **Property 18: Analysis result schema completeness**
    - Test that valid JSON conforming to expected schema parses to AnalysisResult with all required summary and finding fields
    - **Validates: Requirements 11.3, 11.4, 11.5**

- [x] 6. Implement render node with Rich terminal output
  - [x] 6.1 Implement graph/nodes/render.py
    - Define `SEVERITY_COLORS` dict: critical="bold red", high="bold yellow", medium="bold blue", low="bold green"
    - Implement `_render_terminal(analysis, config)` with Rich panels: header panel, summary row, per-finding panels with severity badges
    - Implement `_render_json_file(analysis, path)` writing pretty-printed JSON with default=str
    - Implement `_save_raw_json(raw, path)` writing raw collector state as JSON
    - Implement `render(state)` that checks config.save_raw and config.output to determine output mode
    - Sort findings by severity descending (critical → high → medium → low) before rendering
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.1, 13.2, 13.3, 13.4_

  - [x]* 6.2 Write property test for severity sorting
    - **Property 19: Findings sorted by severity**
    - Test that for any list of findings with mixed severities, output order is always critical before high before medium before low
    - **Validates: Requirements 12.6**

- [x] 7. Wire the LangGraph graph and CLI entry point
  - [x] 7.1 Implement graph/graph.py
    - Import all node functions
    - Build `StateGraph(VaporState)` with all 10 nodes registered
    - Add parallel fan-out edges: START → each collector
    - Add convergence edges: each collector → aggregate
    - Add linear pipeline: aggregate → analyze → render → END
    - Implement `build_graph()` returning compiled graph
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 7.2 Implement vapor.py CLI entry point
    - Implement `parse_args()` with argparse defining all flags and defaults
    - Implement `build_config(args)` converting namespace to AuditConfig
    - Implement `main()` that loads .env with python-dotenv, parses args, builds config, constructs initial VaporState, invokes compiled graph
    - Handle top-level exceptions with Rich error message and sys.exit(1)
    - Exit with code 0 on success
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19_

  - [x]* 7.3 Write property test for CLI argument round-trip
    - **Property 1: CLI argument round-trip**
    - Test that for any valid CLI argument values, parsing and constructing AuditConfig produces matching field values
    - **Validates: Requirements 1.1, 1.3, 1.7, 1.9, 1.11, 1.13, 1.15**

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement remaining collectors
  - [x] 9.1 Implement graph/nodes/collect_rds.py
    - Define `RDS_RAM_GB` hardcoded lookup dict for common instance classes
    - Implement `_compute_memory_free_pct(freeable_memory_gb, instance_class)` returning pct or None
    - Paginate describe_db_instances, batch CloudWatch metrics (CPUUtilization avg/max, FreeableMemory avg, DatabaseConnections max)
    - Convert FreeableMemory from bytes to GB (divide by 1024^3)
    - Handle unknown instance classes with memory_free_pct=None
    - Wrap in try/except with error dict return
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x]* 9.2 Write property test for RDS memory percentage computation
    - **Property 7: RDS memory percentage computation**
    - Test: known class → (bytes/1024^3/total_ram_gb)*100, unknown class → None
    - **Validates: Requirements 4.4, 4.5, 4.6**

  - [x] 9.3 Implement graph/nodes/collect_s3.py
    - List all buckets, check each for lifecycle configuration
    - Catch ClientError with code "NoSuchLifecycleConfiguration" → has_lifecycle_policy=False
    - Catch other ClientError separately as per-bucket errors
    - Wrap in try/except with error dict return
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 9.4 Implement graph/nodes/collect_lambda.py
    - Paginate list_functions, collect function_name, runtime, memory_size, timeout, last_modified, code_size_bytes
    - Wrap in try/except with error dict return
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 9.5 Implement graph/nodes/collect_ebs.py
    - Paginate describe_volumes with filter for status="available"
    - Collect volume_id, size_gb, volume_type, create_time, availability_zone, tags
    - Wrap in try/except with error dict return
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 9.6 Implement graph/nodes/collect_eip.py
    - Call describe_addresses(), filter for unassociated (no AssociationId or no InstanceId)
    - Collect allocation_id, public_ip, tags
    - Wrap in try/except with error dict return
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x]* 9.7 Write property test for EIP unassociated filtering
    - **Property 6: EIP unassociated filtering**
    - Test: only addresses missing AssociationId or InstanceId are returned, never those with both present
    - **Validates: Requirements 8.2**

  - [x] 9.8 Implement graph/nodes/collect_cost_explorer.py
    - Instantiate Cost Explorer client with region_name="us-east-1" (comment explaining why)
    - Query get_cost_and_usage with MONTHLY granularity, SERVICE grouping, UnblendedCost metrics
    - Compute total_cost_usd by summing all service costs
    - Handle Cost Explorer not enabled: return {"available": false, "error": "..."}
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x]* 9.9 Write property test for Cost Explorer total computation
    - **Property 16: Cost Explorer total equals sum of parts**
    - Test that total_cost_usd equals the sum of all individual service costs
    - **Validates: Requirements 9.3**

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Create README and finalize
  - [x] 11.1 Create README.md
    - Write description of what Vapor does
    - Document prerequisites: Python 3.11+, AWS credentials with ReadOnly access, OpenAI API key
    - Installation steps: `pip install -r requirements.txt`
    - `.env` setup instructions with all required environment variables
    - All CLI examples: minimal invocation, full options
    - Recommended IAM policy note (ReadOnlyAccess managed policy)
    - Note that Cost Explorer must be enabled in AWS Billing Console
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 1.7, 1.9, 1.11, 1.13, 1.15, 1.17_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (20 properties)
- Unit tests validate specific examples and edge cases
- The build order ensures a working pipeline after task 7 (graph + CLI), before all collectors are complete
- Implementation must use `gpt-5-mini` as the LLM model (not gpt-4o-mini)
- 9 critical gotchas are addressed inline: CloudWatch metric ID format (2.1), S3 lifecycle exception (9.3), RDS FreeableMemory bytes→GB (9.1), Cost Explorer us-east-1 region (9.8), LangGraph parallel state merging (1.3, 7.1), pagination (2.1, 9.1, 9.3, 9.4, 9.5), missing tags (2.1), EC2 memory visibility (3.1), datetime serialization (3.1)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9"] },
    { "id": 4, "tasks": ["5.1", "5.3"] },
    { "id": 5, "tasks": ["5.2", "5.4", "6.1"] },
    { "id": 6, "tasks": ["6.2", "7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3"] },
    { "id": 8, "tasks": ["9.1", "9.3", "9.4", "9.5", "9.6", "9.8"] },
    { "id": 9, "tasks": ["9.2", "9.7", "9.9"] },
    { "id": 10, "tasks": ["11.1"] }
  ]
}
```
