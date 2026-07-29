import unittest
from processor import calculate_variation

# Teste da função calculate_variation()

class TestCalculateVariation(unittest.TestCase):

    def test_subida(self):
        # seu código aqui com 8 espaços

    def test_descida(self):
        # seu código aqui com 8 espaços

    def test_stable(self):
        # seu código aqui com 8 espaços

    def test_divisao_por_zero(self):
        # seu código aqui com 8 espaços

if __name__ == "__main__":
    unittest.main()

# Teste da função compare_rates()

class TestCompareRates(unittest.TestCase):

    def setUp(self):
        # monta os dois ExchangeRates fictícios aqui

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