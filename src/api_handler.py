"""
api_handler.py — Handler da Lambda de consulta (API Gateway)

Responsabilidade:
  Receber requisições HTTP do API Gateway, rotear para a consulta certa
  e devolver a resposta no formato que o API Gateway espera.

Este é o **segundo entry point** do projeto. São duas Lambdas, com papéis
e permissões diferentes, lendo o mesmo bucket:

  lambda_function.lambda_handler → disparada pelo EventBridge (1x/dia)
                                   escreve relatório no S3
  api_handler.lambda_handler     → disparada pelo API Gateway (sob demanda)
                                   só lê o S3, nunca escreve

Separar as duas é o ponto central desta feature. Se fosse uma Lambda só,
cada visita ao endpoint gastaria 2 requisições das APIs externas — o plano
gratuito (1.500 req/mês) morreria em dias. E a Role da API não precisa de
acesso ao Secrets Manager nem de permissão de escrita: menor privilégio.

Endpoints:
  GET /health          → status da API e ambiente detectado
  GET /reports/latest  → relatório mais recente completo
                         ?currency=BRL → recorte de uma moeda só
  GET /alerts          → alertas do relatório mais recente, com contexto
  GET /trends          → análise de tendência multi-day
                         ?days=7 → tamanho da janela (2 a 30)

Variáveis de ambiente esperadas:
  - FX_BUCKET_NAME   → bucket S3 onde os relatórios vivem
  - FX_BASE_CURRENCY → moeda base das consultas (padrão: USD)
"""

import json
import logging
import os

from query import find_latest_report, filter_currency, extract_alerts, LOOKBACK_DAYS
from trends import analyze_trends, DEFAULT_WINDOW, IS_AWS

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Moeda base das consultas — mesma variável usada pela Lambda agendada
BASE_CURRENCY = os.environ.get("FX_BASE_CURRENCY", "USD")

# Limites aceitos no parâmetro ?days do endpoint /trends
MIN_DAYS = 2
MAX_DAYS = 30


# ── Resposta HTTP ────────────────────────────────────────────────

def _response(status_code: int, body: dict) -> dict:
    """
    Monta a resposta no formato esperado pelo API Gateway.

    O header Content-Type é importante aqui: sem ele o cliente recebe o
    corpo como texto puro e o navegador mostra o JSON cru, sem formatar.

    Parâmetros:
      status_code → código HTTP (200, 400, 404, 500)
      body        → dicionário com o conteúdo da resposta

    Retorna:
      Dicionário com statusCode, headers e body serializado em JSON.
    """
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json; charset=utf-8"},
        "body":       json.dumps(body, ensure_ascii=False),
    }


# ── Leitura do evento do API Gateway ─────────────────────────────

def extract_path(event: dict) -> str:
    """
    Descobre qual caminho foi chamado, independente do tipo de API Gateway.

    O API Gateway tem dois formatos de evento e eles usam campos diferentes:
      HTTP API (v2)  → event["rawPath"]
      REST API (v1)  → event["path"]

    Além disso, o nome do stage entra no caminho quando o stage tem nome
    próprio (ex: "/v1/alerts" em vez de "/alerts"). Essa é uma armadilha
    clássica: o roteamento funciona no teste e quebra no deploy. Por isso
    o stage é removido aqui antes de rotear.

    Parâmetros:
      event → payload bruto entregue pelo API Gateway

    Retorna:
      Caminho normalizado, sempre começando com barra e sem barra final.
      Ex: "/reports/latest"
    """
    caminho = event.get("rawPath") or event.get("path") or "/"

    # Remove o nome do stage do começo do caminho, quando houver.
    # A comparação precisa ser do segmento inteiro: testar só o prefixo faria
    # o stage "v1" cortar um caminho "/v1x/alerts" pela metade.
    stage = event.get("requestContext", {}).get("stage", "")
    if stage and stage != "$default":
        if caminho == f"/{stage}" or caminho.startswith(f"/{stage}/"):
            caminho = caminho[len(stage) + 1:]

    # Normaliza: garante a barra inicial e remove a barra final
    if not caminho.startswith("/"):
        caminho = "/" + caminho
    if len(caminho) > 1 and caminho.endswith("/"):
        caminho = caminho.rstrip("/")

    return caminho


def extract_params(event: dict) -> dict:
    """
    Extrai os parâmetros de query string do evento.

    O API Gateway envia None (não um dicionário vazio) quando a URL não
    tem query string. Sem esse tratamento, o .get() do chamador estoura
    com AttributeError em toda requisição sem parâmetro.

    Parâmetros:
      event → payload bruto entregue pelo API Gateway

    Retorna:
      Dicionário de parâmetros, vazio quando não há nenhum.
    """
    return event.get("queryStringParameters") or {}


# ── Handlers de cada rota ────────────────────────────────────────

def handle_health(params: dict) -> tuple:
    """
    GET /health — confirma que a API está viva e mostra o ambiente detectado.

    Útil para checar o deploy sem gastar leitura do S3.

    Retorna:
      Tupla (status_code, corpo_da_resposta).
    """
    return 200, {
        "status":        "ok",
        "environment":   "aws" if IS_AWS else "local",
        "base_currency": BASE_CURRENCY,
        "endpoints":     sorted(ROUTES.keys()),
    }


def _erro_sem_relatorio() -> tuple:
    """
    Resposta 404 padrão para quando o bucket não tem nenhum relatório.

    Acontece antes da primeira execução da Lambda agendada, ou se o
    bucket foi esvaziado. Os endpoints /reports/latest e /alerts
    dependem do mesmo relatório, então respondem igual nesse caso.

    Retorna:
      Tupla (404, corpo_da_resposta).
    """
    return 404, {
        "error": (
            f"Nenhum relatório encontrado para base={BASE_CURRENCY} "
            f"nos últimos {LOOKBACK_DAYS} dias."
        )
    }


def handle_latest_report(params: dict) -> tuple:
    """
    GET /reports/latest — devolve o relatório mais recente do S3.

    Com ?currency=BRL, devolve só o recorte daquela moeda.

    Retorna:
      Tupla (status_code, corpo_da_resposta).
      404 quando não há relatório no bucket, ou quando a moeda pedida
      não aparece no relatório mais recente.
    """
    report = find_latest_report(BASE_CURRENCY)

    if report is None:
        return _erro_sem_relatorio()

    currency = params.get("currency")
    if currency is None:
        return 200, report

    # Valida o formato antes de procurar: código de moeda tem 3 letras (ISO 4217)
    if len(currency) != 3 or not currency.isalpha():
        return 400, {
            "error": (
                f"Parâmetro currency inválido: {currency}. "
                f"Use um código de 3 letras, ex: BRL."
            )
        }

    recorte = filter_currency(report, currency)
    if recorte is None:
        return 404, {
            "error": f"Moeda {currency.upper()} não está no relatório mais recente.",
            "currencies_available": report.get("currencies_analyzed", []),
        }

    return 200, recorte


def handle_alerts(params: dict) -> tuple:
    """
    GET /alerts — alertas do relatório mais recente, com variação e risco.

    Retorna:
      Tupla (status_code, corpo_da_resposta).
      Lista vazia com 200 quando o relatório existe e nenhuma moeda alertou —
      "nenhum alerta hoje" é uma resposta de sucesso, não um erro.
    """
    report = find_latest_report(BASE_CURRENCY)

    if report is None:
        return _erro_sem_relatorio()

    return 200, extract_alerts(report)


def handle_trends(params: dict) -> tuple:
    """
    GET /trends — análise de tendência multi-day, reaproveitando o trends.py.

    A janela é controlada por ?days (padrão 7). O limite máximo existe para
    proteger a Lambda: cada dia da janela é uma chamada list_objects_v2 no S3,
    então uma janela de 365 dias estouraria o timeout.

    Retorna:
      Tupla (status_code, corpo_da_resposta).
      400 quando ?days não é um número inteiro dentro da faixa aceita.
    """
    days = params.get("days", str(DEFAULT_WINDOW))

    if not str(days).isdigit():
        return 400, {
            "error": f"Parâmetro days inválido: {days}. Use um número inteiro."
        }

    days = int(days)
    if days < MIN_DAYS or days > MAX_DAYS:
        return 400, {
            "error": (
                f"Parâmetro days fora da faixa: {days}. "
                f"Use um valor entre {MIN_DAYS} e {MAX_DAYS}."
            )
        }

    resultado = analyze_trends(days=days, base_currency=BASE_CURRENCY)

    if resultado.get("reports_found", 0) == 0:
        return 404, {
            "error": f"Nenhum relatório histórico encontrado na janela de {days} dias.",
            "window_days": days,
        }

    return 200, resultado


# ── Tabela de rotas ──────────────────────────────────────────────
# Caminho → função que o atende. Cada função recebe os parâmetros de
# query string e devolve (status, corpo). Adicionar um endpoint novo é
# escrever a função e registrá-la aqui.

ROUTES = {
    "/health":         handle_health,
    "/reports/latest": handle_latest_report,
    "/alerts":         handle_alerts,
    "/trends":         handle_trends,
}


# ── Entry point ──────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Ponto de entrada da Lambda de consulta — chamado pelo API Gateway.

    Parâmetros:
      event   → requisição HTTP traduzida pelo API Gateway
      context → metadados da execução (tempo restante, nome da função, etc.)

    Retorna:
      Dicionário no formato API Gateway com statusCode, headers e body.
    """
    caminho = extract_path(event)
    params  = extract_params(event)

    logger.info(f"Consulta recebida: {caminho} params={params}")

    handler = ROUTES.get(caminho)
    if handler is None:
        return _response(404, {
            "error":               f"Rota não encontrada: {caminho}",
            "endpoints_available": sorted(ROUTES.keys()),
        })

    # Qualquer erro inesperado na consulta vira 500 com log — a API nunca
    # devolve stack trace para quem chamou, mas o CloudWatch registra tudo.
    try:
        status, body = handler(params)
    except Exception as e:
        logger.exception(f"Erro inesperado ao atender {caminho}: {e}")
        return _response(500, {"error": "Erro interno ao processar a consulta."})

    return _response(status, body)
