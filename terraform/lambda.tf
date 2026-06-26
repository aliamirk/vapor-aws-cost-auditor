##############################################################################
# Lambda Functions with Excessive Configuration — Vapor flags these
#
# - high_memory: memory_size >= 1024 MB
# - high_timeout: timeout >= 900 seconds (15 minutes)
##############################################################################

# IAM role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "vapor-test-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Dummy Lambda code
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/lambda_function.zip"

  source {
    content  = <<-EOF
      def handler(event, context):
          return {"statusCode": 200, "body": "hello from vapor test"}
    EOF
    filename = "lambda_function.py"
  }
}

# Lambda 1 — Excessive memory (3008 MB) — Vapor flags as "high_memory"
resource "aws_lambda_function" "high_memory_function" {
  function_name = "vapor-test-high-memory"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.12"
  filename      = data.archive_file.lambda_zip.output_path
  memory_size   = 3008 # Way more than needed for a hello world
  timeout       = 30

  tags = merge(local.common_tags, {
    Name = "vapor-test-high-memory"
    Note = "3008 MB memory - Vapor should flag as high_memory"
  })
}

# Lambda 2 — Excessive timeout (900s = 15 min) — Vapor flags as "high_timeout"
resource "aws_lambda_function" "high_timeout_function" {
  function_name = "vapor-test-high-timeout"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.12"
  filename      = data.archive_file.lambda_zip.output_path
  memory_size   = 128
  timeout       = 900 # Maximum timeout — rarely needed

  tags = merge(local.common_tags, {
    Name = "vapor-test-high-timeout"
    Note = "900s timeout - Vapor should flag as high_timeout"
  })
}

# Lambda 3 — Both excessive memory AND timeout
resource "aws_lambda_function" "high_memory_and_timeout" {
  function_name = "vapor-test-high-both"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.12"
  filename      = data.archive_file.lambda_zip.output_path
  memory_size   = 2048
  timeout       = 900

  tags = merge(local.common_tags, {
    Name = "vapor-test-high-both"
    Note = "2048 MB + 900s - Vapor should flag both"
  })
}

# Lambda 4 — Normal config (control — Vapor should mark as healthy)
resource "aws_lambda_function" "healthy_function" {
  function_name = "vapor-test-healthy"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.12"
  filename      = data.archive_file.lambda_zip.output_path
  memory_size   = 256
  timeout       = 30

  tags = merge(local.common_tags, {
    Name = "vapor-test-healthy"
    Note = "Normal config - Vapor should mark healthy"
  })
}
