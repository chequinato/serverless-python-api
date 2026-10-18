"""
query.py — Consulta dos relatórios já persistidos

Responsabilidade:
  Localizar e carregar relatórios de câmbio que a Lambda agendada já
  gerou e salvou. Este módulo é **somente leitura**: nunca chama API
  externa, nunca grava nada, nunca gasta cota das APIs de câmbio.

Por que existe:
  A Lambda agendada (lambda_function.py) roda uma vez por dia e gasta
  2 requisições das APIs externas. Se cada consulta de usuário disparasse
  esse fluxo, o plano gratuito (1.500 req/mês) acabaria em dias.
  A API de consulta lê o que já está no S3 — custo zero de cota.

Funções públicas:
  find_latest_report(base_currency) → relatório mais recente disponível
  filter_currency(report, currency) → recorte de uma moeda do relatório
  extract_alerts(report)            → alertas do relatório + contexto

Reuso:
  As funções de leitura de S3/disco já existem no trends.py. Em vez de
  duplicar, este módulo as reaproveita — mesma estrutura Hive-style,
  mesma detecção de ambiente.

Variáveis de ambiente esperadas:
  - FX_BUCKET_NAME    → bucket S3 onde os relatórios vivem
  - AWS_EXECUTION_ENV → detecção de ambiente (AWS vs local)
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

from processor import ALERT_THRESHOLD
from trends import (
    IS_AWS,
    _list_s3_reports,
    _load_s3_report,
    _list_local_reports,
    _load_local_report,
)

logger = logging.getLogger(__name__)

# ── Configuração ─────────────────────────────────────────────────

# Até quantos dias para trás procurar o relatório mais recente.
# Protege contra varredura infinita quando o bucket está vazio.
LOOKBACK_DAYS = 30


# ── Localização do relatório mais recente ────────────────────────

def find_latest_report(
    base_currency: str = "USD",
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[dict]:
    """
    Busca o relatório mais recente disponível para uma moeda base.

    Varre a janela de dias para trás, junta todas as keys encontradas e
    pega a última em ordem alfabética. O particionamento Hive-style com
    zeros à esquerda (year=2024/month=03/day=09) faz a ordem alfabética
    coincidir com a ordem cronológica — por isso basta ordenar.

    Diferente do load_history() do trends.py, esta função inclui o dia de
    hoje: o relatório de hoje já pode existir se a Lambda agendada rodou.

    Parâmetros:
      base_currency → moeda base dos relatórios (ex: "USD")
      lookback_days → até quantos dias para trás procurar (padrão: 30)

    Retorna:
      Dicionário com o relatório, ou None se nenhum foi encontrado.
    """
    end   = date.today()
    start = end - timedelta(days=lookback_days - 1)

    if IS_AWS:
        keys = _list_s3_reports(base_currency, start, end)
        if not keys:
            logger.warning(
                f"Nenhum relatório encontrado no S3 para base={base_currency} "
                f"nos últimos {lookback_days} dias."
            )
            return None
        return _load_s3_report(keys[-1])

    paths = _list_local_reports(start, end)
    if not paths:
        logger.warning(
            f"Nenhum relatório local encontrado nos últimos {lookback_days} dias."
        )
        return None
    return _load_local_report(paths[-1])


# ── Recortes do relatório (Python puro) ──────────────────────────

def filter_currency(report: dict, currency: str) -> Optional[dict]:
    """
    Extrai os dados de uma única moeda do relatório.

    Quando o relatório tem o bloco analytics, o nível de risco daquela
    moeda é anexado ao resultado. Sem analytics, o campo simplesmente
    não aparece — o endpoint continua respondendo.

    Parâmetros:
      report   → dicionário do relatório completo
      currency → código da moeda (ex: "BRL", maiúsculas ou minúsculas)

    Retorna:
      Dicionário com os dados da moeda, ou None se ela não está no relatório.
    """
    code = currency.upper()

    for variation in report.get("variations", []):
        if variation.get("currency") != code:
            continue

        resultado = {
            "base_currency": report.get("base_currency"),
            "generated_at":  report.get("generated_at"),
            "currency":      code,
            "rate_now":      variation.get("rate_now"),
            "rate_prev":     variation.get("rate_prev"),
            "variation_pct": variation.get("variation_pct"),
            "direction":     variation.get("direction"),
            "alert":         variation.get("alert"),
        }

        # Enriquece com o risco calculado pelo analytics, se disponível
        risco = report.get("analytics", {}).get("risk_classification", {}).get(code)
        if risco:
            resultado["risk_level"] = risco.get("level")

        return resultado

    return None


def extract_alerts(report: dict) -> dict:
    """
    Monta a resposta do endpoint de alertas a partir do relatório.

    O relatório guarda os alertas como uma lista de códigos de moeda
    (ex: ["BRL", "ARS"]). Aqui cada código é cruzado com a variação
    correspondente para devolver o alerta com contexto — quem consulta
    a API quer saber quanto a moeda variou, não só que ela alertou.

    Parâmetros:
      report → dicionário do relatório completo

    Retorna:
      Dicionário com contagem, lista de alertas detalhados e sentimento.
    """
    codigos    = report.get("alerts", [])
    variations = {v.get("currency"): v for v in report.get("variations", [])}
    riscos     = report.get("analytics", {}).get("risk_classification", {})

    detalhados = []
    for code in codigos:
        variation = variations.get(code)
        if variation is None:
            # Alerta sem variação correspondente: relatório inconsistente.
            # Devolve o código mesmo assim — a informação principal é que alertou.
            detalhados.append({"currency": code})
            continue

        alerta = {
            "currency":      code,
            "variation_pct": variation.get("variation_pct"),
            "direction":     variation.get("direction"),
            "rate_now":      variation.get("rate_now"),
        }
        if code in riscos:
            alerta["risk_level"] = riscos[code].get("level")

        detalhados.append(alerta)

    resposta = {
        "base_currency":  report.get("base_currency"),
        "generated_at":   report.get("generated_at"),
        "threshold_pct":  ALERT_THRESHOLD,
        "alerts_count":   len(detalhados),
        "alerts":         detalhados,
    }

    # Sentimento vem do analytics — opcional, só aparece se foi calculado
    sentimento = report.get("analytics", {}).get("market_sentiment", {}).get("sentiment")
    if sentimento:
        resposta["market_sentiment"] = sentimento

    return resposta
