
output "lambda_arn" {
  description = "ARN da Lambda"
  value       = "aws_lambda_function.fx_processor.arn"
}

output "bucket_name" {
  description = "Nome do bucket S3 de relatórios"
  value       = aws_s3_bucket.fx_reports.bucket
}

output "bucket_arn" {
  description = "ARN do bucket S3"
  value       = aws_s3_bucket.fx_reports.arn
}

output "secret_arn" {
  description = "ARN do secret no Secrets Manager"
  value       = aws_secretsmanager_secret.fx_api_key.arn
}

output "kms_key_arn" {
  description = "ARN da CMK no KMS"
  value       = aws_kms_key.fx_cmk.arn
}

output "lambda_role_arn" {
  description = "ARN da IAM Role da Lambda"
  value       = aws_iam_role.fx_lambda_role.arn
}
