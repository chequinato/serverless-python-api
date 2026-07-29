╔══════════════════════════════════════════════════════════════════════════════════╗
║              ARQUITETURA DO PROJETO FX LAMBDA — VISÃO COMPLETA                 ║
╚══════════════════════════════════════════════════════════════════════════════════╝
 
Antes de ver qualquer código, você precisa entender UMA coisa:
um backend bem feito é como uma linha de montagem de fábrica.
Cada estação faz UMA coisa só, passa o resultado pra próxima,
e nenhuma estação sabe (nem precisa saber) como as outras funcionam por dentro.
 
Esse conceito tem nome: SEPARAÇÃO DE RESPONSABILIDADES.
É o princípio mais importante desse projeto.
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 1 — O FLUXO GERAL (do início ao fim)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  QUEM DISPARA?
  ─────────────
  Todo dia às 08h UTC, o EventBridge acorda e chama a Lambda.
  É como um alarme automático. Sem isso, o código nunca roda sozinho.
 
  O QUE ACONTECE?
  ───────────────
 
  [1] Lambda acorda
       │
       ▼
  [2] "Preciso de uma chave de API pra acessar os dados de câmbio.
       Onde está essa chave? No Secrets Manager."
       │
       ▼
  [3] Secrets Manager devolve a chave (descriptografada pelo KMS)
       │
       ▼
  [4] Com a chave em mãos, Lambda chama a API 1 → taxas de hoje
       │
  [5] Lambda chama a API 2 → taxas de ontem
       │
       ▼
  [6] "Tenho os dois conjuntos de dados. Agora preciso processar."
      Calcula variações, detecta alertas, monta relatório
       │
       ▼
  [7] Salva o relatório JSON no S3
       │
       ▼
  [8] Retorna resposta dizendo se deu certo ou não
       │
       ▼
  [9] Logs de tudo isso vão automaticamente pro CloudWatch
 
 
  RESUMO EM UMA LINHA:
  Alarme → Busca credencial → Busca dados → Processa → Salva → Loga
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 2 — OS ARQUIVOS E SUAS RESPONSABILIDADES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  Pensa assim: se o projeto fosse uma empresa, cada arquivo seria um departamento.
  O lambda_function.py é o GERENTE — ele não faz nada sozinho,
  só coordena e delega pra cada departamento na ordem certa.
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  ARQUIVO              DEPARTAMENTO        O QUE FAZ                         │
  ├─────────────────────────────────────────────────────────────────────────────┤
  │  lambda_function.py   Gerente geral       Coordena tudo na ordem certa      │
  │  secrets.py           Segurança/RH        Busca e entrega credenciais       │
  │  api_client.py        Compras/Coleta      Fala com APIs externas            │
  │  processor.py         Analista            Processa e calcula os dados       │
  │  storage.py           Arquivo/Depósito    Salva o resultado final           │
  │  test_processor.py    Controle de qual.   Garante que o analista não errou  │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  Por que separar assim?
  → Se a API mudar, você mexe SÓ no api_client.py
  → Se o bucket S3 mudar, você mexe SÓ no storage.py
  → Você consegue testar o processor.py SEM precisar chamar nenhuma API real
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 3 — COMO OS ARQUIVOS SE COMUNICAM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  Eles se comunicam passando dados de um pro outro via funções.
  Nenhum arquivo "entra" no outro — eles só chamam funções e recebem resultados.
 
  lambda_function.py
  │
  ├── chama → secrets.get_api_key()
  │              └── retorna: "abc123xyz"   (string com a chave)
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
 
  Repara: cada função recebe dados, faz seu trabalho, e devolve dados.
  O lambda_function.py só passa o resultado de um pro próximo. É isso.
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 4 — O QUE CADA ARQUIVO FAZ POR DENTRO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  secrets.py                                                                  │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Você não pode colocar API keys direto no código.
  Se você fizer isso → o código vai pro GitHub → qualquer um vê a chave → problema.
 
  SOLUÇÃO:
  A chave fica guardada no Secrets Manager (cofre da AWS).
  O arquivo secrets.py sabe onde buscar essa chave.
 
  LÓGICA INTERNA:
  ┌──────────────────────────────────────────────────────┐
  │  Estou rodando na AWS?                               │
  │       SIM → busca no Secrets Manager (produção)      │
  │       NÃO → lê da variável de ambiente (local/dev)   │
  └──────────────────────────────────────────────────────┘
 
  Essa decisão é automática. O código detecta o ambiente sozinho.
  Você nunca muda secrets.py dependendo de onde vai rodar.
 
  ─────────────────────────────────────────────────────────────────────────────
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  api_client.py                                                               │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Precisa buscar dados de câmbio de duas fontes diferentes via HTTP.
 
  COMO FAZ:
  Monta a URL → faz GET → recebe JSON → transforma em objeto Python limpo.
 
  URL exemplo:
  https://v6.exchangerate-api.com/v6/SUA_CHAVE/latest/USD
 
  Resposta da API (JSON bruto):
  {
    "base_code": "USD",
    "conversion_rates": { "EUR": 0.92, "BRL": 4.97, "GBP": 0.79 }
  }
 
  O que api_client.py entrega pro resto do sistema:
  ExchangeRates(base="USD", date="...", rates={"EUR": 0.92, "BRL": 4.97})
 
  Por que transformar? Porque o resto do sistema não deve saber nem se importar
  com o formato que a API retorna. Se a API mudar o formato, você ajusta
  SOMENTE aqui, e o processor.py não percebe diferença.
 
  TAMBÉM FAZ: tratamento de erros HTTP
  → 401 = chave inválida  → lança APIAuthError
  → 429 = limite atingido → lança APIRateLimitError
  → 500 = API fora do ar  → lança APIError genérico
 
  ─────────────────────────────────────────────────────────────────────────────
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  processor.py                                                                │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Tenho dois conjuntos de taxas (hoje e ontem). O que faço com isso?
 
  LÓGICA PRINCIPAL:
  Para cada moeda:
    variação % = ((taxa_hoje - taxa_ontem) / taxa_ontem) * 100
 
  Exemplo:
    BRL ontem: 4.85
    BRL hoje:  4.97
    Variação:  ((4.97 - 4.85) / 4.85) * 100 = +2.47%
    Alerta?    SIM (acima de 1.5%)
    Direção?   "up"
 
  ENTRADAS:  dois objetos ExchangeRates
  SAÍDA:     um objeto FXReport com variações, alertas e resumo estatístico
 
  Este é o arquivo MAIS TESTÁVEL do projeto porque:
  → Não chama nenhuma API
  → Não acessa a AWS
  → Recebe dados, calcula, devolve dados. Puro Python.
 
  ─────────────────────────────────────────────────────────────────────────────
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  storage.py                                                                  │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Precisa persistir o relatório em algum lugar acessível e seguro.
 
  O QUE FAZ:
  → Converte o FXReport para JSON
  → Monta o caminho (key) no S3 com particionamento por data:
    fx-reports/year=2024/month=03/day=10/report_USD_20240310T080000Z.json
  → Faz o upload com criptografia SSE-KMS ativada
  → Em modo local: salva em arquivo .json na pasta output/
 
  POR QUE ESSE FORMATO DE PATH?
  É o padrão "Hive-style" usado em data lakes.
  Permite que ferramentas como Athena e Glue leiam os dados com SQL:
  SELECT * FROM fx_reports WHERE year='2024' AND month='03'
 
  ─────────────────────────────────────────────────────────────────────────────
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  lambda_function.py                                                          │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Quem chama o quê, em que ordem, e o que fazer se der erro?
 
  É O ÚNICO ARQUIVO QUE:
  → A AWS conhece (é o entry point configurado no console)
  → Importa todos os outros módulos
  → Define a ordem de execução
  → Decide o que retornar em caso de sucesso ou erro
 
  ESTRUTURA INTERNA (pseudo-código):
  ┌──────────────────────────────────────────────────────┐
  │  def lambda_handler(event, context):                 │
  │                                                      │
  │    tenta → buscar api_key                            │
  │    se falhar → retorna erro 500                      │
  │                                                      │
  │    tenta → buscar taxas ao vivo                      │
  │    se chave inválida → retorna erro 401              │
  │    se rate limit → retorna erro 429                  │
  │    se API fora → retorna erro 502                    │
  │                                                      │
  │    tenta → buscar taxas históricas                   │
  │    se falhar → retorna erro 502                      │
  │                                                      │
  │    processa os dados                                 │
  │                                                      │
  │    salva no S3                                       │
  │    (se falhar, loga mas não cancela tudo)            │
  │                                                      │
  │    retorna 200 com resumo do relatório               │
  └──────────────────────────────────────────────────────┘
 
  ─────────────────────────────────────────────────────────────────────────────
 
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  test_processor.py                                                           │
  └─────────────────────────────────────────────────────────────────────────────┘
 
  PROBLEMA QUE RESOLVE:
  Como garantir que o processor.py está calculando certo?
 
  NÃO É OPCIONAL. É parte do projeto.
  Testes existem pra você poder mudar o código sem medo de quebrar algo.
 
  COMO FUNCIONA:
  → Cria dados falsos (taxas de ontem e hoje inventadas)
  → Chama as funções do processor.py com esses dados
  → Verifica se o resultado é o esperado
 
  Exemplo de teste:
    BRL ontem: 4.85 | BRL hoje: 4.97
    Variação esperada: +2.47%
    Alerta esperado: True (acima de 1.5%)
    → O teste verifica exatamente isso.
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 5 — O PAPEL DA AWS (a infraestrutura por fora do código)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  O código Python é o CÉREBRO.
  A AWS é o CORPO — fornece tudo que o cérebro precisa pra funcionar.
 
  ┌────────────────┬───────────────────────────────────────────────────────────┐
  │  Serviço AWS   │  Por que existe nesse projeto                             │
  ├────────────────┼───────────────────────────────────────────────────────────┤
  │  Lambda        │  Roda o código sem você gerenciar servidor                │
  │  EventBridge   │  Acorda a Lambda todo dia no horário certo                │
  │  Secrets Mgr   │  Guarda a chave de API com segurança                     │
  │  KMS           │  Criptografa o secret e os arquivos no S3                 │
  │  S3            │  Armazena os relatórios gerados                           │
  │  IAM Role      │  Define o que a Lambda tem permissão de fazer             │
  │  CloudWatch    │  Guarda os logs automaticamente                           │
  └────────────────┴───────────────────────────────────────────────────────────┘
 
  REGRA DE OURO DA IAM (mais importante de entender):
  A Lambda só pode fazer o que a IAM Role dela permite.
  Se você não der permissão explícita → a AWS nega. Sempre.
 
  Permissões que a Lambda desse projeto precisa:
  → secretsmanager:GetSecretValue  (pra buscar a chave)
  → kms:Decrypt                    (pra descriptografar o secret)
  → kms:GenerateDataKey            (pra criptografar ao salvar no S3)
  → s3:PutObject                   (pra salvar o relatório)
 
  Nada mais. Esse é o conceito de least privilege (mínimo necessário).
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 6 — O QUE VOCÊ PRECISA ENTENDER ANTES DE REPRODUZIR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  Conceitos Python:
  ┌──────────────────────┬───────────────────────────────────────────────────┐
  │  Conceito            │  Onde aparece no projeto                          │
  ├──────────────────────┼───────────────────────────────────────────────────┤
  │  Funções e return    │  Todo arquivo tem funções que retornam dados       │
  │  Dicionários         │  Taxas de câmbio são dict {moeda: valor}          │
  │  Dataclasses         │  ExchangeRates e FXReport são dataclasses         │
  │  try/except          │  Cada chamada de API tem tratamento de erro       │
  │  Imports entre arqs  │  lambda_function.py importa todos os outros       │
  │  os.environ          │  Configurações vêm de variáveis de ambiente       │
  │  json                │  APIs retornam JSON, S3 recebe JSON               │
  │  urllib              │  Chamadas HTTP sem libs externas                   │
  │  logging             │  Registra o que está acontecendo                  │
  └──────────────────────┴───────────────────────────────────────────────────┘
 
  Conceitos de design:
  ┌──────────────────────┬───────────────────────────────────────────────────┐
  │  Conceito            │  O que significa aqui                             │
  ├──────────────────────┼───────────────────────────────────────────────────┤
  │  Separação de resp.  │  Cada arquivo tem UMA responsabilidade só         │
  │  Funções puras       │  processor.py não depende de nada externo         │
  │  Entry point         │  lambda_handler() é o único ponto de entrada      │
  │  Env vars p/ config  │  Nenhum valor fixo no código (sem hardcode)       │
  │  Detecção de env.    │  secrets.py age diferente local vs AWS            │
  └──────────────────────┴───────────────────────────────────────────────────┘
 
 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PARTE 7 — ORDEM PARA REPRODUZIR DO ZERO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
  Não comece pelo lambda_function.py. Ele é o último.
 
  1. processor.py    → sem dependência nenhuma, 100% Python puro
                        escreva as funções, rode os testes, valide
  2. api_client.py   → adiciona urllib e HTTP. Teste chamando a API real
  3. storage.py      → adiciona a simulação local primeiro, depois o S3
  4. secrets.py      → começa com a variável de ambiente, depois o Secrets Mgr
  5. lambda_function → só depois que os 4 acima funcionam sozinhos
  6. testes          → escreva junto com o processor.py, não depois
 
  A lógica: você constrói de dentro pra fora.
  O núcleo (processamento) primeiro. A casca (Lambda/AWS) por último.
 