"""
test_processor.py — Testes unitários do módulo processor

Testa as funções de cálculo e cruzamento de taxas de câmbio
usando dados fictícios — sem chamadas HTTP nem acesso à AWS.

Como rodar:
  python tests/test_processor.py

Funções testadas:
  calculate_variation → cálculo de variação percentual
  compare_rates       → cruzamento de taxas live e históricas
"""

import sys
import os

# Adiciona src/ ao path para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from api_client import ExchangeRates
from processor import calculate_variation, compare_rates


# ── Testes: calculate_variation() ────────────────────────────────

class TestCalculateVariation(unittest.TestCase):
    """Testa o cálculo de variação percentual entre duas taxas."""

    def test_subida(self):
        """Taxa subiu 10% — deve retornar pct=10 e direction='up'."""
        pct, direction = calculate_variation(110.0, 100.0)
        self.assertEqual(pct, 10)
        self.assertEqual(direction, "up")

    def test_descida(self):
        """Taxa caiu ~9.09% — deve retornar pct negativo e direction='down'."""
        pct, direction = calculate_variation(100.0, 110.0)
        self.assertEqual(pct, -9.0909)
        self.assertEqual(direction, "down")

    def test_stable(self):
        """Taxa sem variação — deve retornar pct=0 e direction='stable'."""
        pct, direction = calculate_variation(100.0, 100.0)
        self.assertEqual(pct, 0)
        self.assertEqual(direction, "stable")

    def test_divisao_por_zero(self):
        """rate_prev=0 não deve lançar exceção — retorna (0.0, 'stable')."""
        pct, direction = calculate_variation(100.0, 0)
        self.assertEqual(pct, 0.0)
        self.assertEqual(direction, "stable")


# ── Testes: compare_rates() ───────────────────────────────────────

class TestCompareRates(unittest.TestCase):
    """
    Testa o cruzamento de taxas live e históricas.

    Fixtures:
      live       → USD base, com EUR, BRL e GBP
      historical → USD base, com EUR e BRL (GBP ausente propositalmente)
    """

    def setUp(self):
        """Monta os objetos ExchangeRates fictícios antes de cada teste."""
        self.live = ExchangeRates(
            base="USD",
            date="2024-03-10",
            source="test",
            rates={"EUR": 0.92, "BRL": 4.97, "GBP": 0.79}
        )
        self.historical = ExchangeRates(
            base="USD",
            date="2024-03-09",
            source="test",
            rates={"EUR": 0.91, "BRL": 4.85}
            # GBP ausente — testado em test_moeda_ausente
        )

    def test_moeda_ausente(self):
        """Moeda presente só no live deve ser ignorada silenciosamente."""
        result     = compare_rates(self.live, self.historical)
        currencies = [v.currency for v in result]
        self.assertNotIn("GBP", currencies)

    def test_fluxo_normal(self):
        """Moedas presentes nos dois devem aparecer no resultado com campos corretos."""
        result     = compare_rates(self.live, self.historical)
        currencies = [v.currency for v in result]

        self.assertEqual(len(result), 2)
        self.assertIn("BRL", currencies)
        self.assertIn("EUR", currencies)

        brl = [v for v in result if v.currency == "BRL"][0]
        self.assertEqual(brl.rate_now, 4.97)
        self.assertEqual(brl.rate_prev, 4.85)
        self.assertEqual(brl.variation_pct, 2.4742)

    def test_ordenacao(self):
        """Lista deve vir ordenada por maior variação absoluta — BRL antes de EUR."""
        result = compare_rates(self.live, self.historical)
        self.assertEqual(result[0].currency, "BRL")
        self.assertEqual(result[0].rate_now, 4.97)


if __name__ == "__main__":
    unittest.main(verbosity=2)
