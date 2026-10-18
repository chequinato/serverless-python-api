
output "lambda_arn" {
  description = "ARN da Lambda"
  value       = aws_lambda_function.fx_processor.arn
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

# ── API de consulta ───────────────────────────────────────────────

output "api_base_url" {
  description = "URL base da API de consulta — cole no navegador ou no curl"
  value       = aws_apigatewayv2_stage.fx_api_stage.invoke_url
}

output "api_endpoints" {
  description = "Endpoints disponíveis na API de consulta"
  value = [
    "GET ${aws_apigatewayv2_stage.fx_api_stage.invoke_url}/health",
    "GET ${aws_apigatewayv2_stage.fx_api_stage.invoke_url}/reports/latest",
    "GET ${aws_apigatewayv2_stage.fx_api_stage.invoke_url}/reports/latest?currency=BRL",
    "GET ${aws_apigatewayv2_stage.fx_api_stage.invoke_url}/alerts",
    "GET ${aws_apigatewayv2_stage.fx_api_stage.invoke_url}/trends?days=7",
  ]
}

output "query_lambda_arn" {
  description = "ARN da Lambda de consulta"
  value       = aws_lambda_function.fx_query_api.arn
}

output "query_lambda_role_arn" {
  description = "ARN da IAM Role somente leitura da Lambda de consulta"
  value       = aws_iam_role.fx_query_role.arn
}
