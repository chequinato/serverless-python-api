"""
processor.py — Processamento dos dados de câmbio e cálculo de variações

Recebe os dois ExchangeRates (live + histórico), cruza os dados
e produz um relatório com variações percentuais, alertas e estatísticas.

Conceitos Python exercitados:
  - Funções puras (sem side effects) — fáceis de testar
  - List comprehensions e dict comprehensions
  - sorted() com key lambda
  - round(), abs(), min(), max()
  - Dataclasses com métodos
  - Type hints e Optional
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.policy import default
from typing import Dict, List, Optional, Tuple
from api_client import ExchangeRates, DEFAULT_CURRENCIES

logger = logging.getLogger(__name__)

#Limiar de alerta de variação (0%)

ALERT_THRESHOLD = 1.5 # variação acima disso é sinalizada como alerta

# Estrutura de resultado
@dataclass
class CurrencyVariation:
    """Variação de uma moeda entre dois momentos."""
    currency: str
    rate_now: float  # taxa atual (live)
    rate_prev: float  # taxa do dia anterior (histórico)
    variation_pct: float  # variação percentual
    direction: str  # "up", "down" ou "stable"
    alert: bool  # True se variação superar o limiar

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "rate_now": self.rate_now,
            "rate_prev": self.rate_prev,
            "variation_pct": self.variation_pct,
            "direction": self.direction,
            "alert": self.alert,
        }

@dataclass
class FXReport:
    """Relatório completo gerado pela Lambda."""
    base_currency: str
    generated_at: str      # ISO 8601 UTC
    live_date: str
    historical_date: str
    currencies_analyzed: List[str]
    variations: List[CurrencyVariation] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)   # moedas com variação alta
    summary: Dict = field(default_factory=dict)

    def to_dict(self)-> dict:
        return{
            "base_currency": self.base_currency,
            "generated_at": self.generated_at,
            "live_date": self.live_date,
            "historical_date": self.historical_date,
            "currencies_analyzed": self.currencies_analyzed,
            "variations": [v.to_dict() for v in self.variations],
            "alerts": self.alerts,
            "summary": self.summary,
        }

# Funções de cálculo

def calculate_variation(rate_now: float, rate_prev: float) -> Tuple[float, str]:
    """
    Calcula variação percentual entre duas taxas.
    Retorna (variacao_pct, direcao).
    """
    if rate_prev == 0:
        return 0.0, "stable"


    pct = ((rate_now - rate_prev) / rate_prev * 100)
    pct = round(pct, 4)

    if pct > 0.01:
        direction = "up"
    elif pct < -0.01:
        direction = "down"
    else:
        direction = "stable"
    return pct, direction

def compare_rates(
        live: ExchangeRates,
        historical: ExchangeRates,
        currencies: Optional[List[str]] = None,
) -> List[CurrencyVariation]:
    """
    Cruza as taxas live e históricas e calcula variações.
    Ignora moedas que não estejam em ambas as fontes.
    """

    if currencies is None:
        currencies =  DEFAULT_CURRENCIES

    variations = []

    for currency in currencies:
        rate_now = live.get_rate(currency)
        rate_prev = historical.get_rate(currency)
