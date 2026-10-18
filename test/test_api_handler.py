"""
test_api_handler.py — Testes unitários do handler da API de consulta

Testa o roteamento, a leitura do evento do API Gateway e a validação dos
parâmetros. A leitura do S3 é substituída por um relatório sintético com
unittest.mock, então nenhum teste toca a AWS.

Como rodar:
  python test/test_api_handler.py

Funções testadas:
  extract_path         → descoberta do caminho nos dois formatos de evento
  extract_params       → query string ausente virando dicionário vazio
  handle_trends        → validação do parâmetro ?days
  handle_latest_report → relatório completo e recorte por moeda
  lambda_handler       → roteamento, 404 de rota e 500 de erro inesperado
"""

import sys
import os
import json

# Adiciona src/ ao path para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from unittest.mock import patch

import api_handler
from api_handler import (
    extract_path,
    extract_params,
    handle_trends,
    handle_latest_report,
    handle_alerts,
    lambda_handler,
)


# ── Dados sintéticos ─────────────────────────────────────────────

RELATORIO = {
    "base_currency":       "USD",
    "generated_at":        "2026-10-18T08:00:00+00:00",
    "currencies_analyzed": ["BRL", "EUR"],
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
}


def evento_v2(caminho: str, params: dict = None, stage: str = "$default") -> dict:
    """Monta um evento no formato HTTP API (payload 2.0)."""
    return {
        "rawPath":               caminho,
        "queryStringParameters": params,
        "requestContext": {
            "stage": stage,
            "http":  {"method": "GET", "path": caminho},
        },
    }


# ── Testes: extract_path() ───────────────────────────────────────

class TestExtractPath(unittest.TestCase):
    """Testa a leitura do caminho nos dois formatos de evento."""

    def test_formato_http_api_v2(self):
        """HTTP API usa rawPath."""
        self.assertEqual(extract_path({"rawPath": "/alerts"}), "/alerts")

    def test_formato_rest_api_v1(self):
        """REST API usa path."""
        self.assertEqual(extract_path({"path": "/alerts"}), "/alerts")

    def test_remove_nome_do_stage(self):
        """O stage no começo do caminho deve ser removido antes de rotear."""
        evento = {"rawPath": "/v1/reports/latest", "requestContext": {"stage": "v1"}}

        self.assertEqual(extract_path(evento), "/reports/latest")

    def test_stage_default_nao_e_removido(self):
        """O stage $default não aparece na URL, então nada deve ser cortado."""
        evento = {"rawPath": "/alerts", "requestContext": {"stage": "$default"}}

        self.assertEqual(extract_path(evento), "/alerts")

    def test_nao_corta_caminho_parecido_com_stage(self):
        """
        Um caminho que só começa com letras parecidas com o stage não deve
        ser cortado pela metade.
        """
        evento = {"rawPath": "/v1x/alerts", "requestContext": {"stage": "v1"}}

        self.assertEqual(extract_path(evento), "/v1x/alerts")

    def test_remove_barra_final(self):
        """Barra no fim não deve criar uma rota diferente."""
        self.assertEqual(extract_path({"rawPath": "/alerts/"}), "/alerts")

    def test_evento_vazio(self):
        """Evento sem caminho nenhum deve cair na raiz, não estourar."""
        self.assertEqual(extract_path({}), "/")


# ── Testes: extract_params() ─────────────────────────────────────

class TestExtractParams(unittest.TestCase):
    """Testa a leitura da query string."""

    def test_query_string_ausente(self):
        """O API Gateway envia None — deve virar dicionário vazio."""
        self.assertEqual(extract_params({"queryStringParameters": None}), {})

    def test_campo_inexistente(self):
        """Evento sem o campo também deve virar dicionário vazio."""
        self.assertEqual(extract_params({}), {})

    def test_com_parametros(self):
        """Parâmetros presentes devem passar direto."""
        evento = {"queryStringParameters": {"days": "10"}}

        self.assertEqual(extract_params(evento), {"days": "10"})


# ── Testes: validação do ?days em /trends ────────────────────────

class TestHandleTrends(unittest.TestCase):
    """Testa a validação do parâmetro days antes de ler o S3."""

    def test_days_nao_numerico(self):
        """Texto no lugar de número deve dar 400 sem consultar nada."""
        status, body = handle_trends({"days": "sete"})

        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_days_abaixo_do_minimo(self):
        """Um dia só não forma série temporal — 400."""
        status, body = handle_trends({"days": "1"})

        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_days_acima_do_maximo(self):
        """Janela grande demais estouraria o timeout da Lambda — 400."""
        status, body = handle_trends({"days": "365"})

        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_days_negativo(self):
        """O sinal de menos faz o isdigit() falhar — 400, não exceção."""
        status, body = handle_trends({"days": "-5"})

        self.assertEqual(status, 400)

    @patch("api_handler.analyze_trends")
    def test_days_valido_chega_no_trends(self, mock_trends):
        """Valor dentro da faixa deve ser repassado para o analyze_trends."""
        mock_trends.return_value = {"reports_found": 3, "trends": {}}

        status, body = handle_trends({"days": "5"})

        self.assertEqual(status, 200)
        mock_trends.assert_called_once()
        self.assertEqual(mock_trends.call_args.kwargs["days"], 5)

    @patch("api_handler.analyze_trends")
    def test_sem_historico(self, mock_trends):
        """Janela sem nenhum relatório deve dar 404."""
        mock_trends.return_value = {"reports_found": 0, "trends": {}}

        status, body = handle_trends({})

        self.assertEqual(status, 404)
        self.assertEqual(body["window_days"], 7)


# ── Testes: /reports/latest e /alerts ────────────────────────────

class TestHandleLatestReport(unittest.TestCase):
    """Testa o endpoint do relatório mais recente."""

    @patch("api_handler.find_latest_report")
    def test_relatorio_completo(self, mock_find):
        """Sem parâmetro, devolve o relatório inteiro."""
        mock_find.return_value = RELATORIO

        status, body = handle_latest_report({})

        self.assertEqual(status, 200)
        self.assertEqual(body["base_currency"], "USD")
        self.assertEqual(len(body["variations"]), 2)

    @patch("api_handler.find_latest_report")
    def test_recorte_por_moeda(self, mock_find):
        """Com ?currency, devolve só aquela moeda."""
        mock_find.return_value = RELATORIO

        status, body = handle_latest_report({"currency": "BRL"})

        self.assertEqual(status, 200)
        self.assertEqual(body["currency"], "BRL")
        self.assertNotIn("variations", body)

    @patch("api_handler.find_latest_report")
    def test_moeda_com_formato_invalido(self, mock_find):
        """Código que não tem 3 letras deve dar 400."""
        mock_find.return_value = RELATORIO

        status, body = handle_latest_report({"currency": "REAL"})

        self.assertEqual(status, 400)

        status, body = handle_latest_report({"currency": "B2L"})

        self.assertEqual(status, 400)

    @patch("api_handler.find_latest_report")
    def test_moeda_nao_analisada(self, mock_find):
        """Moeda válida mas fora do relatório deve dar 404 com as opções."""
        mock_find.return_value = RELATORIO

        status, body = handle_latest_report({"currency": "JPY"})

        self.assertEqual(status, 404)
        self.assertEqual(body["currencies_available"], ["BRL", "EUR"])

    @patch("api_handler.find_latest_report")
    def test_bucket_sem_relatorio(self, mock_find):
        """Bucket vazio deve dar 404, não 500."""
        mock_find.return_value = None

        status, body = handle_latest_report({})

        self.assertEqual(status, 404)
        self.assertIn("error", body)

    @patch("api_handler.find_latest_report")
    def test_alertas_com_relatorio(self, mock_find):
        """O endpoint de alertas devolve a contagem e o limiar."""
        mock_find.return_value = RELATORIO

        status, body = handle_alerts({})

        self.assertEqual(status, 200)
        self.assertEqual(body["alerts_count"], 1)
        self.assertEqual(body["threshold_pct"], 1.5)


# ── Testes: lambda_handler() ─────────────────────────────────────

class TestLambdaHandler(unittest.TestCase):
    """Testa o entry point: roteamento e formato da resposta."""

    def test_health(self):
        """O healthcheck responde 200 sem tocar no S3."""
        resposta = lambda_handler(evento_v2("/health"), None)

        self.assertEqual(resposta["statusCode"], 200)
        corpo = json.loads(resposta["body"])
        self.assertEqual(corpo["status"], "ok")
        self.assertIn("/alerts", corpo["endpoints"])

    def test_rota_inexistente(self):
        """Rota desconhecida deve dar 404 listando as rotas que existem."""
        resposta = lambda_handler(evento_v2("/cotacao"), None)

        self.assertEqual(resposta["statusCode"], 404)
        corpo = json.loads(resposta["body"])
        self.assertIn("/trends", corpo["endpoints_available"])

    def test_resposta_tem_content_type(self):
        """Toda resposta deve sair com Content-Type de JSON."""
        resposta = lambda_handler(evento_v2("/health"), None)

        self.assertIn("application/json", resposta["headers"]["Content-Type"])

    def test_body_e_json_valido(self):
        """O body precisa ser string JSON — é o que o API Gateway exige."""
        resposta = lambda_handler(evento_v2("/health"), None)

        self.assertIsInstance(resposta["body"], str)
        json.loads(resposta["body"])  # não deve lançar

    @patch("api_handler.find_latest_report")
    def test_erro_inesperado_vira_500(self, mock_find):
        """
        Exceção não prevista dentro do handler deve virar 500 limpo,
        sem vazar a mensagem do erro para quem chamou.
        """
        mock_find.side_effect = RuntimeError("boom: credencial do S3 expirada")

        resposta = lambda_handler(evento_v2("/alerts"), None)

        self.assertEqual(resposta["statusCode"], 500)
        corpo = json.loads(resposta["body"])
        self.assertNotIn("boom", corpo["error"])

    @patch("api_handler.find_latest_report")
    def test_roteamento_com_stage_no_caminho(self, mock_find):
        """Com stage nomeado, a rota ainda tem que ser encontrada."""
        mock_find.return_value = RELATORIO

        evento = evento_v2("/v1/reports/latest", stage="v1")
        resposta = lambda_handler(evento, None)

        self.assertEqual(resposta["statusCode"], 200)

    @patch("api_handler.find_latest_report")
    def test_query_string_chega_no_handler(self, mock_find):
        """O parâmetro da URL tem que chegar no handler da rota."""
        mock_find.return_value = RELATORIO

        evento = evento_v2("/reports/latest", params={"currency": "EUR"})
        resposta = lambda_handler(evento, None)

        corpo = json.loads(resposta["body"])
        self.assertEqual(corpo["currency"], "EUR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
