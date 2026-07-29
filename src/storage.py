"""
storage.py — Persistência do relatório de câmbio

Responsabilidade:
  Converter o relatório em JSON e salvá-lo no S3 (produção)
  ou em arquivo local (desenvolvimento).

Funções:
  to_json(report)          → converte dicionário para string JSON
  path_s3(base, date)      → monta o caminho Hive-style no S3
  upload_s3(json_str, key) → faz upload pro S3 com criptografia SSE-KMS
  save_local(json_str)     → salva localmente com nome único por timestamp

Estrutura no bucket S3 (Hive-style — compatível com Athena e Glue):
  fx-reports/year=2024/month=03/day=10/report_USD_20240310T080000Z.json

Variáveis de ambiente esperadas:
  - FX_BUCKET_NAME → nome do bucket S3
  - FX_KMS_KEY_ID  → ARN da CMK para SSE-KMS (usa SSE-S3 se ausente)
"""

import json
import os
import boto3
from datetime import datetime

# ── Configurações via variáveis de ambiente ───────────────────────
BUCKET_NAME = os.environ.get("FX_BUCKET_NAME", "")
KMS_KEY     = os.environ.get("FX_KMS_KEY_ID", "")


def to_json(report: dict) -> str:
    """
    Converte o dicionário do relatório em string JSON.

    Parâmetros:
      report → dicionário retornado por FXReport.to_dict()

    Retorna:
      String JSON serializada.
    """
    return json.dumps(report)


def path_s3(base: str, generated_at: str) -> str:
    """
    Monta o caminho (key) do objeto no S3 com particionamento Hive-style.

    Parâmetros:
      base         → moeda base do relatório (ex: "USD")
      generated_at → data/hora ISO 8601 de geração do relatório

    Retorna:
      String com o caminho completo no S3.
      Ex: fx-reports/year=2024/month=03/day=10/report_USD_20240310T080000Z.json
    """
    objeto_data = datetime.fromisoformat(generated_at)

    year  = objeto_data.year
    month = objeto_data.month
    day   = objeto_data.day

    return (
        f"fx-reports/year={year}/month={month:02d}/day={day:02d}/"
        f"report_{base}_{objeto_data.strftime('%Y%m%dT%H%M%SZ')}.json"
    )


def upload_s3(json_str: str, key: str) -> str:
    """
    Faz upload do relatório JSON para o bucket S3.

    Usa SSE-KMS se FX_KMS_KEY_ID estiver configurado.
    Caso contrário, usa SSE-S3 (criptografia padrão da AWS).

    Parâmetros:
      json_str → conteúdo do relatório em string JSON
      key      → caminho do objeto no S3 (gerado por path_s3)

    Retorna:
      URI do objeto salvo. Ex: s3://bucket/fx-reports/.../report.json
    """
    body = json_str.encode("utf-8")

    s3_client = boto3.client("s3")

    params = {
        "Bucket":      BUCKET_NAME,
        "Key":         key,
        "Body":        body,
        "ContentType": "application/json",
    }

    # Ativa SSE-KMS se uma CMK foi configurada, senão usa SSE-S3
    if KMS_KEY:
        params["ServerSideEncryption"] = "aws:kms"
        params["SSEKMSKeyId"]          = KMS_KEY
    else:
        params["ServerSideEncryption"] = "AES256"

    s3_client.put_object(**params)

    return f"s3://{BUCKET_NAME}/{key}"


def save_local(json_str: str) -> str:
    """
    Salva o relatório localmente em arquivo JSON.
    Usado em desenvolvimento para simular o upload S3.

    Parâmetros:
      json_str → conteúdo do relatório em string JSON

    Retorna:
      Caminho do arquivo salvo. Ex: output/report_20240310080000.json
    """
    agora = datetime.now()
    nome  = agora.strftime("%Y%m%d%H%M%S")

    caminho = f"output/report_{nome}.json"

    os.makedirs("output", exist_ok=True)

    with open(caminho, "w") as f:
        f.write(json_str)

    return caminho
