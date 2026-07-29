import unittest
from processor import calculate_variation

# Teste da função calculate_variation()

class TestCalculateVariation(unittest.TestCase):

    def test_subida(self):
        pct, direction = calculate_variation(110.0, 100.0)
        self.assertEqual(pct, 10)
        self.assertEqual(direction, "up")

    def test_descida(self):
        pct, direction = calculate_variation(100.0, 110.0)
        self.assertEqual(pct, -10)
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

    def test_moeda_ausente(self):
        # chama compare_rates
        # verifica que GBP não está no resultado

    def test_fluxo_normal(self):
        # chama compare_rates
        # verifica que o resultado tem as moedas certas
        # verifica os campos de uma variação específica

    def test_ordenacao(self):
        # chama compare_rates
        # verifica que a primeira moeda tem maior variação absoluta


if __name__ == "__main__":
    unittest.main()