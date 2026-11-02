# Empório da Música: agente de atendimento

Protótipo de um agente de atendimento por mensagens de texto para a **Empório da Música**, loja de instrumentos musicais em Campo Grande/MS. A assistente virtual **Lia** responde dúvidas sobre catálogo, preços, promoções, pedidos e políticas da loja. Ela consulta os dados operacionais (CSVs) e o manual de políticas (PDF) por meio de *function calling*.

```
Você: Quanto custa o Takamine GD20? E no PIX?
  🔧 buscar_produtos(termo='takamine gd20')
Lia: O violão Takamine GD20 Dreadnought Natural custa R$ 2.199,00 (ou em até 12x de R$ 183,25 sem juros).
No PIX, ele fica por R$ 2.089,05 (com 5% de desconto). Ele está disponível em estoque! 😉
```

---

## Sumário
- [Como rodar](#como-rodar)
- [Arquitetura](#arquitetura)
- [Decisões técnicas](#decisões-técnicas)
- [Tratamento dos dados e inconsistências encontradas](#tratamento-dos-dados-e-inconsistências-encontradas)
- [Exemplos de conversa](#exemplos-de-conversa)
- [Limitações conhecidas e próximos passos](#limitações-conhecidas-e-próximos-passos)
- [Uso de assistentes de código (IA)](#uso-de-assistentes-de-código-ia)

---

## Como rodar

### Pré-requisitos
- Python **3.10+** (desenvolvido e testado com 3.13)
- Uma chave gratuita da **Gemini API**: em [aistudio.google.com](https://aistudio.google.com), clique em *Get API key* e depois em *Create API key*. Não é preciso cartão de crédito.

### Instalação
```bash
git clone https://github.com/Niozin101/emporio-musica-agent.git
cd emporio-musica-agent
python -m venv .venv
```

Ative o ambiente virtual:
- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`. Se aparecer o erro de "execução de scripts desabilitada", rode antes `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, que vale só para a janela atual.
- **Linux/macOS:** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
```

### Configuração
Copie o `.env.example` para `.env` e preencha a chave:
```
GEMINI_API_KEY=sua-chave
MODEL=gemini-3.5-flash
MODELOS_RESERVA=gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.1-flash-lite
DATA_REFERENCIA=
```

| Variável | Para que serve |
|---|---|
| `GEMINI_API_KEY` | Chave da Gemini API (obrigatória) |
| `MODEL` | Modelo principal |
| `MODELOS_RESERVA` | Modelos usados se o principal estiver sem cota ou sobrecarregado (ver [Resiliência](#resiliência-no-plano-gratuito)) |
| `DATA_REFERENCIA` | Opcional. Data usada como "hoje" (`AAAA-MM-DD`) para simular prazos de pedidos. Vazio = data atual |

### Uso
```bash
python main.py              # conversa interativa
python main.py --debug      # mostra, em tempo real, as ferramentas que o agente chama
python main.py --roteiro examples/roteiros/04_devolucao_arrependimento.txt   # roda uma conversa pronta
```
Na conversa interativa, `/nova` recomeça o atendimento e `/sair` encerra. Toda conversa é salva em Markdown em `logs/conversas/`. As conversas de roteiro são salvas em `examples/`.

---

## Arquitetura

```
                ┌──────────────┐
 Cliente ──────▶│   main.py    │  CLI (interativa ou roteiro) + transcrição em Markdown
                └──────┬───────┘
                       ▼
                ┌──────────────┐   system prompt (persona + regras + data/hora/loja aberta)
                │ src/agent.py │──────────────────────────────────────────▶ Gemini (function calling)
                └──────┬───────┘   novas tentativas + troca de modelo
                       │ o modelo decide qual ferramenta chamar
          ┌────────────┴─────────────┐
          ▼                          ▼
 ┌─────────────────┐       ┌───────────────────┐
 │  src/tools.py   │       │  src/policies.py  │
 │ buscar_produtos │       │ consultar_politica│ ◀── PDF do manual dividido em 10 seções
 │ detalhes_produto│       └───────────────────┘
 │ consultar_pedido│
 │ listar_promocoes│
 │ registrar_recl. │
 └────────┬────────┘
          ▼
 ┌─────────────────────┐
 │ src/data_loader.py  │ ◀── CSVs: limpeza, junções, preço final, divergências
 └─────────────────────┘
```

| Arquivo | Responsabilidade |
|---|---|
| `src/data_loader.py` | Lê os CSVs uma vez (cache) e entrega os dados tratados: produtos com categoria, specs em dicionário, disponibilidade e preço com promoção; pedidos com itens, cliente e checagem de total |
| `src/tools.py` | Ferramentas de dados que o agente chama. Todo cálculo (preço no PIX, parcelamento, prazos de troca, atraso) é feito aqui |
| `src/policies.py` | Extrai o manual em PDF, divide nas 10 seções e expõe a ferramenta `consultar_politica` |
| `src/prompts.py` | System prompt da persona Lia e o contexto dinâmico (data, hora, loja aberta ou fechada) |
| `src/agent.py` | Sessão de chat com o Gemini, registro das ferramentas chamadas, novas tentativas e troca de modelo |
| `main.py` | Interface de linha de comando e transcrição das conversas |

---

## Decisões técnicas

### 1. Abordagem: function calling (ferramentas tipadas)
O agente é um LLM com **ferramentas Python bem definidas**. O próprio modelo decide, a cada mensagem, se precisa consultar dados (produtos, pedidos, promoções), consultar políticas ou só conversar.

Alternativas consideradas:
- **Agente de SQL / pandas (text-to-SQL):** mais flexível, mas o modelo poderia gerar consultas erradas ou expor dados de outros clientes. Com ferramentas fechadas, a **verificação de identidade é garantida pelo código**, e não pelo prompt.
- **Colocar todos os dados no prompt:** inviável conforme o catálogo cresce, além de induzir o modelo a calcular preços e datas.

**Princípio adotado: o LLM redige, o código calcula.** Preço com desconto, preço no PIX, número máximo de parcelas, prazos de arrependimento, troca e garantia, e atraso de entrega são calculados em Python e entregues prontos ao modelo. O manual diz que informação de preço errada "pode configurar propaganda enganosa", e LLMs erram aritmética e datas.

### 2. Políticas: índice por seção em vez de RAG vetorial
O manual tem 8 páginas e já vem organizado em seções numeradas. Ele é extraído com `pypdf` (modo *layout*, que preserva as tabelas), limpo de cabeçalhos e rodapés, e dividido em 10 tópicos (`formas_de_pagamento`, `trocas_e_devolucoes`, etc.). O agente chama `consultar_politica(topico)` quando precisa de uma regra.

- **Determinístico:** sempre traz a seção inteira e correta, sem o risco de um *chunk* irrelevante vindo da busca vetorial.
- **Rastreável:** os logs mostram exatamente qual seção embasou cada resposta.
- **Sem dependências extras** (banco vetorial, modelo de embeddings).
- O PDF continua sendo a fonte da verdade: se o manual for atualizado, basta trocar o arquivo.

Com um manual de centenas de páginas, eu migraria para RAG híbrido (BM25 + embeddings) com *chunking* por seção.

### 3. Modelo e provedor: Gemini Flash (plano gratuito)
- **Custo zero e reprodutível:** qualquer avaliador roda o projeto com uma chave gratuita, sem cartão.
- **Bom suporte a function calling e a português**, com SDK oficial (`google-genai`) que executa as ferramentas automaticamente a partir das funções Python. Nome, docstring e tipos viram o schema da ferramenta.
- Versão **fixada** (`gemini-3.5-flash`) em vez de `*-latest`, para o comportamento não mudar sem aviso.
- `temperature=0.3`, para respostas consistentes sem perder a naturalidade.

Também avaliei a API do Claude (Anthropic). Seria mais estável que o plano gratuito, mas exige crédito pré-pago. Como só `src/agent.py` conversa com o provedor, trocar de LLM exige mudar apenas esse arquivo.

### 4. Resiliência no plano gratuito
Durante o desenvolvimento, o plano gratuito mostrou **cota de ~20 requisições por dia por modelo** e erros frequentes de sobrecarga (503) e de tempo esgotado (504). Para o atendimento não travar:
1. **Timeout de 30 segundos** por requisição.
2. **Novas tentativas com espera** (2s e 5s) para erros transitórios (429, 500, 503, 504).
3. **Troca automática de modelo:** se a cota diária acabar ou o modelo continuar falhando, a conversa segue no próximo modelo de `MODELOS_RESERVA`, **levando o histórico**. Cada modelo tem a sua própria cota.
4. Se tudo falhar, o cliente recebe uma mensagem educada, em vez de um erro técnico.

### 5. Estratégia de prompt
O system prompt (`src/prompts.py`) segue as diretrizes da seção 7 do manual:
- **Persona:** Lia, tom "informal mas profissional, como um amigo que entende de música", mensagens curtas em formato de chat.
- **Regra central:** "você NÃO sabe de memória preços, estoque, promoções, pedidos ou regras". Há um mapa explícito de qual ferramenta usar para cada tipo de pergunta.
- **Regras de apresentação do manual:** promoção sempre com preço original, percentual de desconto e preço final; produto sem estoque ou descontinuado vem com alternativas.
- **Escopo:** acessórios são redirecionados com gentileza; assuntos fora da loja são recusados em uma frase; tentativas de mudar o papel do agente são ignoradas.
- **Contexto dinâmico calculado em código:** data, hora e se a loja está **aberta ou fechada** (com o horário de reabertura), para cumprir a regra de "fora do expediente, informar o horário de retorno".

### 6. Segurança e privacidade (LGPD)
- `consultar_pedido` exige **número do pedido + e-mail ou telefone cadastrado**. A verificação acontece no código.
- "Pedido inexistente" e "dados não conferem" retornam **a mesma mensagem**, para não revelar quais pedidos existem.
- Campos marcados como `aviso_interno` orientam o agente sem serem mostrados ao cliente.

### 7. Histórico de conversa
- **Dentro da sessão:** o objeto de chat do SDK mantém o histórico, então o cliente pode fazer perguntas de acompanhamento ("e no PIX?", "como funciona o reembolso?").
- **Entre sessões:** não há memória persistente. Num atendimento por mensagens, cada contato costuma ser independente, e guardar conversas exigiria política de retenção (LGPD). As conversas são **salvas em Markdown** em `logs/` apenas para auditoria e depuração.
- Reclamações são registradas em `logs/reclamacoes.jsonl` com um protocolo, simulando o encaminhamento para a equipe.

### 8. Interface: CLI
O foco do desafio é o agente. A CLI tem modo interativo, modo `--debug` (mostra as ferramentas chamadas em tempo real) e modo `--roteiro`, que gera as conversas de exemplo de forma reprodutível.

---

## Tratamento dos dados e inconsistências encontradas

### Dados operacionais (CSVs)
| Problema | Tratamento |
|---|---|
| `specs` é um JSON em texto, com esquemas diferentes por categoria | Convertido para dicionário; a busca pesquisa nos valores |
| Produtos `discontinued`, `coming_soon` e com estoque 0 | **Mantidos**, com uma `situacao` legível ("Fora de linha", "Em breve", "Temporariamente sem estoque"), para o agente explicar e sugerir alternativas, como pede o manual |
| Descrições de baixos, baterias e teclados citam **outra marca/modelo** (ex.: "Music Man Bass 1X" descrito como "Fender Jazz Bass"; "Korg Synth 1" descrito como "Roland de 88 teclas", mas com 61 teclas nas specs) | Descrição descartada nessas categorias; o agente usa só nome + specs |
| Promoções duplicadas por produto e promoções inativas | Só valem as `is_active = 1`; se houver mais de uma ativa para o mesmo produto, vale a de maior desconto (promoções não são cumulativas) |
| Pedidos 3 e 20: total registrado ≠ soma dos itens (R$ 3.450 vs. R$ 3.498; R$ 1.400 vs. R$ 1.488) | Coluna `total_confere`; o agente informa o total registrado e encaminha questionamentos à equipe |
| Pedidos 3 e 14 contêm um produto `coming_soon` | Mantidos como estão (registro histórico) |
| Pedidos 9 e 16 parcelados em 6x com parcela abaixo do mínimo de R$ 80 | Registro histórico mantido; a regra vale para novos cálculos de parcelamento |
| Categorias 6, 7 e 8 (sopros e cordas orquestrais) sem produtos | A busca conhece os sinônimos dessas categorias e retorna "nenhum produto", em vez de trazer itens de outra categoria |
| Busca do cliente com ou sem acento, no singular ou no plural ("violao", "violões") | Normalização (minúsculas, sem acentos) + sinônimos por categoria + palavras irrelevantes ignoradas ("de", "com"...) |

### Manual de políticas (PDF)
| Problema | Interpretação adotada |
|---|---|
| Dois telefones: (67) 3341-4444 (capa e dados da empresa) e (67) 3321-4500 (seção de WhatsApp) | (67) 3341-4444 como oficial, por aparecer nas fontes cadastrais |
| E-mail com acento em um trecho (`contato@empóriodamusica.com.br`) | Considerado erro de digitação; vale `contato@emporiodamusica.com.br` |
| "Até 3x sem valor mínimo de parcela (exceto abaixo de R$ 50,00)" | Parcela mínima de R$ 50,00 até 3x |
| "Mais de 300 instrumentos, incluindo sopros e cordas orquestrais", mas o catálogo tem 65 itens e nenhum sopro | O catálogo do sistema prevalece sobre o texto institucional |

Essas interpretações são devolvidas ao agente junto com a seção do manual (`nota_de_interpretacao`).

### Suposições
- **Data de recebimento = previsão de entrega.** O CSV não tem a data real de recebimento, e os prazos de arrependimento e garantia contam a partir dela.
- **Data de referência:** todos os pedidos são de 2025 e 2026, então na data atual já passaram dos prazos. `DATA_REFERENCIA` permite simular "hoje" e demonstrar casos dentro do prazo.
- **Status `pending`** = aguardando confirmação do pagamento; **`confirmed`** = pagamento aprovado e em separação.
- **Frete para outras cidades** não é calculado (depende de CEP, peso e dimensões); o agente informa as modalidades e prazos do manual.

---

## Exemplos de conversa

Gerados com `python main.py --roteiro examples/roteiros/<arquivo>.txt`. Cada exemplo mostra as ferramentas chamadas (🔧).

| # | Cenário | O que demonstra |
|---|---|---|
| [01](examples/01_catalogo_violoes.md) | Violões até R$ 1.000 | Busca com filtros (categoria, preço, disponibilidade), recomendação e PIX/parcelamento |
| [02](examples/02_preco_e_promocao.md) | Preço e promoção | Preço com promoção, regra de não cumulatividade do PIX, produto sem estoque com alternativas |
| [03](examples/03_informacoes_e_fora_de_escopo.md) | Informações e fora do escopo | Consulta ao manual (endereço, horário), acessórios, categoria inexistente e assunto fora da loja |
| [04](examples/04_devolucao_arrependimento.md) | **Devolução por arrependimento** | Verificação de identidade, prazo calculado em código e aplicação da política de trocas |
| [05](examples/05_pedido_atrasado_reclamacao.md) | **Pedido atrasado + reclamação** | Dados não conferem (nada é revelado), atraso detectado e reclamação registrada com protocolo |

---

## Limitações conhecidas e próximos passos

**Limitações**
- **Plano gratuito do Gemini:** cota baixa (~20 requisições/dia por modelo) e instabilidade em horários de pico. Os modelos *lite* de reserva respondem bem, mas seguem as regras com menos rigor que o principal. Além disso, no plano gratuito o Google pode usar os dados enviados para treinar modelos. Aqui os dados são fictícios; em produção, seria preciso o plano pago.
- **Feriados** não são considerados no cálculo de "loja aberta".
- **Fuso horário:** usa o relógio da máquina. Em produção, fixaria `America/Campo_Grande`.
- **Sem memória entre sessões** (decisão consciente; ver [Histórico de conversa](#7-histórico-de-conversa)).
- **Busca de produtos por palavras-chave:** não entende perguntas vagas como "algo para tocar MPB"; nesses casos, o próprio modelo traduz a intenção em filtros.
- **Sem testes automatizados** de avaliação das respostas; a validação foi manual, com os roteiros.

**Com mais tempo, eu faria**
1. **Avaliação automatizada:** um conjunto de perguntas com respostas esperadas (ferramenta correta chamada, preço correto, recusa de fora do escopo), rodado a cada mudança de prompt, possivelmente com um LLM como avaliador.
2. **Testes unitários** das ferramentas (preço, parcelamento, prazos, verificação de identidade) com `pytest`.
3. **Integração real com WhatsApp** (API oficial) e uma API HTTP (FastAPI) na frente do agente.
4. **Transferência para atendente humano** de verdade, em vez de só registrar a reclamação.
5. **Observabilidade:** métricas de latência, custo e taxa de uso de cada ferramenta por conversa.
6. **Banco de dados** (SQLite/Postgres) no lugar dos CSVs, com estoque atualizado em tempo real.
7. **RAG híbrido** para o manual, se ele crescer.

---

## Uso de assistentes de código (IA)

Usei o **Claude Code** (app desktop da Anthropic, modelo Claude Opus) como par de programação durante todo o projeto. O fluxo foi:

1. **Análise do problema:** compartilhei o enunciado, os CSVs e o PDF. O Claude resumiu os requisitos e levantou as **inconsistências** listadas acima (descrições trocadas, totais divergentes, telefones duplicados, parcelamento ambíguo), que depois validei.
2. **Decisões de arquitetura:** discutimos as alternativas (function calling vs. agente de SQL, RAG vetorial vs. índice por seção, Claude vs. Gemini). A escolha do **Gemini gratuito** foi minha, para o projeto ter custo zero e ser reprodutível pelo avaliador.
3. **Implementação em etapas:** o código foi escrito pelo Claude Code em passos pequenos (dados → ferramentas → políticas → agente → CLI). Em cada etapa, eu revisei, pedi explicações do código e das decisões, e fiz um commit separado, o que se reflete no histórico do repositório.
4. **Testes e depuração:** o Claude rodou cenários reais contra a API e encontrou problemas que corrigimos juntos: listas numeradas do manual confundidas com seções, o agente deduzindo nomes a partir de e-mails, travamentos por sobrecarga do plano gratuito (o que levou ao mecanismo de novas tentativas e troca de modelo).
5. **Configuração do ambiente:** também me orientou no setup no Windows (ambiente virtual, política de execução do PowerShell, `.gitignore`, chave de API fora do repositório).

**Meu papel:** definir as prioridades e as escolhas de produto, revisar e entender cada parte do código, validar o comportamento do agente e conduzir o versionamento. Na minha avaliação, a IA acelerou muito a implementação e a análise dos dados, mas as decisões e a validação precisaram de julgamento humano: por exemplo, interpretar regras ambíguas do manual e decidir o que fazer com dados inconsistentes.
