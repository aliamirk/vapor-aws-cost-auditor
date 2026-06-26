##############################################################################
# Unassociated Elastic IPs — Vapor flags these as "unassociated_eip"
#
# Each unassociated EIP costs $0.005/hour = $3.65/month.
# Creating 3 of them = ~$10.95/mo wasted.
##############################################################################

resource "aws_eip" "wasteful_eip_1" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unassociated-eip-1"
    Note = "Deliberately unassociated for Vapor testing"
  })
}

resource "aws_eip" "wasteful_eip_2" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unassociated-eip-2"
    Note = "Deliberately unassociated for Vapor testing"
  })
}

resource "aws_eip" "wasteful_eip_3" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "vapor-test-unassociated-eip-3"
    Note = "Deliberately unassociated for Vapor testing"
  })
}
