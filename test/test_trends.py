"""
test_trends.py — Testes unitários do módulo trends

Testa as funções de cálculo de tendência multi-day usando dados
sintéticos — sem chamadas HTTP, S3 ou disco.

Como rodar:
  python test/test_trends.py

Funções testadas:
  _sma                → média móvel simples
  _streak             → contagem de direção sustentada
  _accumulated_change → variação acumulada no período
  _volatility         → desvio padrão das variações diárias
  build_series        → montagem de série temporal por moeda
  calculate_trend     → cálculo completo de tendência para uma moeda
  analyze_trends      → função principal com histórico pré-carregado
"""

import sys
import os
import math

# Adiciona src/ ao path para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from trends import (
    _sma,
    _streak,
    _accumulated_change,
    _volatility,
    build_series,
    calculate_trend,
    analyze_trends,
)


# ── Dados sintéticos ─────────────────────────────────────────────

def _make_report(date_str, variations):
    """
    Cria um relatório fictício no formato esperado por build_series.

    Parâmetros:
      date_str   → data ISO 8601 do relatório
      variations → lista de tuplas (currency, rate_now, variation_pct)

    Retorna:
      Dicionário no formato de um relatório FXReport serializado.
    """
    return {
        "generated_at": date_str,
        "variations": [
            {
                "currency":      c,
                "rate_now":      rate,
                "variation_pct": pct,
            }
            for c, rate, pct in variations
        ],
    }


# 7 dias de dados para BRL e EUR
SAMPLE_REPORTS = [
    _make_report("2024-03-04T12:00:00Z", [("BRL", 4.90, 0.5),  ("EUR", 0.91,  0.1)]),
    _make_report("2024-03-05T12:00:00Z", [("BRL", 4.93, 0.61), ("EUR", 0.912, 0.22)]),
    _make_report("2024-03-06T12:00:00Z", [("BRL", 4.96, 0.61), ("EUR", 0.910, -0.22)]),
    _make_report("2024-03-07T12:00:00Z", [("BRL", 5.00, 0.81), ("EUR", 0.915, 0.55)]),
    _make_report("2024-03-08T12:00:00Z", [("BRL", 5.05, 1.0),  ("EUR", 0.913, -0.22)]),
    _make_report("2024-03-09T12:00:00Z", [("BRL", 5.08, 0.59), ("EUR", 0.911, -0.22)]),
    _make_report("2024-03-10T12:00:00Z", [("BRL", 5.12, 0.79), ("EUR", 0.908, -0.33)]),
]

# Dados com tendência de queda
FALLING_REPORTS = [
    _make_report("2024-03-04T12:00:00Z", [("JPY", 150.0, -0.3)]),
    _make_report("2024-03-05T12:00:00Z", [("JPY", 149.5, -0.33)]),
    _make_report("2024-03-06T12:00:00Z", [("JPY", 148.8, -0.47)]),
    _make_report("2024-03-07T12:00:00Z", [("JPY", 148.0, -0.54)]),
    _make_report("2024-03-08T12:00:00Z", [("JPY", 147.5, -0.34)]),
]


# ── Testes: _sma() ───────────────────────────────────────────────

class TestSma(unittest.TestCase):
    """Testa o cálculo da Média Móvel Simples."""

    def test_sma_basico(self):
        """SMA(3) de [1,2,3,4,5] deve começar com None nos 2 primeiros."""
        result = _sma([1, 2, 3, 4, 5], 3)
        self.assertIsNone(result[0])
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 2.0, places=4)
        self.assertAlmostEqual(result[3], 3.0, places=4)
        self.assertAlmostEqual(result[4], 4.0, places=4)

    def test_sma_periodo_1(self):
        """SMA(1) deve retornar os mesmos valores (identidade)."""
        values = [10.0, 20.0, 30.0]
        result = _sma(values, 1)
        for i, v in enumerate(values):
            self.assertAlmostEqual(result[i], v, places=4)

    def test_sma_lista_vazia(self):
        """SMA de lista vazia retorna lista vazia."""
        result = _sma([], 3)
        self.assertEqual(result, [])

    def test_sma_menos_que_periodo(self):
        """Lista menor que o período — todos None."""
        result = _sma([1, 2], 5)
        self.assertTrue(all(v is None for v in result))


# ── Testes: _streak() ────────────────────────────────────────────

class TestStreak(unittest.TestCase):
    """Testa a contagem de direção sustentada."""

    def test_streak_subindo(self):
        """5 valores positivos seguidos deve retornar (5, 'up')."""
        days, direction = _streak([0.5, 0.3, 0.7, 0.2, 0.4])
        self.assertEqual(days, 5)
        self.assertEqual(direction, "up")

    def test_streak_caindo(self):
        """3 valores negativos no final, com positivo antes."""
        days, direction = _streak([0.5, 0.3, -0.2, -0.5, -0.1])
        self.assertEqual(days, 3)
        self.assertEqual(direction, "down")

    def test_streak_misto(self):
        """Alternância — streak deve ser apenas o último trecho."""
        days, direction = _streak([0.5, -0.3, 0.7, -0.2, 0.4])
        self.assertEqual(days, 1)
        self.assertEqual(direction, "up")

    def test_streak_estavel(self):
        """Valores dentro da deadband (±0.01) — deve ser stable."""
        days, direction = _streak([0.005, -0.003, 0.001])
        self.assertEqual(days, 3)
        self.assertEqual(direction, "stable")

    def test_streak_vazio(self):
        """Lista vazia retorna (0, 'stable')."""
        days, direction = _streak([])
        self.assertEqual(days, 0)
        self.assertEqual(direction, "stable")


# ── Testes: _accumulated_change() ────────────────────────────────

class TestAccumulatedChange(unittest.TestCase):
    """Testa o cálculo de variação acumulada."""

    def test_subida(self):
        """100 → 110 = +10%."""
        result = _accumulated_change([100.0, 105.0, 110.0])
        self.assertAlmostEqual(result, 10.0, places=2)

    def test_queda(self):
        """100 → 90 = -10%."""
        result = _accumulated_change([100.0, 95.0, 90.0])
        self.assertAlmostEqual(result, -10.0, places=2)

    def test_sem_mudanca(self):
        """100 → 100 = 0%."""
        result = _accumulated_change([100.0, 105.0, 100.0])
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_lista_curta(self):
        """Lista com menos de 2 elementos retorna 0."""
        self.assertEqual(_accumulated_change([100.0]), 0.0)
        self.assertEqual(_accumulated_change([]), 0.0)

    def test_zero_inicial(self):
        """Valor inicial zero retorna 0 (evita divisão por zero)."""
        self.assertEqual(_accumulated_change([0, 100.0]), 0.0)


# ── Testes: _volatility() ────────────────────────────────────────

class TestVolatility(unittest.TestCase):
    """Testa o cálculo de volatilidade (desvio padrão)."""

    def test_valores_iguais(self):
        """Todos os valores iguais → volatilidade zero."""
        result = _volatility([1.0, 1.0, 1.0])
        self.assertEqual(result, 0.0)

    def test_valores_variados(self):
        """Verifica cálculo correto do desvio padrão populacional."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        # mean=3, variance=(4+1+0+1+4)/5=2, std=sqrt(2)≈1.4142
        result = _volatility(values)
        self.assertAlmostEqual(result, math.sqrt(2), places=3)

    def test_vazio(self):
        """Lista vazia retorna 0."""
        self.assertEqual(_volatility([]), 0.0)


# ── Testes: build_series() ───────────────────────────────────────

class TestBuildSeries(unittest.TestCase):
    """Testa a montagem de séries temporais a partir de relatórios."""

    def test_serie_completa(self):
        """Deve criar uma série para cada moeda presente nos relatórios."""
        series = build_series(SAMPLE_REPORTS)
        self.assertIn("BRL", series)
        self.assertIn("EUR", series)
        self.assertEqual(len(series["BRL"]), 7)
        self.assertEqual(len(series["EUR"]), 7)

    def test_dados_corretos(self):
        """Os pontos de dados devem ter date, rate e variation_pct."""
        series = build_series(SAMPLE_REPORTS)
        first = series["BRL"][0]
        self.assertEqual(first["date"], "2024-03-04T12:00:00Z")
        self.assertEqual(first["rate"], 4.90)
        self.assertEqual(first["variation_pct"], 0.5)

    def test_reports_vazios(self):
        """Lista vazia de relatórios retorna séries vazias."""
        series = build_series([])
        self.assertEqual(series, {})

    def test_report_sem_variations(self):
        """Relatório sem a chave 'variations' é ignorado sem erro."""
        series = build_series([{"generated_at": "2024-01-01"}])
        self.assertEqual(series, {})


# ── Testes: calculate_trend() ────────────────────────────────────

class TestCalculateTrend(unittest.TestCase):
    """Testa o cálculo de tendência para uma moeda individual."""

    def setUp(self):
        """Monta séries a partir dos dados de exemplo."""
        self.series = build_series(SAMPLE_REPORTS)

    def test_brl_rising(self):
        """BRL subiu 7 dias seguidos — sinal deve ser RISING."""
        trend = calculate_trend("BRL", self.series["BRL"], sma_period=3)
        self.assertEqual(trend["currency"], "BRL")
        self.assertEqual(trend["data_points"], 7)
        self.assertEqual(trend["streak_direction"], "up")
        self.assertGreaterEqual(trend["streak_days"], 3)
        self.assertEqual(trend["trend_signal"], "RISING")
        self.assertGreater(trend["accumulated_change_pct"], 0)
        self.assertIsNotNone(trend["sma"])
        self.assertEqual(trend["sma_period"], 3)
        self.assertEqual(len(trend["daily_variations"]), 7)

    def test_eur_sideways(self):
        """EUR oscila — sinal deve ser SIDEWAYS."""
        trend = calculate_trend("EUR", self.series["EUR"], sma_period=3)
        self.assertEqual(trend["trend_signal"], "SIDEWAYS")

    def test_falling_trend(self):
        """JPY em queda por 5 dias — sinal deve ser FALLING."""
        series = build_series(FALLING_REPORTS)
        trend = calculate_trend("JPY", series["JPY"], sma_period=3)
        self.assertEqual(trend["streak_direction"], "down")
        self.assertGreaterEqual(trend["streak_days"], 3)
        self.assertEqual(trend["trend_signal"], "FALLING")
        self.assertLess(trend["accumulated_change_pct"], 0)

    def test_sma_period_respected(self):
        """Período da SMA customizado deve funcionar."""
        trend = calculate_trend("BRL", self.series["BRL"], sma_period=5)
        self.assertEqual(trend["sma_period"], 5)


# ── Testes: analyze_trends() ─────────────────────────────────────

class TestAnalyzeTrends(unittest.TestCase):
    """Testa a função principal de análise de tendências."""

    def test_com_historico(self):
        """Com relatórios pré-carregados, deve retornar resultado completo."""
        result = analyze_trends(days=7, history=SAMPLE_REPORTS)
        self.assertEqual(result["window_days"], 7)
        self.assertEqual(result["reports_found"], 7)
        self.assertIn("BRL", result["trends"])
        self.assertIn("EUR", result["trends"])

    def test_highlights_brl(self):
        """BRL com streak longa deve aparecer nos highlights."""
        result = analyze_trends(days=7, history=SAMPLE_REPORTS)
        highlight_currencies = [h["currency"] for h in result["highlights"]]
        self.assertIn("BRL", highlight_currencies)

    def test_highlights_ordenados(self):
        """Highlights devem estar ordenados por variação acumulada absoluta."""
        result = analyze_trends(days=7, history=SAMPLE_REPORTS)
        if len(result["highlights"]) >= 2:
            for i in range(len(result["highlights"]) - 1):
                self.assertGreaterEqual(
                    abs(result["highlights"][i]["accumulated_pct"]),
                    abs(result["highlights"][i + 1]["accumulated_pct"]),
                )

    def test_historico_vazio(self):
        """Sem relatórios disponíveis, retorna estrutura vazia mas válida."""
        result = analyze_trends(days=7, history=[])
        self.assertEqual(result["reports_found"], 0)
        self.assertEqual(result["trends"], {})
        self.assertEqual(result["highlights"], [])

    def test_sma_period_passado(self):
        """Parâmetro sma_period deve propagar para cada tendência."""
        result = analyze_trends(days=7, history=SAMPLE_REPORTS, sma_period=5)
        for trend in result["trends"].values():
            self.assertEqual(trend["sma_period"], 5)

    def test_falling_highlights(self):
        """JPY em queda deve aparecer nos highlights com sinal correto."""
        result = analyze_trends(days=5, history=FALLING_REPORTS)
        highlight_currencies = [h["currency"] for h in result["highlights"]]
        self.assertIn("JPY", highlight_currencies)
        jpy_hl = [h for h in result["highlights"] if h["currency"] == "JPY"][0]
        self.assertEqual(jpy_hl["signal"], "FALLING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
