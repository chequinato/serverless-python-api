"""
api_client.py — Clientes HTTP para chamar as duas APIs de câmbio

APIs utilizadas (ambas têm plano gratuito):
  1. ExchangeRate-API  → taxas em tempo real  (https://www.exchangerate-api.com)
  2. Open Exchange Rates → histórico de 1 dia atrás (https://openexchangerates.org)

Em produção a Lambda chama ambas via HTTPS usando apenas urllib (stdlib).
Sem requests, sem httpx — Python puro mesmo.

Conceitos Python exercitados:
  - urllib.request / urllib.error — HTTP sem libs externas
  - urllib.parse.urlencode — construção de query strings
  - json.loads — desserialização de resposta
  - Dataclasses — estrutura de dados tipada sem dependências
  - Exceções customizadas — erros claros e rastreáveis
  - Type hints — boa prática mesmo em scripts simples
"""

import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from email.quoprimime import decode
from unittest.mock import DEFAULT
from datetime import date, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Tiemout padrão para chamadas HTTP (segundos)
HTTP_TIMEOUT = 10

# Moedas que a lambda processa por padrão
DEFAULT_CURRENCIES = ["USD", "EUR", "GBP", "BRL", "JPY", "CAD", "ARS"]

# Exceções de erros customizadas para a aplicação
class APIError(Exception):
    """Erro genérico ao chamar uma API externa."""

class APIRateLimitError(APIError):
    """Limite de requisições atingido (HTTP 429)."""

class APIAuthError(APIError):
    """Chave de API inválida ou sem permissão (HTTP 401/403)."""

# Estrutura de dados
@dataclass
class ExchangeRates:
    """Taxas de câmbio para uma moeda base em uma data específica."""
    base: str # ex: "USD"
    date: str  # ex: "2024-03-10"
    source: str  # nome da API que forneceu os dados
    rates: Dict[str, float] = field(default_factory=dict)

    def get_rate(self, currency: str) -> Optional[float]:
        """Retorna a taxa para uma moeda, ou None se não disponível."""
        return self.rates.get(currency.upper(), None)

    def convert(self, amount: float, to_currency: str) -> Optional[float]:
        """Converte um valor da moeda base para outra moeda."""
        rate = self.get_rate(to_currency)
        if rate is None:
            return None
        return round(amount * rate, 4)

# HTTP

def _http_get(url: str, headers: Optional[Dict] = None) -> dict:
    """
    Faz uma requisição GET e retorna o JSON parseado.
    Trata os erros HTTP mais comuns com mensagens claras.
    """
    req = urllib.request.Request(url, headers=headers or {})

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise APIAuthError(f"Chave de API inválida ou expirada. URL: {url}") from e
        elif e.code == 403:
            raise APIAuthError(f"Sem permissão para acessar este recurso. URL: {url}") from e
        elif e.code == 429:
            raise APIRateLimitError(f"Rate limit atingido. Tente novamente em breve. URL: {url}") from e
        else:
            raise APIError(f"HTTP {e.code} ao acessar {url}. Resposta: {body[:200]}") from e

    except urllib.error.URLError as e:
        raise APIError(f"Falha de rede ao acessar {url}: {e.reason}") from e

    except json.JSONDecodeError as e:
        raise APIError(f"Resposta inválida (não é JSON) de {url}") from e

# API 1 - ExchangeRateAPI (taxas em tempo real)

BASE_URL_EXCHANGERATE = "https://v6.exchangerate-api.com/v6"

def fetch_live_rates(api_key: str, base_currency: str) -> ExchangeRates:
    """
       Busca as taxas de câmbio em tempo real via ExchangeRate-API.

       Endpoint: GET /v6/{api_key}/latest/{base}
       Retorna um objeto ExchangeRates com as taxas de todas as moedas.

       Rate limit plano gratuito: 1.500 req/mês
       """

    url = f"{BASE_URL_EXCHANGERATE}/{api_key}/latest/{base_currency.upper()}/"
    logger.info(f"[ExchangeRate-API] Buscando taxas ao vivo para base={base_currency}")

    data = _http_get(url)
    if data.get("result") != "sucess":
        error_type = data.get("error-type", "unknown")
        raise APIError(f"ExchangeRate-API retornou erro: {error_type}")

    rates_raw = data.get("conversion_rates", {})

    return ExchangeRates(
        base=data["base_code"],
        date=data.get["times_last_updated_utc", "unknown"],
        source="ExchangeRate-API (live)",
        rates=rates_raw,
    )

# API 2 - Open Exchange Rates (histórico)

BASE_URL_OXR =  "https://openexchangerates.org/api"

def fetch_historical_rates(
        app_id: str,
        target_date: Optional[date] = None,
        base_currency: str = "USD",
) -> ExchangeRates:
    """
       Busca taxas históricas de 1 dia atrás via Open Exchange Rates.

       Endpoint: GET /historical/{date}.json?app_id={key}&base={base}
       Nota: no plano gratuito a base é sempre USD. Para outras bases,
             fazemos a conversão manualmente (divisão das taxas).

       Rate limit plano gratuito: 1.000 req/mês
       """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
        params = urllib.parse.urlencode({"app_id": app_id, "base": "USD"})
        url = f"{BASE_URL_OXR}/historical/{target_date}.json?{params}"

        logger.info(f"[Open Exchange Rates] Buscando histórico para {date_str}")

        data = _http_get(url)
        rates_raw = data.get("rates", {})

        # Se a base solicitada não for USD, rebase manualmente
        if base_currency.upper() != "USD":
            base_rate = rates_raw.get(base_currency.upper())
            if base_rate and base_rate != 0:
                rates_raw = {
                    currency: round(rate / base_rate, 6)
                    for currency, rate in rates_raw.items()
                }
            else:
                logger.warning(
                    f"Não foi possível fazer rebase para {base_currency}. "
                    "Retornando com base USD."
                )

        return ExchangeRates(
            base=base_currency.upper(),
            date=date_str,
            source="Open Exchange Rates (historical)",
            rates=rates_raw,
        )
