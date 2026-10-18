"""
test_query.py — Testes unitários do módulo query

Testa os recortes de relatório usados pela API de consulta, com um
relatório sintético — sem S3, sem disco, sem chamada HTTP.

Como rodar:
  python test/test_query.py

Funções testadas:
  filter_currency → recorte de uma moeda do relatório
  extract_alerts  → alertas com variação e risco anexados
"""

import sys
import os

# Adiciona src/ ao path para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from query import filter_currency, extract_alerts


# ── Dados sintéticos ─────────────────────────────────────────────
# Relatório no mesmo formato que FXReport.to_dict() produz, incluindo
# o bloco analytics que o módulo analytics.py anexa.

RELATORIO = {
    "base_currency":       "USD",
    "generated_at":        "2026-10-18T08:00:00+00:00",
    "live_date":           "2026-10-18",
    "historical_date":     "2026-10-17",
    "currencies_analyzed": ["BRL", "ARS", "EUR"],
    "variations": [
        {
            "currency":      "BRL",
            "rate_now":      5.40,
            "rate_prev":     5.20,
            "variation_pct": 3.8462,
            "direction":     "up",
            "alert":         True,
        },
        {
            "currency":      "ARS",
            "rate_now":      1010.0,
            "rate_prev":     1000.0,
            "variation_pct": 1.0,
            "direction":     "up",
            "alert":         False,
        },
        {
            "currency":      "EUR",
            "rate_now":      0.92,
            "rate_prev":     0.92,
            "variation_pct": 0.0,
            "direction":     "stable",
            "alert":         False,
        },
    ],
    "alerts":  ["BRL"],
    "summary": {},
    "analytics": {
        "risk_classification": {
            "BRL": {"level": "CRITICAL", "variation_pct": 3.8462, "direction": "up"},
            "ARS": {"level": "MEDIUM",   "variation_pct": 1.0,    "direction": "up"},
            "EUR": {"level": "LOW",      "variation_pct": 0.0,    "direction": "stable"},
        },
        "market_sentiment": {"sentiment": "BEARISH"},
    },
}

# Mesmo relatório, mas sem o bloco analytics — acontece quando o
# enriquecimento falha e a Lambda agendada segue em frente (passo 4b).
RELATORIO_SEM_ANALYTICS = {
    "base_currency":       "USD",
    "generated_at":        "2026-10-18T08:00:00+00:00",
    "currencies_analyzed": ["BRL"],
    "variations":          [RELATORIO["variations"][0]],
    "alerts":              ["BRL"],
}


# ── Testes: filter_currency() ────────────────────────────────────

class TestFilterCurrency(unittest.TestCase):
    """Testa o recorte de uma moeda do relatório."""

    def test_moeda_existente(self):
        """Deve devolver os dados da moeda pedida."""
        recorte = filter_currency(RELATORIO, "BRL")

        self.assertIsNotNone(recorte)
        self.assertEqual(recorte["currency"], "BRL")
        self.assertEqual(recorte["rate_now"], 5.40)
        self.assertEqual(recorte["rate_prev"], 5.20)
        self.assertEqual(recorte["direction"], "up")
        self.assertTrue(recorte["alert"])

    def test_moeda_em_minusculas(self):
        """Deve aceitar o código em minúsculas e normalizar para maiúsculas."""
        recorte = filter_currency(RELATORIO, "brl")

        self.assertIsNotNone(recorte)
        self.assertEqual(recorte["currency"], "BRL")

    def test_anexa_risco_do_analytics(self):
        """Deve incluir o nível de risco quando o relatório tem analytics."""
        recorte = filter_currency(RELATORIO, "BRL")

        self.assertEqual(recorte["risk_level"], "CRITICAL")

    def test_sem_analytics_nao_quebra(self):
        """Sem o bloco analytics, o recorte vem sem risk_level — mas vem."""
        recorte = filter_currency(RELATORIO_SEM_ANALYTICS, "BRL")

        self.assertIsNotNone(recorte)
        self.assertEqual(recorte["currency"], "BRL")
        self.assertNotIn("risk_level", recorte)

    def test_moeda_ausente(self):
        """Moeda que não está no relatório deve retornar None."""
        self.assertIsNone(filter_currency(RELATORIO, "JPY"))

    def test_herda_metadados_do_relatorio(self):
        """O recorte deve carregar a base e a data de geração do relatório."""
        recorte = filter_currency(RELATORIO, "EUR")

        self.assertEqual(recorte["base_currency"], "USD")
        self.assertEqual(recorte["generated_at"], "2026-10-18T08:00:00+00:00")


# ── Testes: extract_alerts() ─────────────────────────────────────

class TestExtractAlerts(unittest.TestCase):
    """Testa a montagem da resposta do endpoint de alertas."""

    def test_conta_alertas(self):
        """A contagem deve bater com o número de moedas alertadas."""
        resposta = extract_alerts(RELATORIO)

        self.assertEqual(resposta["alerts_count"], 1)
        self.assertEqual(len(resposta["alerts"]), 1)

    def test_alerta_vem_com_contexto(self):
        """Cada alerta deve trazer a variação, não só o código da moeda."""
        alerta = extract_alerts(RELATORIO)["alerts"][0]

        self.assertEqual(alerta["currency"], "BRL")
        self.assertEqual(alerta["variation_pct"], 3.8462)
        self.assertEqual(alerta["direction"], "up")
        self.assertEqual(alerta["rate_now"], 5.40)
        self.assertEqual(alerta["risk_level"], "CRITICAL")

    def test_inclui_threshold(self):
        """A resposta deve dizer qual limiar gerou os alertas."""
        resposta = extract_alerts(RELATORIO)

        self.assertEqual(resposta["threshold_pct"], 1.5)

    def test_inclui_sentimento_quando_disponivel(self):
        """O sentimento de mercado deve ser repassado quando existe."""
        resposta = extract_alerts(RELATORIO)

        self.assertEqual(resposta["market_sentiment"], "BEARISH")

    def test_sem_analytics_omite_sentimento(self):
        """Sem analytics, o campo de sentimento simplesmente não aparece."""
        resposta = extract_alerts(RELATORIO_SEM_ANALYTICS)

        self.assertNotIn("market_sentiment", resposta)
        self.assertEqual(resposta["alerts_count"], 1)

    def test_nenhum_alerta(self):
        """Dia calmo: lista vazia e contagem zero, sem erro."""
        relatorio_calmo = dict(RELATORIO)
        relatorio_calmo["alerts"] = []

        resposta = extract_alerts(relatorio_calmo)

        self.assertEqual(resposta["alerts_count"], 0)
        self.assertEqual(resposta["alerts"], [])

    def test_alerta_sem_variacao_correspondente(self):
        """
        Relatório inconsistente: a moeda está em alerts mas não em variations.
        Deve devolver o código mesmo assim, em vez de omitir o alerta.
        """
        relatorio_torto = dict(RELATORIO)
        relatorio_torto["alerts"] = ["BRL", "JPY"]

        resposta = extract_alerts(relatorio_torto)

        self.assertEqual(resposta["alerts_count"], 2)
        self.assertEqual(resposta["alerts"][1], {"currency": "JPY"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
