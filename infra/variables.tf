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
