##############################################################################
# Unattached EBS Volumes — Vapor flags these as "unattached_volume"
#
# These volumes are created without being attached to any instance.
# They sit idle incurring storage charges.
##############################################################################

# Large GP3 volume — $0.08/GB/mo = $8.00/mo wasted
resource "aws_ebs_volume" "wasteful_gp3_large" {
  availability_zone = "${var.region}a"
  size              = 100 # 100 GB
  type              = "gp3"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unattached-gp3-100gb"
    Note = "Deliberately unattached for Vapor testing"
  })
}

# Medium GP2 volume — $0.10/GB/mo = $5.00/mo wasted
resource "aws_ebs_volume" "wasteful_gp2_medium" {
  availability_zone = "${var.region}a"
  size              = 50 # 50 GB
  type              = "gp2"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unattached-gp2-50gb"
    Note = "Deliberately unattached for Vapor testing"
  })
}

# IO1 volume (expensive) — $0.125/GB/mo = $3.75/mo wasted
resource "aws_ebs_volume" "wasteful_io1" {
  availability_zone = "${var.region}a"
  size              = 30 # 30 GB
  type              = "io1"
  iops              = 100

  tags = merge(local.common_tags, {
    Name = "vapor-test-unattached-io1-30gb"
    Note = "Deliberately unattached for Vapor testing"
  })
}

# Another GP3 — small but still wasted — $0.08/GB/mo = $1.60/mo
resource "aws_ebs_volume" "wasteful_gp3_small" {
  availability_zone = "${var.region}b"
  size              = 20 # 20 GB
  type              = "gp3"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unattached-gp3-20gb"
    Note = "Deliberately unattached for Vapor testing"
  })
}
