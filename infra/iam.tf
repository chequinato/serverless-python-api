
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
        # O ARN vem do recurso, não de var.bucket_name: o bucket real tem o
        # sufixo de ambiente ("-dev"), então o ARN montado à mão apontava
        # para um bucket que não existe e o PutObject dava AccessDenied.
        Sid      = "S3PutReport"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.fx_reports.arn}/fx-reports/*"
      },
      {
        # O trends.py, chamado no passo 5 da Lambda agendada, lê os
        # relatórios dos dias anteriores para calcular médias móveis e
        # streaks. Sem estas duas permissões a análise de tendência falha
        # calada (está dentro de um try/except que só loga warning).
        Sid      = "S3ReadHistory"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.fx_reports.arn}/fx-reports/*"
      },
      {
        Sid      = "S3ListHistory"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.fx_reports.arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["fx-reports/*"]
          }
        }
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


# ═══════════════════════════════════════════════════════════════════
# Role da Lambda de consulta (API Gateway)
#
# Identidade separada da Lambda agendada, de propósito. Esta Role:
#   - lê o S3, nunca escreve;
#   - não tem acesso nenhum ao Secrets Manager;
#   - usa o KMS só para descriptografar, não para gerar chave.
#
# Se a API for comprometida, o atacante consegue ler relatórios públicos
# de câmbio — e nada mais. Não dá para apagar o histórico nem alcançar a
# chave da API externa.
# ═══════════════════════════════════════════════════════════════════

resource "aws_iam_role" "fx_query_role" {
  name = "${var.query_lambda_name}-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "fx_query_policy" {
  name = "${var.query_lambda_name}-policy-${var.environment}"
  role = aws_iam_role.fx_query_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ReadReport"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.fx_reports.arn}/fx-reports/*"
      },
      {
        # Necessário porque o query.py chama list_objects_v2 para descobrir
        # qual é o relatório mais recente. ListBucket é permissão do bucket
        # (não do objeto), por isso o ARN vem sem o /* no fim — e a Condition
        # limita a listagem ao prefixo dos relatórios.
        Sid      = "S3ListReports"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.fx_reports.arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["fx-reports/*"]
          }
        }
      },
      {
        # Os objetos estão criptografados com SSE-KMS. Sem Decrypt na CMK,
        # o GetObject volta AccessDenied mesmo com a permissão de S3 acima —
        # pegadinha clássica de bucket com chave gerenciada pelo cliente.
        Sid      = "KMSDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.fx_cmk.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "query_basic_execution" {
  role       = aws_iam_role.fx_query_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
