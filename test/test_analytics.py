"""
test_analytics.py — Testes unitários do módulo analytics

Testa as funções de análise avançada de dados de câmbio:
  - classify_risk        → classificação de risco por variação
  - calculate_statistics → estatísticas descritivas
  - build_cross_rate_matrix → taxas cruzadas entre moedas
  - detect_anomalies     → detecção de variações anômalas via z-score
  - assess_market_sentiment → sentimento geral do mercado
  - analyze              → função principal de integração

Usa dados fictícios — sem chamadas HTTP nem acesso à AWS.

Como rodar:
  python -m pytest test/test_analytics.py -v
"""

import sys
import os

# Adiciona src/ ao path para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from api_client import ExchangeRates
from processor import CurrencyVariation, FXReport
from analytics import (
    classify_risk,
    calculate_statistics,
    build_cross_rate_matrix,
    detect_anomalies,
    assess_market_sentiment,
    analyze,
    RISK_THRESHOLDS,
    ANOMALY_Z_THRESHOLD,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_variation(currency, rate_now, rate_prev, variation_pct, direction, alert=False):
    """Cria um CurrencyVariation para uso nos testes."""
    return CurrencyVariation(
        currency=currency,
        rate_now=rate_now,
        rate_prev=rate_prev,
        variation_pct=variation_pct,
        direction=direction,
        alert=alert,
    )


def _make_report(variations, base="USD"):
    """Cria um FXReport mínimo para uso nos testes."""
    return FXReport(
        base_currency=base,
        generated_at="2024-03-10T08:00:00+00:00",
        live_date="2024-03-10",
        historical_date="2024-03-09",
        currencies_analyzed=[v.currency for v in variations],
        variations=variations,
        alerts=[v.currency for v in variations if v.alert],
        summary={},
    )


# ── Testes: classify_risk() ──────────────────────────────────────

class TestClassifyRisk(unittest.TestCase):
    """Testa a classificação de risco baseada na variação percentual."""

    def test_low_risk_positive(self):
        """Variação de +0.3% deve ser LOW."""
        self.assertEqual(classify_risk(0.3), "LOW")

    def test_low_risk_negative(self):
        """Variação de -0.2% deve ser LOW (usa valor absoluto)."""
        self.assertEqual(classify_risk(-0.2), "LOW")

    def test_low_risk_zero(self):
        """Variação zero deve ser LOW."""
        self.assertEqual(classify_risk(0.0), "LOW")

    def test_medium_risk(self):
        """Variação de +0.8% deve ser MEDIUM."""
        self.assertEqual(classify_risk(0.8), "MEDIUM")

    def test_medium_risk_boundary(self):
        """Variação exatamente em 0.5% deve ser MEDIUM (não LOW)."""
        self.assertEqual(classify_risk(0.5), "MEDIUM")

    def test_high_risk(self):
        """Variação de +2.0% deve ser HIGH."""
        self.assertEqual(classify_risk(2.0), "HIGH")

    def test_high_risk_negative(self):
        """Variação de -2.5% deve ser HIGH."""
        self.assertEqual(classify_risk(-2.5), "HIGH")

    def test_high_risk_boundary(self):
        """Variação exatamente em 1.5% deve ser HIGH (coincide com alerta)."""
        self.assertEqual(classify_risk(1.5), "HIGH")

    def test_critical_risk(self):
        """Variação de +5.0% deve ser CRITICAL."""
        self.assertEqual(classify_risk(5.0), "CRITICAL")

    def test_critical_risk_negative(self):
        """Variação de -4.0% deve ser CRITICAL."""
        self.assertEqual(classify_risk(-4.0), "CRITICAL")

    def test_critical_risk_boundary(self):
        """Variação exatamente em 3.0% deve ser CRITICAL."""
        self.assertEqual(classify_risk(3.0), "CRITICAL")


# ── Testes: calculate_statistics() ────────────────────────────────

class TestCalculateStatistics(unittest.TestCase):
    """Testa o cálculo de estatísticas descritivas das variações."""

    def test_empty_list(self):
        """Lista vazia deve retornar zeros sem erro."""
        stats = calculate_statistics([])
        self.assertEqual(stats["mean"], 0.0)
        self.assertEqual(stats["median"], 0.0)
        self.assertEqual(stats["std_dev"], 0.0)
        self.assertEqual(stats["range"], 0.0)
        self.assertEqual(stats["count"], 0)

    def test_single_variation(self):
        """Uma única variação: média = mediana = valor, desvio = 0."""
        variations = [_make_variation("EUR", 0.92, 0.91, 1.0989, "up")]
        stats = calculate_statistics(variations)

        self.assertAlmostEqual(stats["mean"], 1.0989, places=4)
        self.assertAlmostEqual(stats["median"], 1.0989, places=4)
        self.assertEqual(stats["std_dev"], 0.0)
        self.assertEqual(stats["range"], 0.0)
        self.assertEqual(stats["count"], 1)

    def test_odd_count_median(self):
        """Número ímpar de variações: mediana é o valor central."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.5, "up"),
            _make_variation("JPY", 150, 151, -0.5, "down"),
        ]
        stats = calculate_statistics(variations)

        # Mediana de [-0.5, 1.0, 2.5] → 1.0
        self.assertAlmostEqual(stats["median"], 1.0, places=4)
        self.assertEqual(stats["count"], 3)

    def test_even_count_median(self):
        """Número par de variações: mediana é a média dos dois centrais."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 3.0, "up"),
            _make_variation("JPY", 150, 151, -0.5, "down"),
            _make_variation("GBP", 0.79, 0.78, 0.5, "up"),
        ]
        stats = calculate_statistics(variations)

        # Ordenado: [-0.5, 0.5, 1.0, 3.0] → mediana = (0.5+1.0)/2 = 0.75
        self.assertAlmostEqual(stats["median"], 0.75, places=4)

    def test_mean_calculation(self):
        """Verifica que a média é calculada corretamente."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 2.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 4.0, "up"),
        ]
        stats = calculate_statistics(variations)

        # Média de [2.0, 4.0] = 3.0
        self.assertAlmostEqual(stats["mean"], 3.0, places=4)

    def test_std_dev_calculation(self):
        """Verifica o desvio padrão com valores conhecidos."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 2.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 4.0, "up"),
        ]
        stats = calculate_statistics(variations)

        # Média = 3.0, variância = ((2-3)^2 + (4-3)^2)/2 = 1.0, std = 1.0
        self.assertAlmostEqual(stats["std_dev"], 1.0, places=4)

    def test_range_calculation(self):
        """Range é a diferença entre o maior e menor valor."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, -1.0, "down"),
            _make_variation("BRL", 4.97, 4.85, 3.0, "up"),
        ]
        stats = calculate_statistics(variations)

        # Range = 3.0 - (-1.0) = 4.0
        self.assertAlmostEqual(stats["range"], 4.0, places=4)

    def test_abs_mean_calculation(self):
        """Média absoluta ignora sinal das variações."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, -2.0, "down"),
            _make_variation("BRL", 4.97, 4.85, 4.0, "up"),
        ]
        stats = calculate_statistics(variations)

        # abs_mean = (2.0 + 4.0) / 2 = 3.0
        self.assertAlmostEqual(stats["abs_mean"], 3.0, places=4)


# ── Testes: build_cross_rate_matrix() ─────────────────────────────

class TestBuildCrossRateMatrix(unittest.TestCase):
    """Testa a construção da matriz de taxas cruzadas."""

    def setUp(self):
        """Cria ExchangeRates com taxas conhecidas para cálculos verificáveis."""
        self.rates = ExchangeRates(
            base="USD",
            date="2024-03-10",
            source="test",
            rates={"EUR": 0.92, "BRL": 5.0, "GBP": 0.80}
        )

    def test_diagonal_is_one(self):
        """Toda moeda convertida para ela mesma deve dar 1.0."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR", "BRL", "GBP"])

        self.assertEqual(matrix["EUR"]["EUR"], 1.0)
        self.assertEqual(matrix["BRL"]["BRL"], 1.0)
        self.assertEqual(matrix["GBP"]["GBP"], 1.0)

    def test_cross_rate_eur_brl(self):
        """EUR→BRL: se 1 USD = 0.92 EUR e 1 USD = 5.0 BRL, então 1 EUR = 5.0/0.92."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR", "BRL"])

        expected = round(5.0 / 0.92, 6)
        self.assertAlmostEqual(matrix["EUR"]["BRL"], expected, places=5)

    def test_cross_rate_brl_eur(self):
        """BRL→EUR: inverso de EUR→BRL."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR", "BRL"])

        expected = round(0.92 / 5.0, 6)
        self.assertAlmostEqual(matrix["BRL"]["EUR"], expected, places=5)

    def test_inverse_rates_product(self):
        """A→B * B→A deve ser aproximadamente 1.0."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR", "BRL"])

        product = matrix["EUR"]["BRL"] * matrix["BRL"]["EUR"]
        self.assertAlmostEqual(product, 1.0, places=4)

    def test_missing_currency_ignored(self):
        """Moeda que não existe no rates é excluída da matriz."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR", "XXX", "BRL"])

        self.assertNotIn("XXX", matrix)
        self.assertIn("EUR", matrix)
        self.assertIn("BRL", matrix)

    def test_default_currencies(self):
        """Sem lista explícita, usa todas as moedas do rates."""
        matrix = build_cross_rate_matrix(self.rates)

        self.assertIn("EUR", matrix)
        self.assertIn("BRL", matrix)
        self.assertIn("GBP", matrix)
        self.assertEqual(len(matrix), 3)

    def test_single_currency(self):
        """Matriz de uma moeda só: só a diagonal."""
        matrix = build_cross_rate_matrix(self.rates, ["EUR"])

        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix["EUR"]["EUR"], 1.0)


# ── Testes: detect_anomalies() ────────────────────────────────────

class TestDetectAnomalies(unittest.TestCase):
    """Testa a detecção de anomalias por z-score."""

    def test_no_anomalies_uniform(self):
        """Variações uniformes: sem anomalias."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 1.1, "up"),
            _make_variation("GBP", 0.79, 0.78, 0.9, "up"),
        ]
        anomalies = detect_anomalies(variations)
        self.assertEqual(len(anomalies), 0)

    def test_detects_outlier(self):
        """Uma variação muito diferente das demais é detectada como anomalia."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 0.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 0.6, "up"),
            _make_variation("GBP", 0.79, 0.78, 0.4, "up"),
            _make_variation("JPY", 150, 151, 0.5, "up"),
            _make_variation("ARS", 800, 700, 14.0, "up", alert=True),
        ]
        anomalies = detect_anomalies(variations)

        self.assertGreater(len(anomalies), 0)
        # ARS deve ser a maior anomalia (z-score mais alto)
        self.assertEqual(anomalies[0]["currency"], "ARS")

    def test_less_than_two_variations(self):
        """Com menos de 2 variações, retorna lista vazia."""
        variations = [_make_variation("EUR", 0.92, 0.91, 1.0, "up")]
        anomalies = detect_anomalies(variations)
        self.assertEqual(anomalies, [])

    def test_zero_std_dev(self):
        """Se todas variações forem iguais (std=0), sem anomalias."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 1.0, "up"),
        ]
        anomalies = detect_anomalies(variations)
        self.assertEqual(anomalies, [])

    def test_anomaly_has_required_fields(self):
        """Anomalias detectadas devem ter todos os campos obrigatórios."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 0.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 0.5, "up"),
            _make_variation("ARS", 800, 700, 10.0, "up", alert=True),
        ]
        anomalies = detect_anomalies(variations)

        if anomalies:
            anomaly = anomalies[0]
            self.assertIn("currency", anomaly)
            self.assertIn("variation_pct", anomaly)
            self.assertIn("z_score", anomaly)
            self.assertIn("direction", anomaly)
            self.assertIn("severity", anomaly)

    def test_severity_extreme(self):
        """Z-score >= 2.5 deve ter severity EXTREME."""
        # Precisamos de muitos pontos próximos para que o outlier tenha
        # z-score alto o bastante (>= 2.5). Com 9 moedas em ~0.5% e uma
        # em 50%, o desvio padrão fica baixo o bastante para o z-score
        # do ARS ultrapassar 2.5.
        variations = [
            _make_variation("EUR", 0.92, 0.91, 0.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 0.5, "up"),
            _make_variation("GBP", 0.79, 0.78, 0.5, "up"),
            _make_variation("JPY", 150, 151, 0.5, "up"),
            _make_variation("CAD", 1.35, 1.34, 0.5, "up"),
            _make_variation("CHF", 0.88, 0.87, 0.5, "up"),
            _make_variation("AUD", 1.53, 1.52, 0.5, "up"),
            _make_variation("NZD", 1.60, 1.59, 0.5, "up"),
            _make_variation("MXN", 17.0, 16.9, 0.5, "up"),
            _make_variation("ARS", 800, 700, 50.0, "up", alert=True),
        ]
        anomalies = detect_anomalies(variations)

        self.assertGreater(len(anomalies), 0)
        ars = [a for a in anomalies if a["currency"] == "ARS"]
        self.assertEqual(len(ars), 1)
        self.assertEqual(ars[0]["severity"], "EXTREME")

    def test_custom_z_threshold(self):
        """Threshold customizado altera sensibilidade da detecção."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.0, "up"),
            _make_variation("GBP", 0.79, 0.78, 0.5, "up"),
        ]

        # Com threshold alto, menos anomalias
        strict = detect_anomalies(variations, z_threshold=3.0)
        # Com threshold baixo, mais anomalias
        relaxed = detect_anomalies(variations, z_threshold=0.5)

        self.assertGreaterEqual(len(relaxed), len(strict))

    def test_sorted_by_z_score(self):
        """Anomalias devem ser ordenadas por z-score absoluto decrescente."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 0.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 0.5, "up"),
            _make_variation("GBP", 0.79, 0.78, 5.0, "up"),
            _make_variation("ARS", 800, 700, 15.0, "up", alert=True),
        ]
        anomalies = detect_anomalies(variations)

        if len(anomalies) >= 2:
            for i in range(len(anomalies) - 1):
                self.assertGreaterEqual(
                    abs(anomalies[i]["z_score"]),
                    abs(anomalies[i + 1]["z_score"]),
                )


# ── Testes: assess_market_sentiment() ─────────────────────────────

class TestAssessMarketSentiment(unittest.TestCase):
    """Testa a avaliação de sentimento de mercado."""

    def test_empty_variations(self):
        """Sem variações: sentimento NEUTRAL com confiança 0."""
        sentiment = assess_market_sentiment([])
        self.assertEqual(sentiment["sentiment"], "NEUTRAL")
        self.assertEqual(sentiment["confidence"], 0.0)

    def test_bullish_majority(self):
        """Maioria subindo → BULLISH."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.0, "up"),
            _make_variation("GBP", 0.79, 0.78, 0.5, "up"),
            _make_variation("JPY", 150, 151, -0.5, "down"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["sentiment"], "BULLISH")
        self.assertEqual(sentiment["up_count"], 3)
        self.assertEqual(sentiment["down_count"], 1)

    def test_bearish_majority(self):
        """Maioria caindo → BEARISH."""
        variations = [
            _make_variation("EUR", 0.91, 0.92, -1.0, "down"),
            _make_variation("BRL", 4.85, 4.97, -2.0, "down"),
            _make_variation("GBP", 0.78, 0.79, -0.5, "down"),
            _make_variation("JPY", 151, 150, 0.5, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["sentiment"], "BEARISH")

    def test_mixed_sentiment(self):
        """Sem maioria clara → MIXED."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.85, 4.97, -2.0, "down"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["sentiment"], "MIXED")

    def test_confidence_range(self):
        """Confiança deve estar entre 0 e 1."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.0, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertGreaterEqual(sentiment["confidence"], 0.0)
        self.assertLessEqual(sentiment["confidence"], 1.0)

    def test_volatility_calm(self):
        """Variações muito pequenas → CALM."""
        variations = [
            _make_variation("EUR", 0.92, 0.92, 0.1, "up"),
            _make_variation("BRL", 4.97, 4.97, 0.2, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["volatility_level"], "CALM")

    def test_volatility_normal(self):
        """Variações moderadas → NORMAL."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 0.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 0.7, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["volatility_level"], "NORMAL")

    def test_volatility_elevated(self):
        """Variações acima de 1% em média → ELEVATED."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.5, "up"),
            _make_variation("BRL", 4.97, 4.85, 1.2, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["volatility_level"], "ELEVATED")

    def test_volatility_high(self):
        """Variações acima de 2% em média → HIGH."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 3.0, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.5, "up"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["volatility_level"], "HIGH")

    def test_counts_correct(self):
        """Contagens por direção devem bater."""
        variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0, "up"),
            _make_variation("BRL", 4.85, 4.97, -2.0, "down"),
            _make_variation("JPY", 150, 150, 0.0, "stable"),
        ]
        sentiment = assess_market_sentiment(variations)
        self.assertEqual(sentiment["up_count"], 1)
        self.assertEqual(sentiment["down_count"], 1)
        self.assertEqual(sentiment["stable_count"], 1)


# ── Testes: analyze() — integração ────────────────────────────────

class TestAnalyze(unittest.TestCase):
    """Testa a função principal de integração do módulo analytics."""

    def setUp(self):
        """Monta fixtures completas para teste de integração."""
        self.live_rates = ExchangeRates(
            base="USD",
            date="2024-03-10",
            source="test",
            rates={"EUR": 0.92, "BRL": 4.97, "GBP": 0.79, "JPY": 150.0}
        )

        self.variations = [
            _make_variation("EUR", 0.92, 0.91, 1.0989, "up"),
            _make_variation("BRL", 4.97, 4.85, 2.4742, "up", alert=True),
            _make_variation("GBP", 0.79, 0.80, -1.25, "down"),
            _make_variation("JPY", 150.0, 149.0, 0.6711, "up"),
        ]

        self.report = _make_report(self.variations)

    def test_returns_all_sections(self):
        """O resultado deve conter todas as 5 seções de análise."""
        result = analyze(self.report, self.live_rates)

        self.assertIn("risk_classification", result)
        self.assertIn("statistics", result)
        self.assertIn("cross_rate_matrix", result)
        self.assertIn("anomalies", result)
        self.assertIn("market_sentiment", result)

    def test_risk_classification_all_currencies(self):
        """Cada moeda analisada deve ter uma classificação de risco."""
        result = analyze(self.report, self.live_rates)
        risk = result["risk_classification"]

        for currency in self.report.currencies_analyzed:
            self.assertIn(currency, risk)
            self.assertIn(risk[currency]["level"], ["LOW", "MEDIUM", "HIGH", "CRITICAL"])

    def test_statistics_has_required_fields(self):
        """Estatísticas devem ter todos os campos obrigatórios."""
        result = analyze(self.report, self.live_rates)
        stats = result["statistics"]

        required = ["mean", "median", "std_dev", "range", "abs_mean", "count"]
        for field in required:
            self.assertIn(field, stats)

    def test_cross_rate_matrix_structure(self):
        """Matriz deve ter todas as moedas analisadas com diagonal = 1.0."""
        result = analyze(self.report, self.live_rates)
        matrix = result["cross_rate_matrix"]

        for currency in self.report.currencies_analyzed:
            if currency in matrix:
                self.assertAlmostEqual(matrix[currency][currency], 1.0)

    def test_market_sentiment_structure(self):
        """Sentimento deve ter todos os campos obrigatórios."""
        result = analyze(self.report, self.live_rates)
        sentiment = result["market_sentiment"]

        required = ["sentiment", "confidence", "up_count", "down_count",
                     "stable_count", "avg_magnitude", "volatility_level"]
        for field in required:
            self.assertIn(field, sentiment)

    def test_anomalies_is_list(self):
        """Anomalias deve ser uma lista (vazia ou com items)."""
        result = analyze(self.report, self.live_rates)
        self.assertIsInstance(result["anomalies"], list)

    def test_with_empty_report(self):
        """Relatório vazio não deve causar erro."""
        empty_report = _make_report([])
        result = analyze(empty_report, self.live_rates)

        self.assertEqual(result["statistics"]["count"], 0)
        self.assertEqual(result["market_sentiment"]["sentiment"], "NEUTRAL")
        self.assertEqual(len(result["anomalies"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
