
'''
1. verificar se está na AWS ou local
2. se AWS → buscar no Secrets Manager → json.loads → retornar api_key
3. se local → ler variável de ambiente → retornar
'''

import json
import logging
import os
import boto3
from botocore.exceptions import ClientError

SECRET_NAME = os.environ.get("SECRET_NAME", "fx-lambda/exchangerate-api-key")
REGION = os.environ.get("AWS_REGION", "us-east-1")

def get_api_key() -> str:

    is_aws = os.environ.get("AWS_EXECUTION_ENV")

    if is_aws:
        return _get_from_aws()
    else:
        return _get_from_env()

def _get_from_aws() -> str:

    client = boto3.client("secretsmanager", region_name=REGION)

    try:
        request = client.get_secret_value(SecretId=SECRET_NAME)

    except ClientError as e:
        raise RuntimeError(f"Erro ao buscar secret: {e}")

    secret_dict = json.loads(request["SecretString"])
    logging.info((secret_dict))

    return secret_dict["api_key"]

def _get_from_env() -> str:

    api_env = os.environ.get("EXCHANGERATE_API_KEY")
    logging.info((api_env))

    if not api_env:
        raise RuntimeError(f"Erro ao buscar secret: {api_env}")

    return api_env