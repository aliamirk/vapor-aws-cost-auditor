# Requirements Document

## Introduction

Vapor is a Python CLI tool that acts as an AWS cost audit agent. It scans an AWS account for cost waste across multiple services (EC2, RDS, S3, Lambda, EBS, EIP, Cost Explorer), passes the collected findings to an LLM (GPT-5-mini) for analysis, and outputs a structured, severity-tagged cost report to the terminal or a JSON file. The tool uses a LangGraph-based parallel pipeline architecture where collectors run concurrently, followed by aggregation, LLM analysis, and rendering stages.

## Glossary

- **Vapor**: The CLI tool and agentic pipeline that scans AWS accounts for cost waste
- **Collector**: A pipeline node that queries a specific AWS service for resource data and metrics
- **Finding**: A normalized data structure representing a single resource with its verdict, estimated cost, and metadata
- **Verdict**: A machine-readable classification of a resource's cost efficiency (e.g., underutilized, healthy, unattached)
- **Aggregate_Node**: The pipeline stage that normalizes raw collector output into Finding objects and pre-computes verdicts
- **Analyze_Node**: The pipeline stage that sends normalized findings to GPT-5-mini for severity-tagged analysis
- **Render_Node**: The pipeline stage that formats the analysis result for terminal display or JSON file output
- **AuditConfig**: A dataclass holding all CLI parameters and threshold values for the audit run
- **VaporState**: The shared state TypedDict that all pipeline nodes read from and write to
- **LangGraph_Graph**: The orchestration graph with static parallel fan-out for concurrent collector execution
- **CloudWatch_Metrics**: AWS monitoring data (CPU, memory, connections) collected over a configurable time window
- **Cost_Explorer**: AWS billing service that provides cost data grouped by service
- **Severity_Badge**: A color-coded label (critical, high, medium, low) indicating the impact of a finding

## Requirements

### Requirement 1: CLI Entry Point and Argument Parsing

**User Story:** As a DevOps engineer, I want to invoke Vapor from the command line with configurable options, so that I can customize the audit scope and output behavior.

#### Acceptance Criteria

1. WHEN invoked with `--region <value>`, THE Vapor CLI SHALL use the specified AWS region for all service collectors except Cost Explorer
2. WHEN invoked without `--region`, THE Vapor CLI SHALL default to `us-east-1` as the target region
3. WHEN invoked with `--window-days <value>`, THE Vapor CLI SHALL use the specified number of days as the CloudWatch metrics lookback window
4. WHEN invoked without `--window-days`, THE Vapor CLI SHALL default to 30 days as the lookback window
5. WHEN invoked with `--output <path>`, THE Vapor CLI SHALL write the full analysis JSON report to the specified file path
6. WHEN invoked with `--save-raw <path>`, THE Vapor CLI SHALL write the pre-LLM raw collector output as JSON to the specified file path
7. WHEN invoked with `--ec2-cpu-avg-threshold <value>`, THE Vapor CLI SHALL use the specified percentage as the EC2 CPU average underutilization threshold
8. WHEN invoked without `--ec2-cpu-avg-threshold`, THE Vapor CLI SHALL default to 10.0 percent
9. WHEN invoked with `--ec2-cpu-max-threshold <value>`, THE Vapor CLI SHALL use the specified percentage as the EC2 CPU maximum underutilization threshold
10. WHEN invoked without `--ec2-cpu-max-threshold`, THE Vapor CLI SHALL default to 40.0 percent
11. WHEN invoked with `--rds-cpu-avg-threshold <value>`, THE Vapor CLI SHALL use the specified percentage as the RDS CPU average underutilization threshold
12. WHEN invoked without `--rds-cpu-avg-threshold`, THE Vapor CLI SHALL default to 10.0 percent
13. WHEN invoked with `--rds-connections-threshold <value>`, THE Vapor CLI SHALL use the specified integer as the RDS idle connections threshold
14. WHEN invoked without `--rds-connections-threshold`, THE Vapor CLI SHALL default to 5 connections
15. WHEN invoked with `--rds-memory-free-pct <value>`, THE Vapor CLI SHALL use the specified percentage as the RDS over-provisioned memory threshold
16. WHEN invoked without `--rds-memory-free-pct`, THE Vapor CLI SHALL default to 75.0 percent
17. THE Vapor CLI SHALL load environment variables from a `.env` file in the project root using python-dotenv at startup
18. WHEN the pipeline completes successfully, THE Vapor CLI SHALL exit with code 0
19. IF the pipeline encounters an unrecoverable error, THEN THE Vapor CLI SHALL exit with code 1

### Requirement 2: Parallel Collector Pipeline Architecture

**User Story:** As a DevOps engineer, I want all AWS service collectors to run concurrently, so that the audit completes faster than sequential execution.

#### Acceptance Criteria

1. THE LangGraph_Graph SHALL execute all seven collector nodes (EC2, RDS, S3, Lambda, EBS, EIP, Cost Explorer) in parallel using static fan-out from the start node
2. WHEN all collector nodes complete, THE LangGraph_Graph SHALL merge their outputs into VaporState using Annotated reducers before passing state to the Aggregate_Node
3. THE LangGraph_Graph SHALL execute the Aggregate_Node, Analyze_Node, and Render_Node in sequential order after all collectors complete
4. THE VaporState SHALL use a `merge_dicts` reducer for the `raw` field that combines collector outputs via dictionary merge
5. THE VaporState SHALL use a `merge_lists` reducer for the `errors` field that concatenates error lists from all collectors

### Requirement 3: EC2 Collector

**User Story:** As a DevOps engineer, I want Vapor to collect EC2 instance details and CPU utilization metrics, so that I can identify underutilized compute resources.

#### Acceptance Criteria

1. THE collect_ec2 Collector SHALL paginate through all EC2 instances using `get_paginator("describe_instances")`
2. THE collect_ec2 Collector SHALL collect instance_id, instance_type, state, launch_time, availability_zone, tags, and attached EBS volume details for each instance
3. THE collect_ec2 Collector SHALL batch all CloudWatch CPU metric queries (avg, max, p95) into a single `get_metric_data` call with a period of 3600 seconds
4. THE collect_ec2 Collector SHALL transform instance IDs into valid CloudWatch metric query IDs by stripping the `i-` prefix, replacing dashes with underscores, and prepending a label prefix
5. WHEN an instance has zero CloudWatch datapoints for all CPU metrics, THE collect_ec2 Collector SHALL set the cpu field to `{"avg": null, "max": null, "p95": null, "no_data": true}`
6. THE collect_ec2 Collector SHALL extract tags using `.get("Tags", [])` and convert them to a key-value dictionary
7. IF the collect_ec2 Collector encounters an exception, THEN THE collect_ec2 Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 4: RDS Collector

**User Story:** As a DevOps engineer, I want Vapor to collect RDS instance details and performance metrics, so that I can identify underutilized or over-provisioned databases.

#### Acceptance Criteria

1. THE collect_rds Collector SHALL paginate through all RDS instances using `get_paginator("describe_db_instances")`
2. THE collect_rds Collector SHALL collect db_instance_id, db_instance_class, engine, engine_version, status, multi_az, publicly_accessible, allocated_storage_gb, and storage_type for each instance
3. THE collect_rds Collector SHALL batch CloudWatch metric queries for CPUUtilization (avg, max), FreeableMemory (avg), and DatabaseConnections (max) into a single `get_metric_data` call
4. THE collect_rds Collector SHALL convert FreeableMemory values from bytes to gigabytes by dividing by 1024 cubed
5. THE collect_rds Collector SHALL compute memory_free_pct using a hardcoded RAM lookup table for common RDS instance classes
6. WHEN the RDS instance class is not found in the RAM lookup table, THE collect_rds Collector SHALL set memory_free_pct to null and memory_lookup to "unknown"
7. IF the collect_rds Collector encounters an exception, THEN THE collect_rds Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 5: S3 Collector

**User Story:** As a DevOps engineer, I want Vapor to check all S3 buckets for lifecycle policies, so that I can identify buckets that may accumulate unbounded storage costs.

#### Acceptance Criteria

1. THE collect_s3 Collector SHALL list all S3 buckets using `list_buckets()`
2. THE collect_s3 Collector SHALL check each bucket for a lifecycle configuration using `get_bucket_lifecycle_configuration`
3. WHEN `get_bucket_lifecycle_configuration` raises a ClientError with code "NoSuchLifecycleConfiguration", THE collect_s3 Collector SHALL set has_lifecycle_policy to false for that bucket
4. WHEN `get_bucket_lifecycle_configuration` raises any other ClientError, THE collect_s3 Collector SHALL record the error separately from the missing-policy case
5. IF the collect_s3 Collector encounters an unhandled exception, THEN THE collect_s3 Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 6: Lambda Collector

**User Story:** As a DevOps engineer, I want Vapor to list Lambda function configurations, so that I can identify functions with excessive memory or timeout settings.

#### Acceptance Criteria

1. THE collect_lambda Collector SHALL paginate through all Lambda functions using `get_paginator("list_functions")`
2. THE collect_lambda Collector SHALL collect function_name, runtime, memory_size, timeout, last_modified, and code_size_bytes for each function
3. IF the collect_lambda Collector encounters an exception, THEN THE collect_lambda Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 7: EBS Collector

**User Story:** As a DevOps engineer, I want Vapor to find unattached EBS volumes, so that I can identify storage resources incurring cost with no compute attached.

#### Acceptance Criteria

1. THE collect_ebs Collector SHALL paginate through EBS volumes using `get_paginator("describe_volumes")` with a filter for status equal to "available"
2. THE collect_ebs Collector SHALL collect volume_id, size_gb, volume_type, create_time, availability_zone, and tags for each unattached volume
3. IF the collect_ebs Collector encounters an exception, THEN THE collect_ebs Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 8: EIP Collector

**User Story:** As a DevOps engineer, I want Vapor to find unassociated Elastic IPs, so that I can identify networking resources incurring hourly charges without providing value.

#### Acceptance Criteria

1. THE collect_eip Collector SHALL retrieve all Elastic IP addresses using `describe_addresses()`
2. THE collect_eip Collector SHALL identify unassociated EIPs by filtering for addresses where AssociationId or InstanceId is absent
3. THE collect_eip Collector SHALL collect allocation_id, public_ip, and tags for each unassociated EIP
4. IF the collect_eip Collector encounters an exception, THEN THE collect_eip Collector SHALL return an error dict with the error message and empty data list without raising the exception

### Requirement 9: Cost Explorer Collector

**User Story:** As a DevOps engineer, I want Vapor to retrieve cost data grouped by service, so that I can see the overall spend distribution for context in the audit report.

#### Acceptance Criteria

1. THE collect_cost_explorer Collector SHALL instantiate the Cost Explorer client with region_name set to "us-east-1" regardless of the configured scan region
2. THE collect_cost_explorer Collector SHALL query `get_cost_and_usage` with monthly granularity, grouped by SERVICE dimension, using UnblendedCost metrics over the configured window_days period
3. THE collect_cost_explorer Collector SHALL compute total_cost_usd by summing all service costs
4. IF Cost Explorer is not enabled or permissions are insufficient, THEN THE collect_cost_explorer Collector SHALL return a result with available set to false and an error description without raising an exception

### Requirement 10: Aggregate Node — Finding Normalization and Verdict Computation

**User Story:** As a DevOps engineer, I want all raw collector data normalized into a consistent finding structure with pre-computed verdicts, so that the LLM receives clean, structured input.

#### Acceptance Criteria

1. THE Aggregate_Node SHALL transform all raw collector outputs into a list of Finding TypedDicts with resource_id, resource_type, region, issue, verdict, estimated_monthly_cost_usd, data, and tags fields
2. WHEN an EC2 instance has cpu.no_data equal to true, THE Aggregate_Node SHALL assign a verdict of "no_data"
3. WHEN an EC2 instance has cpu.avg below the ec2_cpu_avg_threshold AND cpu.max below the ec2_cpu_max_threshold, THE Aggregate_Node SHALL assign a verdict of "underutilized"
4. WHEN an RDS instance has cpu.avg below the rds_cpu_avg_threshold AND connections_max below the rds_connections_threshold, THE Aggregate_Node SHALL assign a verdict of "underutilized"
5. WHEN an RDS instance has memory_free_pct above the rds_memory_free_pct_threshold, THE Aggregate_Node SHALL assign a verdict of "overprovisioned_memory"
6. WHEN an S3 bucket has has_lifecycle_policy equal to false, THE Aggregate_Node SHALL assign a verdict of "no_lifecycle_policy"
7. WHEN a Lambda function has memory_size greater than or equal to 1024 MB, THE Aggregate_Node SHALL assign a verdict of "high_memory"
8. WHEN a Lambda function has timeout greater than or equal to 900 seconds, THE Aggregate_Node SHALL assign a verdict of "high_timeout"
9. THE Aggregate_Node SHALL assign a verdict of "unattached" to all EBS volumes in the raw data
10. THE Aggregate_Node SHALL assign a verdict of "unassociated" to all EIP addresses in the raw data
11. THE Aggregate_Node SHALL compute estimated_monthly_cost_usd for EC2 instances using a hardcoded hourly rate lookup table multiplied by 730 hours
12. THE Aggregate_Node SHALL compute estimated_monthly_cost_usd for EBS volumes using per-GB monthly rates based on volume type (gp3: $0.08, gp2: $0.10, io1: $0.125)
13. THE Aggregate_Node SHALL set estimated_monthly_cost_usd to $3.65 for each unassociated EIP
14. THE Aggregate_Node SHALL convert all datetime objects to ISO 8601 strings using `.isoformat()` before storing in Finding data dictionaries
15. THE Aggregate_Node SHALL add a memory visibility note to each EC2 finding indicating that memory metrics are unavailable without the CloudWatch agent
16. WHEN a collector reports an error in the errors list, THE Aggregate_Node SHALL create a Finding with verdict "gap" describing the data collection failure

### Requirement 11: LLM Analysis Node

**User Story:** As a DevOps engineer, I want findings analyzed by GPT-5-mini to produce severity-tagged recommendations, so that I receive actionable cost optimization advice.

#### Acceptance Criteria

1. THE Analyze_Node SHALL send the normalized findings list to GPT-5-mini using temperature 0 and response_format set to json_object
2. THE Analyze_Node SHALL include the scan region, window_days, resource count, and threshold values in the user message sent to the LLM
3. THE Analyze_Node SHALL parse the LLM response JSON into an AnalysisResult containing a summary object and a findings list
4. THE AnalysisResult summary SHALL include totalFindings, criticalCount, highCount, mediumCount, lowCount, and estimatedMonthlySavings fields
5. WHEN each analyzed finding is produced, THE Analyze_Node SHALL include title, severity, category, resource_id, detail, estimated_savings, and fix fields
6. IF the OpenAI API call fails, THEN THE Analyze_Node SHALL produce a fallback AnalysisResult describing the failure without raising an exception
7. IF the LLM response JSON parsing fails, THEN THE Analyze_Node SHALL produce a fallback AnalysisResult describing the parsing error without raising an exception

### Requirement 12: Terminal Rendering with Rich

**User Story:** As a DevOps engineer, I want the audit report displayed with color-coded severity panels in the terminal, so that I can quickly identify critical findings.

#### Acceptance Criteria

1. WHEN the --output flag is not provided, THE Render_Node SHALL display the report in the terminal using rich panels
2. THE Render_Node SHALL display a header panel containing "Vapor — AWS Cost Audit Report" with the scan region and timestamp
3. THE Render_Node SHALL display a summary row showing total findings count, critical and high finding counts, and estimated monthly savings
4. THE Render_Node SHALL render each finding as a rich panel containing title, severity badge, category, resource_id, detail, estimated_savings, and fix fields
5. THE Render_Node SHALL color-code severity badges as bold red for critical, bold yellow for high, bold blue for medium, and bold green for low
6. THE Render_Node SHALL sort findings by severity in descending order from critical to low

### Requirement 13: JSON File Output

**User Story:** As a DevOps engineer, I want to export the audit report and raw collector data as JSON files, so that I can integrate findings with other tools or review them later.

#### Acceptance Criteria

1. WHEN the --output flag is provided with a file path, THE Render_Node SHALL write the full AnalysisResult as pretty-printed JSON to the specified path
2. WHEN writing JSON output, THE Render_Node SHALL use `default=str` in json.dumps to handle non-serializable objects
3. WHEN the --output flag is provided, THE Render_Node SHALL print a confirmation message to the terminal indicating the file was written
4. WHEN the --save-raw flag is provided with a file path, THE Render_Node SHALL write the raw collector state as pretty-printed JSON to the specified path before rendering the report

### Requirement 14: Error Resilience

**User Story:** As a DevOps engineer, I want the pipeline to continue operating even when individual collectors fail, so that I receive a partial report rather than no report.

#### Acceptance Criteria

1. THE Vapor CLI SHALL complete the full pipeline and produce a report even when one or more collectors encounter errors
2. THE Vapor CLI SHALL surface collector errors as gap findings in the final report rather than terminating the pipeline
3. WHEN a collector encounters a permissions error or service unavailability, THE Collector SHALL return an error structure with the error message and empty data without raising an exception
4. WHEN the LLM analysis fails, THE Vapor CLI SHALL produce a report containing the fallback analysis result and exit with code 0
