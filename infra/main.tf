
provider "aws" {
  region = "us-east-1"
}

# ── KMS — chave gerenciada pelo cliente ───────────────────────────
resource "aws_kms_key" "fx_cmk" {
  description             = "CMK para criptografar secrets e objetos S3 do FX Lambda"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "fx_cmk_alias" {
  name          = var.kms_alias
  target_key_id = aws_kms_key.fx_cmk.key_id
}

# ── Secrets Manager — armazena a chave de API ─────────────────────
resource "aws_secretsmanager_secret" "fx_api_key" {
  name       = var.secret_name
  kms_key_id = aws_kms_key.fx_cmk.arn
}

resource "aws_secretsmanager_secret_version" "fx_api_key_value" {
  secret_id     = aws_secretsmanager_secret.fx_api_key.id
  secret_string = jsonencode({
    api_key = "substitua_pela_chave_real"
  })
}

# ── S3 — bucket de relatórios ─────────────────────────────────────
resource "aws_s3_bucket" "fx_reports" {
  bucket = "${var.bucket_name}-${var.environment}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "fx_reports_sse" {
  bucket = aws_s3_bucket.fx_reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.fx_cmk.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "fx_reports_block" {
  bucket                  = aws_s3_bucket.fx_reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Lambda — empacotamento e criação ─────────────────────────────
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/dist/lambda_function.zip"
}

resource "aws_lambda_function" "fx_processor" {
  filename      = data.archive_file.lambda_zip.output_path
  function_name = var.lambda_name
  role          = aws_iam_role.fx_lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"

  environment {
    variables = {
      FX_BUCKET_NAME = var.bucket_name
      FX_KMS_KEY_ID  = aws_kms_key.fx_cmk.arn
      SECRET_NAME    = var.secret_name
      AWS_REGION     = "us-east-1"
    }
  }
}

# ── EventBridge — agendamento diário ─────────────────────────────
resource "aws_cloudwatch_event_rule" "cron_rule" {
  name                = "fx-lambda-schedule-${var.environment}"
  description         = "Dispara a Lambda de câmbio todo dia às 08h UTC"
  schedule_expression = "cron(0 8 * * ? *)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.cron_rule.name
  target_id = "EnviarParaLambda"
  arn       = aws_lambda_function.fx_processor.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fx_processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cron_rule.arn
}
