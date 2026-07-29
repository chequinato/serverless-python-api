"""
processor.py — Processamento dos dados de câmbio

Responsabilidade:
  Receber as taxas live e históricas, calcular variações percentuais,
  detectar alertas e montar o relatório final (FXReport).

Funções públicas:
  process(live, historical)  → função principal, retorna FXReport completo

Funções internas:
  calculate_variation(now, prev) → calcula % de variação entre dois valores
  compare_rates(live, historical) → cruza as duas fontes e gera CurrencyVariation
  build_summary(variations)       → gera estatísticas consolidadas

Este módulo não faz chamadas HTTP nem acessa a AWS — é Python puro.
Por isso é o mais fácil de testar unitariamente.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from api_client import ExchangeRates, DEFAULT_CURRENCIES

logger = logging.getLogger(__name__)

# Variação percentual acima deste limiar gera alerta
ALERT_THRESHOLD = 1.5


# ── Estruturas de dados ───────────────────────────────────────────

@dataclass
class CurrencyVariation:
    """Representa a variação de uma moeda entre dois momentos."""
    currency:      str    # código da moeda (ex: "BRL")
    rate_now:      float  # taxa atual — fonte live
    rate_prev:     float  # taxa do dia anterior — fonte histórica
    variation_pct: float  # variação percentual calculada
    direction:     str    # "up", "down" ou "stable"
    alert:         bool   # True se variação superar ALERT_THRESHOLD

    def to_dict(self) -> dict:
        """Serializa para dicionário — usado na conversão para JSON."""
        return {
            "currency":      self.currency,
            "rate_now":      self.rate_now,
            "rate_prev":     self.rate_prev,
            "variation_pct": self.variation_pct,
            "direction":     self.direction,
            "alert":         self.alert,
        }


@dataclass
class FXReport:
    """Relatório completo gerado pela Lambda após o processamento."""
    base_currency:       str
    generated_at:        str            # ISO 8601 UTC
    live_date:           str
    historical_date:     str
    currencies_analyzed: List[str]
    variations:          List[CurrencyVariation] = field(default_factory=list)
    alerts:              List[str]               = field(default_factory=list)
    summary:             Dict                    = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serializa para dicionário — usado antes do upload S3."""
        return {
            "base_currency":       self.base_currency,
            "generated_at":        self.generated_at,
            "live_date":           self.live_date,
            "historical_date":     self.historical_date,
            "currencies_analyzed": self.currencies_analyzed,
            "variations":          [v.to_dict() for v in self.variations],
            "alerts":              self.alerts,
            "summary":             self.summary,
        }


# ── Funções de cálculo ────────────────────────────────────────────

def calculate_variation(rate_now: float, rate_prev: float) -> Tuple[float, str]:
    """
    Calcula a variação percentual entre a taxa atual e a taxa anterior.

    Fórmula: ((rate_now - rate_prev) / rate_prev) * 100

    Parâmetros:
      rate_now  → taxa atual (live)
      rate_prev → taxa do dia anterior (histórico)

    Retorna:
      Tupla (variacao_pct, direcao) onde direção é "up", "down" ou "stable".
    """
    if rate_prev == 0:
        return 0.0, "stable"

    pct = ((rate_now - rate_prev) / rate_prev) * 100
    pct = round(pct, 4)

    if pct > 0.01:
        direction = "up"
    elif pct < -0.01:
        direction = "down"
    else:
        direction = "stable"

    return pct, direction


def compare_rates(
    live:       ExchangeRates,
    historical: ExchangeRates,
    currencies: Optional[List[str]] = None,
) -> List[CurrencyVariation]:
    """
    Cruza as taxas live e históricas e calcula a variação de cada moeda.

    Moedas ausentes em qualquer uma das fontes são ignoradas silenciosamente.
    A lista retornada é ordenada por variação absoluta decrescente.

    Parâmetros:
      live       → taxas em tempo real
      historical → taxas do dia anterior
      currencies → lista de moedas a analisar (padrão: DEFAULT_CURRENCIES)

    Retorna:
      Lista de CurrencyVariation ordenada por maior variação absoluta.
    """
    if currencies is None:
        currencies = DEFAULT_CURRENCIES

    variations = []

    for currency in currencies:
        rate_now  = live.get_rate(currency)
        rate_prev = historical.get_rate(currency)

        # Ignora moedas ausentes em qualquer uma das fontes
        if rate_now is None or rate_prev is None:
            continue

        pct, direction = calculate_variation(rate_now, rate_prev)
        is_alert = abs(pct) >= ALERT_THRESHOLD

        variations.append(CurrencyVariation(
            currency=currency,
            rate_now=rate_now,
            rate_prev=rate_prev,
            variation_pct=pct,
            direction=direction,
            alert=is_alert,
        ))

    return sorted(variations, key=lambda v: abs(v.variation_pct), reverse=True)


def build_summary(variations: List[CurrencyVariation]) -> dict:
    """
    Gera estatísticas consolidadas de todas as variações.

    Parâmetros:
      variations → lista retornada por compare_rates

    Retorna:
      Dicionário com maior alta, maior baixa e contagens por direção.
    """
    maior_alta  = max(variations, key=lambda v: v.variation_pct)
    maior_baixa = min(variations, key=lambda v: v.variation_pct)

    return {
        "maior_alta":    {"currency": maior_alta.currency,  "pct": maior_alta.variation_pct},
        "maior_baixa":   {"currency": maior_baixa.currency, "pct": maior_baixa.variation_pct},
        "total_subindo": len([v for v in variations if v.direction == "up"]),
        "total_caindo":  len([v for v in variations if v.direction == "down"]),
        "total_stable":  len([v for v in variations if v.direction == "stable"]),
    }


def process(live: ExchangeRates, historical: ExchangeRates) -> FXReport:
    """
    Função principal do módulo — orquestra o processamento completo.

    Chama compare_rates e build_summary e monta o FXReport final.
    É a única função chamada externamente pelo lambda_function.py.

    Parâmetros:
      live       → taxas em tempo real (ExchangeRates)
      historical → taxas do dia anterior (ExchangeRates)

    Retorna:
      FXReport com variações, alertas e resumo estatístico.
    """
    variations = compare_rates(live, historical)
    summary    = build_summary(variations)

    return FXReport(
        base_currency=live.base,
        generated_at=datetime.now(timezone.utc).isoformat(),
        live_date=live.date,
        historical_date=historical.date,
        currencies_analyzed=[v.currency for v in variations],
        alerts=[v.currency for v in variations if v.alert],
        variations=variations,
        summary=summary,
    )
