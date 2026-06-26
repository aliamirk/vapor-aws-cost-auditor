##############################################################################
# RDS Instance — Over-provisioned and underutilized
#
# Vapor flags:
# - "underutilized" if CPU avg < 10% AND connections < 5
# - "overprovisioned_memory" if memory_free_pct > 75%
#
# A db.t3.medium with no real workload will trigger both conditions.
##############################################################################

# VPC for RDS (RDS requires a subnet group)
resource "aws_vpc" "rds_vpc" {
  cidr_block           = "10.99.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "vapor-test-rds-vpc"
  })
}

resource "aws_subnet" "rds_subnet_a" {
  vpc_id            = aws_vpc.rds_vpc.id
  cidr_block        = "10.99.1.0/24"
  availability_zone = "${var.region}a"

  tags = merge(local.common_tags, {
    Name = "vapor-test-rds-subnet-a"
  })
}

resource "aws_subnet" "rds_subnet_b" {
  vpc_id            = aws_vpc.rds_vpc.id
  cidr_block        = "10.99.2.0/24"
  availability_zone = "${var.region}b"

  tags = merge(local.common_tags, {
    Name = "vapor-test-rds-subnet-b"
  })
}

resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "vapor-test-rds-subnet-group"
  subnet_ids = [aws_subnet.rds_subnet_a.id, aws_subnet.rds_subnet_b.id]

  tags = merge(local.common_tags, {
    Name = "vapor-test-rds-subnet-group"
  })
}

# Security group — no inbound (ensures zero connections = underutilized)
resource "aws_security_group" "rds_sg" {
  name        = "vapor-test-rds-sg"
  description = "No inbound - ensures RDS stays idle for Vapor testing"
  vpc_id      = aws_vpc.rds_vpc.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "vapor-test-rds-sg"
  })
}

# RDS instance — db.t3.medium (4 GB RAM), idle, over-provisioned
resource "aws_db_instance" "wasteful_rds" {
  identifier     = "vapor-test-idle-db"
  engine         = "mysql"
  engine_version = "8.0"
  instance_class = "db.t3.medium"

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "vaportest"
  username = "admin"
  password = "VaporTest2024!" # Test only — not production

  db_subnet_group_name   = aws_db_subnet_group.rds_subnet_group.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]

  publicly_accessible = false
  multi_az            = false
  skip_final_snapshot = true

  # No backups needed for test
  backup_retention_period = 0

  tags = merge(local.common_tags, {
    Name = "vapor-test-idle-db"
    Note = "Idle RDS - Vapor should flag as underutilized + overprovisioned_memory"
  })
}
