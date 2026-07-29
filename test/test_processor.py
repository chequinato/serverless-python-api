import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import unittest
from api_client import ExchangeRates
from processor import calculate_variation, compare_rates

# Teste da função calculate_variation()

class TestCalculateVariation(unittest.TestCase):

    def test_subida(self):
        pct, direction = calculate_variation(110.0, 100.0)
        self.assertEqual(pct, 10)
        self.assertEqual(direction, "up")

    def test_descida(self):
        pct, direction = calculate_variation(100.0, 110.0)
        self.assertEqual(pct, -9.0909)
        self.assertEqual(direction, "down")

    def test_stable(self):
        pct, direction = calculate_variation(100.0, 100.0)
        self.assertEqual(pct, 0)
        self.assertEqual(direction, "stable")

    def test_divisao_por_zero(self):
        pct, direction = calculate_variation(100.0, 0)
        self.assertEqual(pct, 0.0)
        self.assertEqual(direction, "stable")


# Teste da função compare_rates()

class TestCompareRates(unittest.TestCase):

    def setUp(self):
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
            # GBP ausente propositalmente pro teste de moeda ausente
        )

    def test_moeda_ausente(self):
        compare_function = compare_rates(self.live, self.historical)
        currencies = [v.currency for v in compare_function]
        self.assertNotIn("GBP", currencies)

    def test_fluxo_normal(self):
        compare_function = compare_rates(self.live, self.historical)
        self.assertEqual(len(compare_function), 2)

        currencies = [v.currency for v in compare_function]
        self.assertIn("BRL", currencies)
        self.assertIn("EUR", currencies)

        brl = [v for v in compare_function if v.currency == "BRL"][0]
        self.assertEqual(brl.rate_now, 4.97)
        self.assertEqual(brl.rate_prev, 4.85)
        self.assertEqual(brl.variation_pct, 2.4742)


    def test_ordenacao(self):
        compare_function = compare_rates(self.live, self.historical)
        verify_coin = compare_function[0]
        self.assertEqual(verify_coin.currency, "BRL")
        self.assertEqual(verify_coin.rate_now, 4.97)


if __name__ == "__main__":
    unittest.main()