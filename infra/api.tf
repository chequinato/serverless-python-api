# ═══════════════════════════════════════════════════════════════════
# api.tf — API Gateway de consulta + Lambda somente leitura
#
# Esta é a porta de entrada sob demanda do projeto. A Lambda agendada
# (main.tf) escreve os relatórios no S3 uma vez por dia; esta Lambda só
# lê o que já está lá e devolve por HTTP.
#
# Por que uma segunda Lambda, e não a mesma:
#   1. Cota — a Lambda agendada gasta 2 chamadas das APIs externas por
#      execução. O plano gratuito é 1.500/mês. Se cada visita ao endpoint
#      disparasse o fluxo completo, a cota acabaria em poucos dias.
#   2. Permissão — a Role de consulta não precisa do Secrets Manager nem
#      de escrita no S3. Menor privilégio de verdade, não no discurso.
#   3. Latência — ler um JSON do S3 responde em milissegundos; chamar duas
#      APIs externas leva segundos e pode falhar por causa de terceiros.
#
# Usa HTTP API (apigatewayv2) e não REST API (apigateway v1): são ~7
# recursos em vez de ~20, custa cerca de 1/3 do preço e já traz CORS
# nativo. REST API só valeria por recursos que o projeto não usa
# (API keys, usage plans, transformação de request/response).
# ═══════════════════════════════════════════════════════════════════

# ── Lambda de consulta ────────────────────────────────────────────
# Mesmo pacote .zip da Lambda agendada — os dois handlers vivem no
# mesmo src/. Muda só qual função a AWS chama na entrada.
resource "aws_lambda_function" "fx_query_api" {
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  function_name    = var.query_lambda_name
  role             = aws_iam_role.fx_query_role.arn
  handler          = "api_handler.lambda_handler"
  runtime          = "python3.12"

  # O endpoint /trends varre até 30 prefixos no S3, um por dia da janela.
  # 20s cobre o pior caso e ainda fica abaixo do limite de 29s do API Gateway.
  timeout     = 20
  memory_size = 256

  environment {
    variables = {
      # Aponta para o bucket real criado pelo Terraform, com o sufixo de
      # ambiente incluído — e não para var.bucket_name cru.
      FX_BUCKET_NAME   = aws_s3_bucket.fx_reports.bucket
      FX_BASE_CURRENCY = var.base_currency
    }
  }
}

# ── Log group da Lambda de consulta ───────────────────────────────
# Criado explicitamente para ter retenção definida. Sem isso a AWS cria
# o grupo na primeira execução com retenção "nunca expira" — e a conta
# de CloudWatch cresce para sempre.
resource "aws_cloudwatch_log_group" "fx_query_logs" {
  name              = "/aws/lambda/${var.query_lambda_name}"
  retention_in_days = var.log_retention_days
}

# ── HTTP API ──────────────────────────────────────────────────────
resource "aws_apigatewayv2_api" "fx_api" {
  name          = "fx-query-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "API de consulta dos relatórios de câmbio já processados"

  # CORS resolvido na borda, não no código Python: o navegador manda um
  # OPTIONS antes do GET e o API Gateway responde sozinho, sem invocar
  # a Lambda (e sem cobrar por essa invocação).
  cors_configuration {
    allow_origins = var.api_allowed_origins
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["content-type"]
    max_age       = 300
  }
}

# ── Integração Lambda ─────────────────────────────────────────────
resource "aws_apigatewayv2_integration" "fx_query_integration" {
  api_id                 = aws_apigatewayv2_api.fx_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fx_query_api.invoke_arn
  payload_format_version = "2.0"

  # Limite duro do API Gateway. Se a Lambda passar disso, quem chamou
  # recebe 504 — por isso o timeout da Lambda (20s) é menor.
  timeout_milliseconds = 29000
}

# ── Rotas ─────────────────────────────────────────────────────────
# Uma rota por endpoint, todas apontando para a mesma integração. O
# roteamento fino (qual função atende qual caminho) está na tabela ROUTES
# do api_handler.py.
#
# Declarar as rotas aqui, em vez de usar um "$default" que aceita tudo,
# faz o API Gateway rejeitar caminho desconhecido na borda: a Lambda nem
# é invocada, então URL errada e varredura de robô não geram custo.
#
# O for_each evita quatro blocos quase idênticos — cada item da lista
# vira um recurso, identificado pelo próprio texto da rota.
resource "aws_apigatewayv2_route" "fx_query_routes" {
  for_each = toset([
    "GET /health",
    "GET /reports/latest",
    "GET /alerts",
    "GET /trends",
  ])

  api_id    = aws_apigatewayv2_api.fx_api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.fx_query_integration.id}"
}

# ── Log group dos acessos da API ──────────────────────────────────
resource "aws_cloudwatch_log_group" "fx_api_access_logs" {
  name              = "/aws/apigateway/fx-query-api-${var.environment}"
  retention_in_days = var.log_retention_days
}

# ── Stage ─────────────────────────────────────────────────────────
resource "aws_apigatewayv2_stage" "fx_api_stage" {
  api_id      = aws_apigatewayv2_api.fx_api.id
  name        = var.api_stage_name
  auto_deploy = true

  # Log de acesso em JSON — dá para consultar com CloudWatch Logs Insights
  # sem precisar parsear texto solto.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.fx_api_access_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      latencyMs      = "$context.responseLatency"
      integrationErr = "$context.integrationErrorMessage"
    })
  }

  # Throttling: a API é pública e só serve leitura, mas sem limite uma
  # rajada de requisições viraria conta de Lambda + S3. Os valores são
  # folgados para uso normal e cortam abuso.
  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst
    throttling_rate_limit  = var.api_throttle_rate
  }
}

# ── Permissão para o API Gateway invocar a Lambda ─────────────────
# Sem isso o endpoint responde 500: a Lambda existe, a rota existe, mas
# o API Gateway não tem autorização para chamá-la.
resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fx_query_api.function_name
  principal     = "apigateway.amazonaws.com"

  # Restringe à API específica. O "/*/*" final libera qualquer stage e
  # qualquer rota desta API — sem ele, cada rota exigiria uma permissão.
  source_arn = "${aws_apigatewayv2_api.fx_api.execution_arn}/*/*"
}
