"""
analytics.py — Análise avançada dos dados de câmbio

Responsabilidade:
  Receber o FXReport já processado e enriquecê-lo com métricas
  analíticas: classificação de risco, detecção de anomalias,
  matriz de cross-rates e sentimento de mercado.

Funções públicas:
  analyze(report, live_rates)  → função principal, retorna dicionário de analytics

Funções internas:
  classify_risk(variation_pct)          → classifica risco de uma moeda
  calculate_statistics(variations)      → média, mediana, desvio padrão
  build_cross_rate_matrix(rates, currencies) → taxas cruzadas entre moedas
  detect_anomalies(variations)          → identifica variações fora do padrão
  assess_market_sentiment(variations)   → sentimento geral do mercado

Este módulo não faz chamadas HTTP nem acessa a AWS — é Python puro.
Segue o mesmo princípio do processor.py: recebe dados, calcula, devolve dados.
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

from api_client import ExchangeRates
from processor import CurrencyVariation, FXReport

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────────

# Limites para classificação de risco (variação % absoluta)
RISK_THRESHOLDS = {
    "LOW":      0.5,   # variação < 0.5%
    "MEDIUM":   1.5,   # 0.5% <= variação < 1.5%
    "HIGH":     3.0,   # 1.5% <= variação < 3.0%
    "CRITICAL": 3.0,   # variação >= 3.0%
}

# Fator de desvio para detecção de anomalias (z-score)
ANOMALY_Z_THRESHOLD = 1.5

# Sentimento requer pelo menos esta proporção para ser considerado direcional
SENTIMENT_MAJORITY = 0.6


# ── Classificação de risco ────────────────────────────────────────

def classify_risk(variation_pct: float) -> str:
    """
    Classifica o nível de risco de uma moeda com base na variação percentual.

    Faixas:
      |variation| < 0.5%  → LOW      (variação dentro do normal diário)
      |variation| < 1.5%  → MEDIUM   (atenção, mas ainda esperado)
      |variation| < 3.0%  → HIGH     (fora do normal, merece investigação)
      |variation| >= 3.0% → CRITICAL (evento significativo de mercado)

    Parâmetros:
      variation_pct → variação percentual (positiva ou negativa)

    Retorna:
      String com o nível de risco: "LOW", "MEDIUM", "HIGH" ou "CRITICAL"
    """
    abs_pct = abs(variation_pct)

    if abs_pct < RISK_THRESHOLDS["LOW"]:
        return "LOW"
    elif abs_pct < RISK_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    elif abs_pct < RISK_THRESHOLDS["HIGH"]:
        return "HIGH"
    else:
        return "CRITICAL"


# ── Estatísticas ──────────────────────────────────────────────────

def calculate_statistics(variations: List[CurrencyVariation]) -> dict:
    """
    Calcula estatísticas descritivas das variações percentuais.

    Métricas:
      - mean:       média aritmética das variações
      - median:     valor central das variações ordenadas
      - std_dev:    desvio padrão (dispersão das variações)
      - range:      diferença entre maior e menor variação
      - abs_mean:   média das variações em valor absoluto

    Parâmetros:
      variations → lista de CurrencyVariation do relatório

    Retorna:
      Dicionário com as estatísticas calculadas.
      Retorna zeros se a lista estiver vazia.
    """
    if not variations:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std_dev": 0.0,
            "range": 0.0,
            "abs_mean": 0.0,
            "count": 0,
        }

    pcts = [v.variation_pct for v in variations]
    n = len(pcts)

    # Média
    mean = sum(pcts) / n

    # Mediana
    sorted_pcts = sorted(pcts)
    if n % 2 == 1:
        median = sorted_pcts[n // 2]
    else:
        median = (sorted_pcts[n // 2 - 1] + sorted_pcts[n // 2]) / 2

    # Desvio padrão (populacional — temos todas as moedas analisadas)
    variance = sum((p - mean) ** 2 for p in pcts) / n
    std_dev = math.sqrt(variance)

    # Range
    pct_range = max(pcts) - min(pcts)

    # Média absoluta
    abs_mean = sum(abs(p) for p in pcts) / n

    return {
        "mean":     round(mean, 4),
        "median":   round(median, 4),
        "std_dev":  round(std_dev, 4),
        "range":    round(pct_range, 4),
        "abs_mean": round(abs_mean, 4),
        "count":    n,
    }


# ── Matriz de cross-rates ────────────────────────────────────────

def build_cross_rate_matrix(
    rates: ExchangeRates,
    currencies: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """
    Constrói uma matriz de taxas cruzadas entre as moedas monitoradas.

    Dado que temos as taxas de todas as moedas em relação a uma base,
    podemos calcular a taxa entre quaisquer duas moedas:
      taxa(A→B) = taxa_B / taxa_A

    Exemplo: se 1 USD = 0.92 EUR e 1 USD = 4.97 BRL,
      então 1 EUR = 4.97 / 0.92 = 5.4022 BRL

    Parâmetros:
      rates      → ExchangeRates com as taxas atuais
      currencies → lista de moedas para a matriz (padrão: moedas do rates)

    Retorna:
      Dicionário aninhado {moeda_origem: {moeda_destino: taxa}}
      A diagonal (mesma moeda) é sempre 1.0.
    """
    if currencies is None:
        currencies = list(rates.rates.keys())

    # Filtra só moedas que existem no rates
    available = [c for c in currencies if rates.get_rate(c) is not None]

    matrix = {}
    for from_currency in available:
        row = {}
        from_rate = rates.get_rate(from_currency)

        for to_currency in available:
            if from_currency == to_currency:
                row[to_currency] = 1.0
            else:
                to_rate = rates.get_rate(to_currency)
                if from_rate and from_rate != 0:
                    row[to_currency] = round(to_rate / from_rate, 6)
                else:
                    row[to_currency] = 0.0

        matrix[from_currency] = row

    return matrix


# ── Detecção de anomalias ────────────────────────────────────────

def detect_anomalies(
    variations: List[CurrencyVariation],
    z_threshold: float = ANOMALY_Z_THRESHOLD,
) -> List[dict]:
    """
    Identifica moedas com variações anormais usando z-score.

    O z-score mede quantos desvios padrão um valor está da média.
    Moedas com |z-score| acima do limiar são consideradas anômalas.

    Fórmula: z = (valor - média) / desvio_padrão

    Parâmetros:
      variations  → lista de CurrencyVariation
      z_threshold → número de desvios padrão para considerar anomalia

    Retorna:
      Lista de dicionários com moeda, z-score e variação das anomalias,
      ordenada por z-score absoluto decrescente.
      Lista vazia se não houver variações ou desvio padrão for zero.
    """
    if len(variations) < 2:
        return []

    pcts = [v.variation_pct for v in variations]
    mean = sum(pcts) / len(pcts)
    variance = sum((p - mean) ** 2 for p in pcts) / len(pcts)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return []

    anomalies = []
    for v in variations:
        z_score = (v.variation_pct - mean) / std_dev
        if abs(z_score) >= z_threshold:
            anomalies.append({
                "currency":      v.currency,
                "variation_pct": v.variation_pct,
                "z_score":       round(z_score, 4),
                "direction":     v.direction,
                "severity":      "EXTREME" if abs(z_score) >= 2.5 else "MODERATE",
            })

    return sorted(anomalies, key=lambda a: abs(a["z_score"]), reverse=True)


# ── Sentimento de mercado ────────────────────────────────────────

def assess_market_sentiment(variations: List[CurrencyVariation]) -> dict:
    """
    Avalia o sentimento geral do mercado com base nas variações.

    Lógica:
      - Se >= 60% das moedas sobem → BULLISH (mercado otimista)
      - Se >= 60% das moedas caem  → BEARISH (mercado pessimista)
      - Caso contrário             → MIXED   (sem direção clara)

    Também calcula:
      - confidence: proporção da direção dominante (0.0 a 1.0)
      - avg_magnitude: magnitude média das variações (volatilidade geral)
      - volatility_level: classificação da volatilidade geral

    Parâmetros:
      variations → lista de CurrencyVariation

    Retorna:
      Dicionário com sentimento, confiança e métricas de volatilidade.
    """
    if not variations:
        return {
            "sentiment":       "NEUTRAL",
            "confidence":      0.0,
            "up_count":        0,
            "down_count":      0,
            "stable_count":    0,
            "avg_magnitude":   0.0,
            "volatility_level": "CALM",
        }

    total = len(variations)
    up_count    = sum(1 for v in variations if v.direction == "up")
    down_count  = sum(1 for v in variations if v.direction == "down")
    stable_count = sum(1 for v in variations if v.direction == "stable")

    # Sentimento baseado em maioria
    up_ratio   = up_count / total
    down_ratio = down_count / total

    if up_ratio >= SENTIMENT_MAJORITY:
        sentiment = "BULLISH"
        confidence = round(up_ratio, 4)
    elif down_ratio >= SENTIMENT_MAJORITY:
        sentiment = "BEARISH"
        confidence = round(down_ratio, 4)
    else:
        sentiment = "MIXED"
        confidence = round(max(up_ratio, down_ratio), 4)

    # Volatilidade geral — média das variações absolutas
    avg_magnitude = sum(abs(v.variation_pct) for v in variations) / total
    avg_magnitude = round(avg_magnitude, 4)

    # Classificação de volatilidade
    if avg_magnitude < 0.3:
        volatility_level = "CALM"
    elif avg_magnitude < 1.0:
        volatility_level = "NORMAL"
    elif avg_magnitude < 2.0:
        volatility_level = "ELEVATED"
    else:
        volatility_level = "HIGH"

    return {
        "sentiment":        sentiment,
        "confidence":       confidence,
        "up_count":         up_count,
        "down_count":       down_count,
        "stable_count":     stable_count,
        "avg_magnitude":    avg_magnitude,
        "volatility_level": volatility_level,
    }


# ── Função principal ──────────────────────────────────────────────

def analyze(report: FXReport, live_rates: ExchangeRates) -> dict:
    """
    Função principal do módulo — gera o relatório analítico completo.

    Recebe o FXReport já processado pelo processor.py e as taxas live,
    e produz um dicionário com todas as análises avançadas.

    Parâmetros:
      report     → FXReport gerado pelo processor.process()
      live_rates → ExchangeRates com taxas atuais (para cross-rate matrix)

    Retorna:
      Dicionário com:
        - risk_classification: risco por moeda
        - statistics: estatísticas descritivas
        - cross_rate_matrix: matriz de taxas cruzadas
        - anomalies: variações fora do padrão
        - market_sentiment: sentimento geral do mercado
    """
    variations = report.variations

    # Classificação de risco por moeda
    risk_classification = {
        v.currency: {
            "level":         classify_risk(v.variation_pct),
            "variation_pct": v.variation_pct,
            "direction":     v.direction,
        }
        for v in variations
    }

    # Estatísticas descritivas
    statistics = calculate_statistics(variations)

    # Matriz de cross-rates (só moedas analisadas)
    cross_rate_matrix = build_cross_rate_matrix(
        live_rates, report.currencies_analyzed
    )

    # Detecção de anomalias
    anomalies = detect_anomalies(variations)

    # Sentimento de mercado
    market_sentiment = assess_market_sentiment(variations)

    logger.info(
        f"Analytics completo: {len(risk_classification)} moedas classificadas, "
        f"{len(anomalies)} anomalias detectadas, "
        f"sentimento={market_sentiment['sentiment']}"
    )

    return {
        "risk_classification": risk_classification,
        "statistics":          statistics,
        "cross_rate_matrix":   cross_rate_matrix,
        "anomalies":           anomalies,
        "market_sentiment":    market_sentiment,
    }
