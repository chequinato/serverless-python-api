# FX Lambda — Processador de Cotações de Câmbio

Uma AWS Lambda que roda diariamente, busca cotações de câmbio em duas APIs externas, calcula variações percentuais entre hoje e ontem, gera alertas automáticos e salva o relatório no S3 — com toda a infraestrutura provisionada via Terraform.

> **Princípio central do projeto:** separação de responsabilidades. Cada arquivo faz **uma coisa só**, entrega o resultado pro próximo, e nenhum precisa saber como o outro funciona por dentro — como uma linha de montagem.

---

## Índice

- [Fluxo geral](#fluxo-geral)
- [Arquivos e responsabilidades](#arquivos-e-responsabilidades)
- [Como os arquivos se comunicam](#como-os-arquivos-se-comunicam)
- [Detalhamento por arquivo](#detalhamento-por-arquivo)
- [API de consulta](#api-de-consulta)
- [Infraestrutura AWS](#infraestrutura-aws)
- [Conceitos aplicados](#conceitos-aplicados)
- [Ordem sugerida para reproduzir do zero](#ordem-sugerida-para-reproduzir-do-zero)

---

## Fluxo geral

**Quem dispara:** todo dia às 08h UTC, o **EventBridge** aciona a Lambda automaticamente — sem isso, o código nunca roda sozinho.

```
1. Lambda acorda
2. Busca a chave de API no Secrets Manager (descriptografada via KMS)
3. Chama a API 1 → taxas de câmbio de hoje
4. Chama a API 2 → taxas de câmbio de ontem
5. Processa os dados: calcula variações, detecta alertas, monta relatório
6. Salva o relatório (JSON) no S3
7. Retorna resposta de sucesso ou erro
8. Logs de tudo vão automaticamente para o CloudWatch
```

**Resumo em uma linha:**
`Alarme → Busca credencial → Busca dados → Processa → Salva → Loga`

**O outro lado:** esse fluxo só escreve. Quem quer **ler** o resultado passa pela [API de consulta](#api-de-consulta) — uma segunda Lambda, disparada por API Gateway em vez de EventBridge, que só lê o que já está no S3 e nunca chama as APIs externas.

---

## Arquivos e responsabilidades

Pense em cada arquivo como um departamento de uma empresa. O `lambda_function.py` é o **gerente geral**: não faz nada sozinho, só coordena e delega na ordem certa.

| Arquivo | Departamento | O que faz |
|---|---|---|
| `lambda_function.py` | Gerência geral | Coordena tudo, na ordem certa |
| `secrets.py` | Segurança / RH | Busca e entrega credenciais |
| `api_client.py` | Compras / Coleta | Fala com as APIs externas |
| `processor.py` | Análise | Processa e calcula os dados |
| `analytics.py` | Análise avançada | Risco, anomalias, cross-rates, sentimento |
| `trends.py` | Histórico | Tendência multi-day: média móvel, streaks, volatilidade |
| `storage.py` | Arquivo / Depósito | Salva o resultado final |
| `query.py` | Balcão de consulta | Localiza e recorta relatórios já salvos |
| `api_handler.py` | Atendimento | Atende as requisições HTTP do API Gateway |
| `test_*.py` | Controle de qualidade | Garante que os cálculos não erraram |

**Por que separar assim:**
- Se a API mudar → mexe só em `api_client.py`
- Se o bucket S3 mudar → mexe só em `storage.py`
- Dá pra testar `processor.py` sem chamar nenhuma API real

---

## Como os arquivos se comunicam

Não há acoplamento direto — cada arquivo só chama funções e recebe dados de volta.

```
lambda_function.py
│
├── chama → secrets.get_api_key()
│              └── retorna: "abc123xyz"
│
├── chama → api_client.fetch_live_rates("abc123xyz")
│              └── retorna: ExchangeRates(base="USD", rates={EUR: 0.92, BRL: 4.97, ...})
│
├── chama → api_client.fetch_historical_rates("abc123xyz")
│              └── retorna: ExchangeRates(base="USD", rates={EUR: 0.91, BRL: 4.85, ...})
│
├── chama → processor.process(live_rates, historical_rates)
│              └── retorna: FXReport(variations=[...], alerts=["BRL"], summary={...})
│
└── chama → storage.upload_report(report.to_dict())
               └── retorna: "s3://bucket/fx-reports/year=2024/.../report.json"
```

Cada função recebe dados, faz seu trabalho, e devolve dados. O `lambda_function.py` só repassa o resultado de um pro próximo.

---

## Detalhamento por arquivo

### `secrets.py`

**Problema que resolve:** API keys nunca podem ficar hardcoded no código — se o repositório for público (ou vazar), a chave vaza junto.

**Solução:** a chave fica guardada no **Secrets Manager**. Este arquivo sabe onde buscá-la.

**Lógica interna:**
```
Estou rodando na AWS?
  SIM → busca no Secrets Manager (produção)
  NÃO → lê da variável de ambiente (local/dev)
```
A detecção de ambiente é automática — o código nunca precisa ser alterado dependendo de onde vai rodar.

---

### `api_client.py`

**Problema que resolve:** buscar cotações de câmbio de duas fontes diferentes via HTTP.

**Como faz:** monta a URL → faz `GET` → recebe JSON → transforma em objeto Python limpo.

```
URL exemplo:
https://v6.exchangerate-api.com/v6/SUA_CHAVE/latest/USD

Resposta bruta da API:
{
  "base_code": "USD",
  "conversion_rates": { "EUR": 0.92, "BRL": 4.97, "GBP": 0.79 }
}

O que api_client.py entrega ao resto do sistema:
ExchangeRates(base="USD", date="...", rates={"EUR": 0.92, "BRL": 4.97})
```

Essa transformação existe porque o resto do sistema **não deve saber nem se importar** com o formato da API. Se a API mudar o formato de resposta, o ajuste é feito só aqui — `processor.py` nem percebe.

**Tratamento de erros HTTP:**

| Código | Situação | Exceção lançada |
|---|---|---|
| 401 | Chave inválida | `APIAuthError` |
| 429 | Limite de requisições atingido | `APIRateLimitError` |
| 500 | API fora do ar | `APIError` (genérica) |

---

### `processor.py`

**Problema que resolve:** com dois conjuntos de taxas (hoje e ontem) em mãos, o que fazer com eles?

**Lógica principal:**
```
variação % = ((taxa_hoje - taxa_ontem) / taxa_ontem) * 100
```

**Exemplo:**
```
BRL ontem: 4.85
BRL hoje:  4.97
Variação:  ((4.97 - 4.85) / 4.85) * 100 = +2.47%
Alerta?    SIM (acima de 1.5%)
Direção?   "up"
```

- **Entradas:** dois objetos `ExchangeRates`
- **Saída:** um objeto `FXReport`, com variações, alertas e resumo estatístico

Este é o arquivo **mais testável** do projeto: não chama nenhuma API, não acessa a AWS. Recebe dados, calcula, devolve dados — Python puro.

---

### `storage.py`

**Problema que resolve:** persistir o relatório em um lugar acessível e seguro.

**O que faz:**
- Converte o `FXReport` para JSON
- Monta o caminho (key) no S3 com particionamento por data:
  ```
  fx-reports/year=2024/month=03/day=10/report_USD_20240310T080000Z.json
  ```
- Faz o upload com criptografia **SSE-KMS** ativada
- Em modo local: salva em arquivo `.json` na pasta `output/`

**Por que esse formato de path:** é o padrão **Hive-style**, usado em data lakes. Permite que ferramentas como Athena e Glue leiam os dados diretamente com SQL:
```sql
SELECT * FROM fx_reports WHERE year='2024' AND month='03'
```

---

### `lambda_function.py`

**Problema que resolve:** quem chama o quê, em que ordem, e o que fazer se der erro.

É o **único arquivo que a AWS conhece de fato** — é o entry point configurado no console/Terraform. Importa todos os outros módulos e define a ordem de execução.

**Estrutura interna (pseudo-código):**
```
def lambda_handler(event, context):

    tenta → buscar api_key
    se falhar → retorna erro 500

    tenta → buscar taxas ao vivo
    se chave inválida → retorna erro 401
    se rate limit → retorna erro 429
    se API fora → retorna erro 502

    tenta → buscar taxas históricas
    se falhar → retorna erro 502

    processa os dados

    salva no S3
    (se falhar, loga mas não cancela tudo)

    retorna 200 com resumo do relatório
```

---

### `test_processor.py`

**Problema que resolve:** garantir que `processor.py` está calculando certo.

Não é opcional — é parte do projeto. Testes existem para permitir mudar o código sem medo de quebrar algo.

**Como funciona:**
1. Cria dados falsos (taxas de ontem e hoje inventadas)
2. Chama as funções do `processor.py` com esses dados
3. Verifica se o resultado é o esperado

**Exemplo de teste:**
```
BRL ontem: 4.85 | BRL hoje: 4.97
Variação esperada: +2.47%
Alerta esperado: True (acima de 1.5%)
```

---

## API de consulta

Até aqui o projeto só escrevia: a Lambda acordava às 08h, gerava o relatório e deixava no S3. Para ler, alguém tinha que abrir o bucket na mão.

A API de consulta resolve isso — e a decisão central dela é **ser uma segunda Lambda, separada**:

```
                     ┌─────────────────────┐
  EventBridge ─────► │  fx_processor       │ ─────► S3 (escreve)
  (1x por dia)       │  lambda_function.py │        fx-reports/...
                     └─────────────────────┘             │
                                                          │ lê
                     ┌─────────────────────┐             │
  API Gateway ─────► │  fx_query_api       │ ◄───────────┘
  (sob demanda)      │  api_handler.py     │
                     └─────────────────────┘
```

**Por que não reaproveitar a mesma Lambda:**

| Motivo | Explicação |
|---|---|
| **Cota** | Cada execução da Lambda agendada gasta 2 requisições das APIs externas. O plano gratuito é 1.500/mês. Se cada visita ao endpoint rodasse o fluxo completo, a cota acabaria em dias. |
| **Permissão** | A Role da API não tem acesso ao Secrets Manager nem permissão de escrita. Se a API for comprometida, dá para ler cotações públicas — e nada mais. |
| **Latência** | Ler um JSON do S3 responde em milissegundos. Chamar duas APIs externas leva segundos e pode falhar por causa de terceiros. |

### Endpoints

| Endpoint | O que devolve |
|---|---|
| `GET /health` | Status da API e ambiente detectado. Não toca no S3. |
| `GET /reports/latest` | Relatório mais recente, completo |
| `GET /reports/latest?currency=BRL` | Só os dados daquela moeda, com o nível de risco |
| `GET /alerts` | Moedas que estouraram o limiar de 1,5%, com variação e risco |
| `GET /trends?days=7` | Tendência multi-day: média móvel, streaks, volatilidade |

```bash
# A URL base sai no output do Terraform (api_base_url)
curl "$API/alerts"
```

```json
{
  "base_currency": "USD",
  "generated_at": "2026-10-18T08:00:00+00:00",
  "threshold_pct": 1.5,
  "alerts_count": 1,
  "alerts": [
    {
      "currency": "BRL",
      "variation_pct": 3.8462,
      "direction": "up",
      "rate_now": 5.4,
      "risk_level": "CRITICAL"
    }
  ],
  "market_sentiment": "BEARISH"
}
```

### Códigos de resposta

| Código | Quando acontece |
|---|---|
| `200` | Consulta atendida. Inclui "nenhum alerta hoje" — lista vazia é sucesso, não erro. |
| `400` | Parâmetro inválido: `?days=sete`, `?days=99`, `?currency=REAL` |
| `404` | Rota inexistente, bucket sem relatório, ou moeda fora do relatório |
| `500` | Erro inesperado. O motivo vai para o CloudWatch; quem chamou nunca recebe stack trace. |

### Decisões de projeto da API

**HTTP API, não REST API.** São ~7 recursos no Terraform em vez de ~20, custa cerca de 1/3 do preço e já traz CORS nativo. REST API só valeria por recursos que o projeto não usa (API keys, usage plans, transformação de request).

**Rotas declaradas uma a uma, sem `$default`.** Caminho desconhecido é rejeitado na borda e a Lambda nem é invocada — URL errada e varredura de robô não geram custo.

**Limite de 30 dias no `?days`.** Cada dia da janela é uma chamada `list_objects_v2` no S3. Sem o limite, uma janela de 365 dias estouraria o timeout da Lambda.

---

## Infraestrutura AWS

O código Python é o **cérebro**. A AWS é o **corpo** — fornece tudo que o cérebro precisa para funcionar.

| Serviço AWS | Por que existe neste projeto |
|---|---|
| **Lambda** | Roda o código sem gerenciar servidor — duas delas: processamento e consulta |
| **EventBridge** | Acorda a Lambda de processamento todo dia no horário certo |
| **API Gateway** | Expõe a Lambda de consulta por HTTP, sob demanda |
| **Secrets Manager** | Guarda a chave de API com segurança |
| **KMS** | Criptografa o secret e os arquivos no S3 |
| **S3** | Armazena os relatórios gerados |
| **IAM Role** | Define o que cada Lambda tem permissão de fazer |
| **CloudWatch** | Guarda os logs automaticamente |

### Regra de ouro da IAM

> A Lambda só pode fazer o que a IAM Role dela permite. Sem permissão explícita, a AWS nega — sempre.

São **duas Roles**, uma por Lambda, cada uma com o mínimo do seu papel.

**Role da Lambda de processamento** (`fx_lambda_role`):
- `secretsmanager:GetSecretValue` — buscar a chave
- `kms:Decrypt` — descriptografar o secret e ler o histórico
- `kms:GenerateDataKey` — criptografar ao salvar no S3
- `s3:PutObject` — salvar o relatório
- `s3:GetObject` + `s3:ListBucket` — ler os relatórios anteriores para a análise de tendência

**Role da Lambda de consulta** (`fx_query_role`):
- `s3:GetObject` — ler o relatório
- `s3:ListBucket` (limitado ao prefixo `fx-reports/*`) — descobrir qual é o mais recente
- `kms:Decrypt` — sem isso o `GetObject` volta `AccessDenied` mesmo com a permissão de S3, porque os objetos estão criptografados com a CMK
- **nada** de Secrets Manager, **nada** de escrita

Esse é o conceito de **least privilege** (mínimo necessário).

---

## Conceitos aplicados

### Python

| Conceito | Onde aparece no projeto |
|---|---|
| Funções e `return` | Todo arquivo tem funções que retornam dados |
| Dicionários | Taxas de câmbio são `dict {moeda: valor}` |
| Dataclasses | `ExchangeRates` e `FXReport` |
| `try/except` | Toda chamada de API tem tratamento de erro |
| Imports entre arquivos | `lambda_function.py` importa todos os outros |
| `os.environ` | Configurações vêm de variáveis de ambiente |
| `json` | APIs retornam JSON; S3 recebe JSON |
| `urllib` | Chamadas HTTP sem libs externas |
| `logging` | Registra o que está acontecendo |

### Design

| Conceito | O que significa aqui |
|---|---|
| Separação de responsabilidades | Cada arquivo tem uma responsabilidade só |
| Funções puras | `processor.py` não depende de nada externo |
| Entry point | `lambda_handler()` é o único ponto de entrada |
| Env vars para config | Nenhum valor fixo no código (sem hardcode) |
| Detecção de ambiente | `secrets.py` age diferente local vs. AWS |

---

## Ordem sugerida para reproduzir do zero

Não comece pelo `lambda_function.py` — ele é o último da lista. A lógica é construir de **dentro pra fora**: o núcleo (processamento) primeiro, a casca (Lambda/AWS) por último.

1. **`processor.py`** — sem dependência nenhuma, 100% Python puro. Escreva as funções, rode os testes, valide.
2. **`api_client.py`** — adiciona `urllib` e HTTP. Teste chamando a API real.
3. **`storage.py`** — comece com a simulação local, depois implemente o S3.
4. **`secrets.py`** — comece com a variável de ambiente, depois o Secrets Manager.
5. **`lambda_function.py`** — só depois que os 4 anteriores funcionarem sozinhos.
6. **Testes** — escreva junto com o `processor.py`, não depois.