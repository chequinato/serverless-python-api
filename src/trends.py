"""
trends.py — Análise de tendência multi-day

Responsabilidade:
  Buscar os relatórios dos últimos N dias no S3 (ou localmente),
  montar a série temporal de cada moeda e calcular:
    - Média móvel (SMA) configurável
    - Direção sustentada (moeda subindo/caindo N dias seguidos)
    - Volatilidade acumulada (desvio padrão da janela)
    - Variação acumulada no período

Funções públicas:
  load_history(days, base_currency)  → carrega relatórios anteriores
  build_series(reports)              → monta série temporal por moeda
  calculate_trend(series)            → calcula tendências de uma moeda
  analyze_trends(days, base_currency) → função principal, retorna tudo

Este módulo acessa o S3 (ou disco local) para leitura de relatórios passados.
Toda a lógica de cálculo é Python puro — testável com dados sintéticos.

Variáveis de ambiente:
  - FX_BUCKET_NAME     → bucket S3 onde os relatórios vivem
  - AWS_EXECUTION_ENV  → detecção de ambiente (AWS vs local)
"""

import json
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Configuração ─────────────────────────────────────────────────

BUCKET_NAME = os.environ.get("FX_BUCKET_NAME", "")
IS_AWS = bool(os.environ.get("AWS_EXECUTION_ENV"))

# Janela padrão de dias para análise de tendência
DEFAULT_WINDOW = 7

# Período da média móvel (em dias)
DEFAULT_SMA_PERIOD = 3


# ── Carga de histórico ───────────────────────────────────────────

def _list_s3_reports(base_currency: str, start_date: date, end_date: date) -> List[str]:
    """
    Lista as keys dos relatórios no S3 dentro de um intervalo de datas.

    Varre os prefixos Hive-style dia a dia e coleta os objetos que
    casam com a moeda base.

    Parâmetros:
      base_currency → moeda base dos relatórios (ex: "USD")
      start_date    → data inicial (inclusiva)
      end_date      → data final (inclusiva)

    Retorna:
      Lista de S3 keys ordenadas por data crescente.
    """
    import boto3
    s3 = boto3.client("s3")
    keys = []

    current = start_date
    while current <= end_date:
        prefix = (
            f"fx-reports/year={current.year}/"
            f"month={current.month:02d}/"
            f"day={current.day:02d}/"
        )

        try:
            response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
            for obj in response.get("Contents", []):
                key = obj["Key"]
                # Filtra pela moeda base no nome do arquivo
                if f"report_{base_currency}_" in key and key.endswith(".json"):
                    keys.append(key)
        except Exception as e:
            logger.warning(f"Erro ao listar S3 prefix={prefix}: {e}")

        current += timedelta(days=1)

    return sorted(keys)


def _load_s3_report(key: str) -> Optional[dict]:
    """
    Carrega e parseia um relatório JSON do S3.

    Parâmetros:
      key → S3 key do objeto

    Retorna:
      Dicionário com o conteúdo do relatório, ou None em caso de erro.
    """
    import boto3
    s3 = boto3.client("s3")

    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        body = response["Body"].read().decode("utf-8")
        return json.loads(body)
    except Exception as e:
        logger.warning(f"Erro ao carregar relatório {key}: {e}")
        return None


def _list_local_reports(start_date: date, end_date: date) -> List[str]:
    """
    Lista relatórios locais na pasta output/ dentro de um intervalo de datas.

    Parâmetros:
      start_date → data inicial (inclusiva)
      end_date   → data final (inclusiva)

    Retorna:
      Lista de caminhos de arquivo ordenados por nome (data crescente).
    """
    output_dir = "output"
    if not os.path.isdir(output_dir):
        return []

    files = []
    for filename in os.listdir(output_dir):
        if not filename.startswith("report_") or not filename.endswith(".json"):
            continue

        # Extrai a data do nome: report_YYYYMMDDHHMMSS.json
        try:
            date_part = filename.replace("report_", "").replace(".json", "")
            file_date = datetime.strptime(date_part[:8], "%Y%m%d").date()

            if start_date <= file_date <= end_date:
                files.append(os.path.join(output_dir, filename))
        except (ValueError, IndexError):
            continue

    return sorted(files)


def _load_local_report(path: str) -> Optional[dict]:
    """
    Carrega e parseia um relatório JSON local.

    Parâmetros:
      path → caminho do arquivo

    Retorna:
      Dicionário com o conteúdo do relatório, ou None em caso de erro.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception as e:
        logger.warning(f"Erro ao carregar relatório local {path}: {e}")
        return None


def load_history(
    days: int = DEFAULT_WINDOW,
    base_currency: str = "USD",
) -> List[dict]:
    """
    Carrega os relatórios dos últimos N dias.

    Decide automaticamente entre S3 (produção) e disco local (dev).

    Parâmetros:
      days          → número de dias para trás (padrão: 7)
      base_currency → moeda base dos relatórios (padrão: "USD")

    Retorna:
      Lista de dicionários (relatórios parseados), ordenada por data crescente.
      Dias sem relatório são simplesmente ausentes — sem erro.
    """
    end = date.today() - timedelta(days=1)  # Exclui hoje (pode ainda não existir)
    start = end - timedelta(days=days - 1)

    if IS_AWS:
        keys = _list_s3_reports(base_currency, start, end)
        reports = [_load_s3_report(k) for k in keys]
    else:
        paths = _list_local_reports(start, end)
        reports = [_load_local_report(p) for p in paths]

    # Filtra None (relatórios que falharam ao carregar)
    return [r for r in reports if r is not None]


# ── Série temporal ───────────────────────────────────────────────

def build_series(reports: List[dict]) -> Dict[str, List[dict]]:
    """
    Monta uma série temporal por moeda a partir dos relatórios carregados.

    Extrai a variação percentual de cada moeda de cada relatório e
    organiza como uma lista ordenada por data.

    Parâmetros:
      reports → lista de relatórios (dicionários) ordenada por data

    Retorna:
      Dicionário {moeda: [{"date": str, "rate": float, "variation_pct": float}, ...]}
      Cada moeda tem uma entrada por relatório onde apareceu.
    """
    series: Dict[str, List[dict]] = {}

    for report in reports:
        report_date = report.get("generated_at", "")
        variations = report.get("variations", [])

        for v in variations:
            currency = v.get("currency")
            if currency is None:
                continue

            if currency not in series:
                series[currency] = []

            series[currency].append({
                "date":          report_date,
                "rate":          v.get("rate_now", 0.0),
                "variation_pct": v.get("variation_pct", 0.0),
            })

    return series


# ── Cálculos de tendência ────────────────────────────────────────

def _sma(values: List[float], period: int) -> List[Optional[float]]:
    """
    Calcula a Média Móvel Simples (SMA) de uma série.

    Os primeiros (period - 1) valores não têm SMA completa e são None.

    Parâmetros:
      values → lista de valores numéricos
      period → número de períodos da média

    Retorna:
      Lista do mesmo tamanho com a SMA ou None nos pontos iniciais.
    """
    result: List[Optional[float]] = []

    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            window = values[i - period + 1 : i + 1]
            result.append(round(sum(window) / period, 6))

    return result


def _streak(variations_pct: List[float]) -> Tuple[int, str]:
    """
    Calcula quantos dias seguidos a moeda manteve a mesma direção,
    contando do dia mais recente para trás.

    Parâmetros:
      variations_pct → lista de variações % por dia (ordem cronológica)

    Retorna:
      (dias, direção) — ex: (5, "up") significa 5 dias subindo seguidos.
      Direção pode ser "up", "down" ou "stable".
    """
    if not variations_pct:
        return 0, "stable"

    # Determina a direção do último dia
    last = variations_pct[-1]
    if last > 0.01:
        target = "up"
    elif last < -0.01:
        target = "down"
    else:
        target = "stable"

    count = 0
    for pct in reversed(variations_pct):
        if target == "up" and pct > 0.01:
            count += 1
        elif target == "down" and pct < -0.01:
            count += 1
        elif target == "stable" and -0.01 <= pct <= 0.01:
            count += 1
        else:
            break

    return count, target


def _accumulated_change(rates: List[float]) -> float:
    """
    Calcula a variação percentual acumulada entre o primeiro e o último valor.

    Parâmetros:
      rates → lista de taxas em ordem cronológica

    Retorna:
      Variação % acumulada. Zero se a lista tiver menos de 2 elementos
      ou se o valor inicial for zero.
    """
    if len(rates) < 2 or rates[0] == 0:
        return 0.0

    return round(((rates[-1] - rates[0]) / rates[0]) * 100, 4)


def _volatility(variations_pct: List[float]) -> float:
    """
    Calcula a volatilidade (desvio padrão) das variações diárias.

    Parâmetros:
      variations_pct → lista de variações % por dia

    Retorna:
      Desvio padrão populacional. Zero se a lista estiver vazia.
    """
    if not variations_pct:
        return 0.0

    n = len(variations_pct)
    mean = sum(variations_pct) / n
    variance = sum((p - mean) ** 2 for p in variations_pct) / n

    return round(math.sqrt(variance), 4)


def calculate_trend(
    currency: str,
    data_points: List[dict],
    sma_period: int = DEFAULT_SMA_PERIOD,
) -> dict:
    """
    Calcula as métricas de tendência para uma moeda.

    Parâmetros:
      currency    → código da moeda (ex: "BRL")
      data_points → lista de {"date", "rate", "variation_pct"} em ordem cronológica
      sma_period  → período da média móvel (padrão: 3)

    Retorna:
      Dicionário com:
        - currency: código da moeda
        - data_points: número de dias com dados
        - streak_days: quantos dias na mesma direção
        - streak_direction: "up", "down" ou "stable"
        - accumulated_change_pct: variação % total no período
        - volatility: desvio padrão das variações diárias
        - sma: último valor da média móvel (ou None)
        - sma_period: período usado
        - trend_signal: sinal consolidado ("RISING", "FALLING", "SIDEWAYS")
        - daily_variations: lista de variações % por dia
    """
    rates = [dp["rate"] for dp in data_points]
    variations = [dp["variation_pct"] for dp in data_points]

    streak_days, streak_dir = _streak(variations)
    accumulated = _accumulated_change(rates)
    vol = _volatility(variations)
    sma_values = _sma(rates, sma_period)

    # Último valor da SMA (pode ser None se não houver dados suficientes)
    last_sma = sma_values[-1] if sma_values else None

    # Sinal consolidado — combina streak e acumulado
    if streak_days >= 3 and streak_dir == "up" and accumulated > 0.5:
        signal = "RISING"
    elif streak_days >= 3 and streak_dir == "down" and accumulated < -0.5:
        signal = "FALLING"
    else:
        signal = "SIDEWAYS"

    return {
        "currency":               currency,
        "data_points":            len(data_points),
        "streak_days":            streak_days,
        "streak_direction":       streak_dir,
        "accumulated_change_pct": accumulated,
        "volatility":             vol,
        "sma":                    last_sma,
        "sma_period":             sma_period,
        "trend_signal":           signal,
        "daily_variations":       variations,
    }


# ── Função principal ─────────────────────────────────────────────

def analyze_trends(
    days: int = DEFAULT_WINDOW,
    base_currency: str = "USD",
    sma_period: int = DEFAULT_SMA_PERIOD,
    history: Optional[List[dict]] = None,
) -> dict:
    """
    Função principal — analisa tendências de todas as moedas.

    Carrega o histórico (ou usa o fornecido), monta as séries temporais
    e calcula tendências para cada moeda encontrada.

    Parâmetros:
      days          → janela de dias para análise (padrão: 7)
      base_currency → moeda base (padrão: "USD")
      sma_period    → período da média móvel (padrão: 3)
      history       → relatórios pré-carregados (pula a leitura do S3/disco)

    Retorna:
      Dicionário com:
        - window_days: tamanho da janela analisada
        - reports_found: número de relatórios carregados
        - base_currency: moeda base
        - trends: {moeda: resultado de calculate_trend}
        - highlights: lista de moedas com streaks >= 3 dias
    """
    if history is None:
        history = load_history(days, base_currency)

    if not history:
        logger.warning("Nenhum relatório histórico encontrado para análise de tendência.")
        return {
            "window_days":    days,
            "reports_found":  0,
            "base_currency":  base_currency,
            "trends":         {},
            "highlights":     [],
        }

    series = build_series(history)
    trends = {}

    for currency, data_points in series.items():
        trends[currency] = calculate_trend(currency, data_points, sma_period)

    # Destaques: moedas com streak >= 3 dias ou variação acumulada significativa
    highlights = []
    for currency, trend in trends.items():
        if trend["streak_days"] >= 3:
            highlights.append({
                "currency":  currency,
                "reason":    f"{trend['streak_direction']} por {trend['streak_days']} dias seguidos",
                "signal":    trend["trend_signal"],
                "accumulated_pct": trend["accumulated_change_pct"],
            })
        elif abs(trend["accumulated_change_pct"]) >= 3.0:
            highlights.append({
                "currency":  currency,
                "reason":    f"variação acumulada de {trend['accumulated_change_pct']:+.2f}% em {trend['data_points']} dias",
                "signal":    trend["trend_signal"],
                "accumulated_pct": trend["accumulated_change_pct"],
            })

    # Ordena highlights por variação acumulada absoluta
    highlights.sort(key=lambda h: abs(h["accumulated_pct"]), reverse=True)

    logger.info(
        f"Tendências calculadas: {len(trends)} moedas, "
        f"{len(highlights)} destaques, "
        f"{len(history)} relatórios na janela de {days} dias"
    )

    return {
        "window_days":    days,
        "reports_found":  len(history),
        "base_currency":  base_currency,
        "trends":         trends,
        "highlights":     highlights,
    }
