"""
lambda_function.py — Handler principal da AWS Lambda

Responsabilidade:
  Orquestrar todo o fluxo de processamento de taxas de câmbio.
  Este é o único arquivo que a AWS conhece — é o entry point configurado no console.

Fluxo:
  1. Busca a chave de API no Secrets Manager (ou variável de ambiente local)
  2. Chama a ExchangeRate-API → taxas em tempo real
  3. Chama a Open Exchange Rates → taxas do dia anterior
  4. Processa os dados → calcula variações e gera alertas
  5. Salva o relatório no S3 (produção) ou localmente (desenvolvimento)

Variáveis de ambiente esperadas:
  - EXCHANGERATE_API_KEY → apenas para dev local
  - FX_BUCKET_NAME       → nome do bucket S3
  - FX_KMS_KEY_ID        → ARN da CMK para SSE-KMS
  - SECRET_NAME          → nome do secret no Secrets Manager
  - AWS_REGION           → região AWS (padrão: us-east-1)
"""

import json
import logging
import os

from src.secrets import get_api_key
from src.api_client import fetch_live_rates, fetch_historical_rates
from src.api_client import APIError, APIRateLimitError, APIAuthError
from src.processor import process
from src.storage import save_local, upload_s3, to_json, path_s3

# Detecta se está rodando na AWS ou localmente
IS_AWS = bool(os.environ.get("AWS_EXECUTION_ENV"))


def _response(status_code: int, body: dict) -> dict:
    """
    Monta a resposta no formato esperado pelo API Gateway.

    Parâmetros:
      status_code → código HTTP (200, 401, 500, etc.)
      body        → dicionário com o conteúdo da resposta

    Retorna:
      Dicionário com statusCode e body serializado em JSON.
    """
    return {
        "statusCode": status_code,
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event, context):
    """
    Ponto de entrada da Lambda — chamado automaticamente pela AWS.

    Parâmetros:
      event   → payload enviado pelo trigger (EventBridge, API Gateway, etc.)
      context → metadados da execução (tempo restante, nome da função, etc.)

    Retorna:
      Dicionário no formato API Gateway com statusCode e body.
    """

    # ── Passo 1: Buscar a chave de API ────────────────────────────
    # Em produção vem do Secrets Manager. Localmente, de variável de ambiente.
    try:
        api_key = get_api_key()
    except RuntimeError:
        return _response(500, {"error": "Erro ao buscar credenciais no Secrets Manager."})
    except EnvironmentError:
        return _response(500, {"error": "Variável de ambiente EXCHANGERATE_API_KEY não definida."})

    # ── Passo 2: Buscar taxas em tempo real ───────────────────────
    # Chama a ExchangeRate-API com a chave obtida no passo 1.
    try:
        live_rates = fetch_live_rates(api_key)
    except APIAuthError as e:
        return _response(401, {"error": str(e)})
    except APIRateLimitError as e:
        return _response(429, {"error": str(e)})
    except APIError as e:
        return _response(502, {"error": str(e)})

    # ── Passo 3: Buscar taxas históricas (D-1) ────────────────────
    # Chama a Open Exchange Rates para obter as taxas do dia anterior.
    try:
        historical_rates = fetch_historical_rates(api_key)
    except APIAuthError as e:
        return _response(401, {"error": str(e)})
    except APIRateLimitError as e:
        return _response(429, {"error": str(e)})
    except APIError as e:
        return _response(502, {"error": str(e)})

    # ── Passo 4: Processar dados e calcular variações ─────────────
    # Cruza as taxas live e históricas, calcula deltas e detecta alertas.
    try:
        report = process(live_rates, historical_rates)
    except RuntimeError as e:
        return _response(500, {"error": str(e)})

    # ── Passo 5: Salvar o relatório ───────────────────────────────
    # Em produção: sobe pro S3 com SSE-KMS.
    # Localmente: salva em arquivo JSON na pasta output/.
    json_str = to_json(report.to_dict())
    key = path_s3(report.base_currency, report.generated_at)

    if IS_AWS:
        try:
            upload_s3(json_str, key)
        except Exception as e:
            # Erro de storage não cancela o processamento — só loga
            logging.error(f"Erro ao salvar no S3: {e}")
    else:
        save_local(json_str)

    return _response(200, {"message": "ok", "alerts": report.alerts})
