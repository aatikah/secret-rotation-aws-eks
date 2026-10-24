# Database module: a disposable, NON-PUBLIC PostgreSQL instance for rotation
# testing.
#
# Security posture:
#   * publicly_accessible = false (never reachable from the internet).
#   * Deployed into private subnets via a DB subnet group.
#   * A security group that admits PostgreSQL ONLY from the rotation Lambda's
#     security group (passed in) — no 0.0.0.0/0 ingress.
#   * storage_encrypted = true.
#
# Cost note: db.t4g.micro single-AZ is the smallest sensible instance. This is
# still a chargeable resource — see docs/costs.md. The whole module is gated by
# var.create so an environment can skip it (e.g. when testing against a local
# container instead).

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

resource "aws_db_subnet_group" "this" {
  count      = var.create ? 1 : 0
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "db" {
  count       = var.create ? 1 : 0
  name        = "${var.name_prefix}-db-sg"
  description = "PostgreSQL access for rotation Lambda only."
  vpc_id      = var.vpc_id
  tags        = var.tags
}

resource "aws_security_group_rule" "db_ingress_from_lambda" {
  count                    = var.create ? 1 : 0
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.db[0].id
  source_security_group_id = var.lambda_security_group_id
  description              = "PostgreSQL from rotation Lambda."
}

resource "aws_db_instance" "this" {
  count                       = var.create ? 1 : 0
  identifier                  = "${var.name_prefix}-pg"
  engine                      = "postgres"
  engine_version              = var.engine_version
  instance_class              = var.instance_class
  allocated_storage           = 20
  storage_encrypted           = true
  db_name                     = var.db_name
  username                    = var.master_username
  password                    = var.master_password
  db_subnet_group_name        = aws_db_subnet_group.this[0].name
  vpc_security_group_ids      = [aws_security_group.db[0].id]
  publicly_accessible         = false
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true
  allow_major_version_upgrade = false
  tags                        = var.tags
}
