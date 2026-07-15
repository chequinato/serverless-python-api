
import json
from datetime import datetime
import os
import boto3

BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
KMS_KEY = os.environ.get("KMS_KEY", "")


def to_json(report: dict) -> str:
    return json.dumps(report)

def path_s3(base: str, generated_at: str) -> str:

    objeto_data = datetime.fromisoformat(generated_at)

    year = objeto_data.year
    month = objeto_data.month
    day = objeto_data.day

    return (
        f"fx-reports/year={year}/month={month:02d}/day={day:02d}/"
        f"report_{base}_{objeto_data.strftime('%Y%m%dT%H%M%SZ')}.json"
    )

def upload_s3(json_str: str, key: str) -> str:

    body = json_str.encode("utf-8")

    s3_client = boto3.client("s3")

    params = {
        "Bucket": BUCKET_NAME,
        "Key": key,
        "Body": body,
        "ContentType": "application/json",
    }

    if KMS_KEY:
        params['ServerSideEncryption'] = "aws:kms"
        params['SSEKMSKeyId'] = KMS_KEY
    else:
        params['ServerSideEncryption'] = "AES256"

    s3_client.put_object(**params)

    return f"s3://{BUCKET_NAME}/{key}"

def save_local(json_str: str) -> str:

    agora = datetime.now()
    nome = agora.strftime("%Y%m%d%H%M%S")

    caminho = f"output/report_{nome}.json"

    with open(caminho, "w") as f:
        f.write(json_str)

    return caminho

