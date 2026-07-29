"""
secrets.py — Gerenciamento de credenciais

Responsabilidade:
  Buscar a chave de API de forma segura, sem expô-la no código.

Estratégia por ambiente:
  - AWS (produção) → busca no Secrets Manager, descriptografado via KMS
  - Local (dev)    → lê da variável de ambiente EXCHANGERATE_API_KEY

O ambiente é detectado automaticamente pela variável AWS_EXECUTION_ENV,
que só existe quando o código está rodando dentro de uma Lambda.

Fluxo na AWS:
  Lambda assume IAM Role
    → chama Secrets Manager (GetSecretValue)
    → Secrets Manager chama KMS (Decrypt)
    → retorna a chave descriptografada

Variáveis de ambiente esperadas:
  - SECRET_NAME          → nome do secret (padrão: fx-lambda/exchangerate-api-key)
  - AWS_REGION           → região do Secrets Manager (padrão: us-east-1)
  - EXCHANGERATE_API_KEY → apenas para dev local
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

# ── Configurações via variáveis de ambiente ───────────────────────
SECRET_NAME = os.environ.get("SECRET_NAME", "fx-lambda/exchangerate-api-key")
REGION      = os.environ.get("AWS_REGION", "us-east-1")


def get_api_key() -> str:
    """
    Ponto de entrada público — retorna a chave de API.

    Detecta o ambiente automaticamente:
      - AWS_EXECUTION_ENV presente → produção → usa Secrets Manager
      - AWS_EXECUTION_ENV ausente  → local    → usa variável de ambiente
    """
    is_aws = os.environ.get("AWS_EXECUTION_ENV")

    if is_aws:
        return _get_from_aws()
    else:
        return _get_from_env()


def _get_from_aws() -> str:
    """
    Busca a chave de API no AWS Secrets Manager.

    O secret deve ter o formato JSON: {"api_key": "sua_chave_aqui"}
    A descriptografia é feita automaticamente pelo KMS via CMK configurada no secret.

    Lança RuntimeError em caso de falha de acesso ou secret malformado.
    """
    client = boto3.client("secretsmanager", region_name=REGION)

    try:
        request = client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as e:
        raise RuntimeError(f"Erro ao buscar secret no Secrets Manager: {e}")

    secret_dict = json.loads(request["SecretString"])
    logging.info("Secret recuperado com sucesso do Secrets Manager.")

    return secret_dict["api_key"]


def _get_from_env() -> str:
    """
    Lê a chave de API da variável de ambiente EXCHANGERATE_API_KEY.
    Usado apenas em desenvolvimento local.

    Para configurar:
      export EXCHANGERATE_API_KEY='sua_chave_aqui'

    Lança RuntimeError se a variável não estiver definida.
    """
    api_key = os.environ.get("EXCHANGERATE_API_KEY")
    logging.info("Buscando chave de API em variável de ambiente (modo local).")

    if not api_key:
        raise RuntimeError(
            "Variável de ambiente EXCHANGERATE_API_KEY não definida. "
            "Execute: export EXCHANGERATE_API_KEY='sua_chave_aqui'"
        )

    return api_key
