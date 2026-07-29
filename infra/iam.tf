
# ── IAM Role — identidade que a Lambda assume ─────────────────────
resource "aws_iam_role" "fx_lambda_role" {
  name = "${var.lambda_name}-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# ── Policy inline — permissões mínimas (least privilege) ──────────
resource "aws_iam_role_policy" "fx_lambda_policy" {
  name = "${var.lambda_name}-policy-${var.environment}"
  role = aws_iam_role.fx_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3PutReport"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${var.bucket_name}/fx-reports/*"
      },
      {
        Sid      = "SecretsManagerRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:*:*:secret:${var.secret_name}*"
      },
      {
        Sid      = "KMSAccess"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.fx_cmk.arn
      }
    ]
  })
}

# ── Policy gerenciada — permissão pra escrever logs no CloudWatch ─
resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.fx_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
