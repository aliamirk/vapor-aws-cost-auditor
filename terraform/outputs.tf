##############################################################################
# Outputs — Quick reference after apply
##############################################################################

output "unattached_ebs_volumes" {
  description = "IDs of unattached EBS volumes (Vapor should flag all)"
  value = [
    aws_ebs_volume.wasteful_gp3_large.id,
    aws_ebs_volume.wasteful_gp2_medium.id,
    aws_ebs_volume.wasteful_io1.id,
    aws_ebs_volume.wasteful_gp3_small.id,
  ]
}

output "unassociated_eips" {
  description = "Allocation IDs of unassociated EIPs (Vapor should flag all)"
  value = [
    aws_eip.wasteful_eip_1.id,
    aws_eip.wasteful_eip_2.id,
    aws_eip.wasteful_eip_3.id,
  ]
}

output "s3_buckets_no_lifecycle" {
  description = "Buckets without lifecycle policies (Vapor should flag)"
  value = [
    aws_s3_bucket.no_lifecycle_logs.id,
    aws_s3_bucket.no_lifecycle_artifacts.id,
    aws_s3_bucket.no_lifecycle_backups.id,
  ]
}

output "s3_bucket_with_lifecycle" {
  description = "Bucket with lifecycle policy (Vapor should mark healthy)"
  value       = aws_s3_bucket.with_lifecycle.id
}

output "lambda_functions" {
  description = "Lambda functions and their expected Vapor verdicts"
  value = {
    high_memory         = aws_lambda_function.high_memory_function.function_name
    high_timeout        = aws_lambda_function.high_timeout_function.function_name
    high_memory_timeout = aws_lambda_function.high_memory_and_timeout.function_name
    healthy             = aws_lambda_function.healthy_function.function_name
  }
}

output "rds_instance" {
  description = "RDS instance (Vapor should flag as underutilized)"
  value       = aws_db_instance.wasteful_rds.identifier
}

output "estimated_monthly_waste" {
  description = "Approximate monthly cost of all wasteful resources"
  value       = <<-EOF
    EBS volumes: ~$18.35/mo (100GB gp3 + 50GB gp2 + 30GB io1 + 20GB gp3)
    EIPs: ~$10.95/mo (3 × $3.65)
    RDS: ~$50/mo (db.t3.medium idle)
    Lambda: $0/mo (no invocations, but config is wasteful)
    S3: $0/mo (empty, but no lifecycle = risk of unbounded growth)
    ---
    Total estimated waste: ~$79/mo
  EOF
}
