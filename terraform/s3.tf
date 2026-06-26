##############################################################################
# S3 Buckets Without Lifecycle Policies — Vapor flags as "no_lifecycle_policy"
#
# Buckets without lifecycle rules can accumulate unbounded storage costs.
# These are created with no lifecycle configuration.
##############################################################################

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# Bucket 1 — no lifecycle policy, simulates a forgotten log bucket
resource "aws_s3_bucket" "no_lifecycle_logs" {
  bucket = "vapor-test-logs-no-lifecycle-${random_id.bucket_suffix.hex}"

  tags = merge(local.common_tags, {
    Name = "vapor-test-logs-no-lifecycle"
    Note = "No lifecycle policy — Vapor should flag this"
  })
}

# Bucket 2 — no lifecycle policy, simulates an artifacts bucket
resource "aws_s3_bucket" "no_lifecycle_artifacts" {
  bucket = "vapor-test-artifacts-no-lifecycle-${random_id.bucket_suffix.hex}"

  tags = merge(local.common_tags, {
    Name = "vapor-test-artifacts-no-lifecycle"
    Note = "No lifecycle policy — Vapor should flag this"
  })
}

# Bucket 3 — no lifecycle policy, simulates a backups bucket
resource "aws_s3_bucket" "no_lifecycle_backups" {
  bucket = "vapor-test-backups-no-lifecycle-${random_id.bucket_suffix.hex}"

  tags = merge(local.common_tags, {
    Name = "vapor-test-backups-no-lifecycle"
    Note = "No lifecycle policy — Vapor should flag this"
  })
}

# Bucket 4 — HAS a lifecycle policy (control — Vapor should mark as healthy)
resource "aws_s3_bucket" "with_lifecycle" {
  bucket = "vapor-test-with-lifecycle-${random_id.bucket_suffix.hex}"

  tags = merge(local.common_tags, {
    Name = "vapor-test-with-lifecycle"
    Note = "Has lifecycle policy — Vapor should mark healthy"
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "with_lifecycle_rules" {
  bucket = aws_s3_bucket.with_lifecycle.id

  rule {
    id     = "expire-old-objects"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}
