variable "bucket_name" {
  description = "Nome do bucket para persistir os relatórios de câmbio"
  type        = string
  default     = "fx-reports-bucket"
}

variable "lambda_name" {
  description = "Nome da Lambda que executa o processamento"
  type        = string
  default     = "fx-exchange-rate-processor"
}

variable "secret_name" {
  description = "Nome do secret no Secrets Manager"
  type        = string
  default     = "fx-lambda/exchangerate-api-key"
}

variable "kms_alias" {
  description = "Alias da CMK no KMS"
  type        = string
  default     = "alias/fx-cmk"
}

variable "environment" {
  description = "Ambiente de deploy"
  type        = string
  default     = "dev"
}

variable "base_currency" {
  description = "Moeda base usada para buscar as cotações"
  type        = string
  default     = "USD"
}

# ── API de consulta ───────────────────────────────────────────────

variable "query_lambda_name" {
  description = "Nome da Lambda que atende as consultas via API Gateway"
  type        = string
  default     = "fx-exchange-rate-query"
}

variable "api_stage_name" {
  description = "Nome do stage do API Gateway — entra na URL (ex: /v1/alerts)"
  type        = string
  default     = "v1"
}

variable "api_allowed_origins" {
  description = "Origens liberadas no CORS. Use o domínio do seu front em produção."
  type        = list(string)
  default     = ["*"]
}

variable "api_throttle_rate" {
  description = "Requisições por segundo aceitas em regime normal"
  type        = number
  default     = 20
}

variable "api_throttle_burst" {
  description = "Rajada máxima de requisições simultâneas aceitas"
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "Dias de retenção dos logs no CloudWatch"
  type        = number
  default     = 14
}
