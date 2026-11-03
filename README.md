# Empório da Música: customer service agent

> 🇧🇷 [Versão em português](README.pt-BR.md)

A prototype of a text-message customer service agent for **Empório da Música**, a musical instrument store in Campo Grande, Brazil. The virtual assistant **Lia** answers questions about the catalog, prices, promotions, orders and store policies. She looks up the operational data (CSVs) and the policy manual (PDF) through *function calling*.

```
Customer: Quanto custa o Takamine GD20? E no PIX?
  🔧 buscar_produtos(termo='takamine gd20')
Lia: O violão Takamine GD20 Dreadnought Natural custa R$ 2.199,00 (ou em até 12x de R$ 183,25 sem juros).
No PIX, ele fica por R$ 2.089,05 (com 5% de desconto). Ele está disponível em estoque! 😉
```
*(Customer: "How much is the Takamine GD20? And with PIX?" Lia gives the price, the PIX price with the 5% discount and the 12 interest-free installments, all computed by the code.)*

> **About languages:** this documentation is in English, as requested for the submission. The agent itself talks to customers in **Brazilian Portuguese**, because the store and its customers are in Brazil; the system prompt, the example conversations and the code identifiers are therefore in Portuguese.

---

## Contents
- [How to run](#how-to-run)
- [Architecture](#architecture)
- [Technical decisions](#technical-decisions)
- [Data handling and inconsistencies found](#data-handling-and-inconsistencies-found)
- [Example conversations](#example-conversations)
- [Known limitations and next steps](#known-limitations-and-next-steps)
- [Use of AI coding assistants](#use-of-ai-coding-assistants)

---

## How to run

### Requirements
- Python **3.10+** (developed and tested with 3.13)
- A free **Gemini API** key: at [aistudio.google.com](https://aistudio.google.com), click *Get API key* and then *Create API key*. No credit card needed.

### Installation
```bash
git clone https://github.com/Niozin101/emporio-musica-agent.git
cd emporio-musica-agent
python -m venv .venv
```

Activate the virtual environment:
- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`. If you get a "running scripts is disabled" error, first run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, which only applies to the current window.
- **Linux/macOS:** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
```

### Configuration
Copy `.env.example` to `.env` and fill in the key:
```
GEMINI_API_KEY=your-key
MODEL=gemini-3.5-flash
MODELOS_RESERVA=gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.1-flash-lite
DATA_REFERENCIA=
```

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini API key (required) |
| `MODEL` | Main model |
| `MODELOS_RESERVA` | Fallback models, used when the main one is out of quota or overloaded (see [Resilience](#4-resilience-on-the-free-tier)) |
| `DATA_REFERENCIA` | Optional. Date used as "today" (`YYYY-MM-DD`) to simulate order deadlines. Empty = current date |

### Usage
```bash
python main.py              # interactive conversation
python main.py --debug      # shows, in real time, the tools the agent calls
python main.py --roteiro examples/roteiros/04_devolucao_arrependimento.txt   # runs a scripted conversation
```
In the interactive mode, `/nova` starts a new conversation and `/sair` quits. Every conversation is saved as Markdown in `logs/conversas/`. Scripted conversations are saved in `examples/`.

### Web interface (optional)
```bash
streamlit run app.py
```
Opens at `http://localhost:8501`: a chat with shortcut cards, sample questions and, under each answer, **"Consultas feitas"** (lookups made), listing the tools Lia called to answer. The color palette was extracted from the design of the store's policy manual (petrol blue `#1A5276`, medium blue `#2E86C1` and amber `#F39C12`), so the interface follows the visual identity of the store's official material. The manual has no brand guide; the colors were inferred from the PDF itself.

---

## Architecture

```
                ┌──────────────────┐
 Customer ─────▶│ main.py / app.py │  CLI (interactive or scripted) / Streamlit web chat
                └────────┬─────────┘
                         ▼
                ┌──────────────┐   system prompt (persona + rules + date/time/store open)
                │ src/agent.py │◀─────────────────────────────────────────▶ Gemini (function calling)
                └──────┬───────┘   step-by-step tool loop, retries, model fallback
                       │ executes the tool the model asked for
          ┌────────────┴─────────────┐
          ▼                          ▼
 ┌─────────────────┐       ┌───────────────────┐
 │  src/tools.py   │       │  src/policies.py  │
 │ buscar_produtos │       │ consultar_politica│ ◀── policy PDF split into 10 sections
 │ detalhes_produto│       └───────────────────┘
 │ consultar_pedido│
 │ listar_promocoes│
 │ registrar_recl. │
 └────────┬────────┘
          ▼
 ┌─────────────────────┐
 │ src/data_loader.py  │ ◀── CSVs: cleaning, joins, final price, inconsistency checks
 └─────────────────────┘
```

The model never touches the data directly: it can only ask for one of the tools we defined, and the code decides what to return.

| File | Responsibility |
|---|---|
| `src/data_loader.py` | Reads the CSVs once (cached) and returns clean data: products with category, specs as dictionaries, availability and promotional price; orders with items, customer and a total check |
| `src/tools.py` | Data tools the agent calls. Every calculation (PIX price, installments, return deadlines, delivery delay) happens here |
| `src/policies.py` | Extracts the PDF manual, splits it into its 10 sections and exposes the `consultar_politica` tool |
| `src/prompts.py` | System prompt for the Lia persona and the dynamic context (date, time, whether the store is open) |
| `src/agent.py` | Step-by-step tool loop with Gemini, conversation history, retries, model fallback and anti-hallucination check |
| `main.py` | Command-line interface and conversation transcripts |
| `app.py` | Web interface (Streamlit), with the tools called visible under each answer |

Tool names, in English: `buscar_produtos` = search products, `detalhes_produto` = product details, `consultar_pedido` = look up an order, `listar_promocoes` = list promotions, `registrar_reclamacao` = file a complaint, `consultar_politica` = look up a policy.

---

## Technical decisions

### 1. Approach: function calling (typed tools)
The agent is an LLM with **well-defined Python tools**. On each message, the model itself decides whether it needs to look up data (products, orders, promotions), look up policies, or just talk.

Alternatives considered:
- **SQL / pandas agent (text-to-SQL):** more flexible, but the model could write wrong queries or expose other customers' data. With closed tools, **identity verification is enforced by code**, not by the prompt.
- **Putting all the data in the prompt:** does not scale as the catalog grows, and invites the model to compute prices and dates.

**Guiding principle: the LLM writes, the code computes.** Discounted price, PIX price, maximum number of installments, return and warranty deadlines, and delivery delays are computed in Python and handed to the model ready to use. The manual says that wrong price information "may constitute false advertising", and LLMs make arithmetic and date mistakes.

### 2. Policies: section index instead of vector RAG
The manual has 8 pages and is already organized into numbered sections. It is extracted with `pypdf` (in *layout* mode, which preserves the tables), stripped of headers and footers, and split into 10 topics (`formas_de_pagamento`, `trocas_e_devolucoes`, etc.). The agent calls `consultar_politica(topico)` when it needs a rule.

- **Deterministic:** it always returns the whole, correct section, with no risk of an irrelevant chunk from a vector search.
- **Traceable:** the logs show exactly which section backed each answer.
- **No extra dependencies** (vector database, embedding model).
- The PDF remains the source of truth: if the manual is updated, just replace the file.

With a manual of hundreds of pages, I would move to hybrid RAG (BM25 + embeddings) with section-based chunking.

### 3. Model and provider: Gemini Flash (free tier)
- **Zero cost and reproducible:** any reviewer can run the project with a free key, no credit card.
- **Good function calling and Portuguese support**, with an official SDK (`google-genai`) that builds each tool's schema from the Python function: its name, docstring and type hints become the description the model reads.
- **Pinned version** (`gemini-3.5-flash`) instead of `*-latest`, so behavior does not change without notice.
- `temperature=0.3`, for consistent answers that still sound natural.

I also considered the Claude API (Anthropic). It would be more stable than a free tier, but requires prepaid credit. Since only `src/agent.py` talks to the provider, switching LLMs only requires changing that file.

### 4. Resilience on the free tier
During development, the free tier showed a **quota of ~20 requests per day per model** and frequent overload (503) and timeout (504) errors. To keep the service from hanging:
1. **30-second timeout** per request.
2. **Retries with backoff** (2s and 5s) for transient errors (429, 500, 503, 504 and network timeouts).
3. **Automatic model fallback:** if the daily quota runs out or the model keeps failing, the conversation continues on the next model in `MODELOS_RESERVA`, **keeping the history**. Each model has its own quota.
4. If everything fails, the customer gets a polite message instead of a technical error.

**A real bug that changed the tool-loop architecture.** The first version used the SDK's automatic mode, which runs the whole cycle ("model asks for a tool → code runs it → model answers") in a single call. While generating the examples, a 503 error **in the middle** of that cycle also discarded the result of the tool that had already run. The retry started over without the data, and the fallback model **answered with made-up prices** (Tagima Dallas for R$ 890 instead of R$ 749). The fix:
- **Tool loop written in `agent.py`**, step by step. Each step is retried on its own, and tool results stay in the conversation, so a failure never erases what was already looked up. This also avoids running a tool with side effects, such as `registrar_reclamacao`, twice.
- **Anti-hallucination check:** if an answer quotes R$ amounts and no tool has been called in the conversation, the agent asks the model to answer again using the tools. It is an extra safeguard that does not depend on the prompt.

Both mechanisms were tested with simulated failures (without spending quota) before going back to the real API.

### 5. Prompt strategy
The system prompt (`src/prompts.py`) follows the guidelines in section 7 of the manual:
- **Persona:** Lia, with an "informal but professional tone, like a friend who knows music", short chat-style messages.
- **Core rule:** "you do NOT know prices, stock, promotions, orders or rules from memory". It includes an explicit map of which tool to use for each kind of question.
- **Presentation rules from the manual:** promotions always show the original price, the discount percentage and the final price; out-of-stock or discontinued products come with alternatives.
- **Scope:** accessories are politely redirected; off-topic requests are declined in one sentence; attempts to change the agent's role are ignored. Lia informs and guides but does not perform operations (returns, exchanges, sales); the only action she takes is filing complaints.
- **Dynamic context computed in code:** date, time and whether the store is **open or closed** (with the reopening time), to follow the rule "outside business hours, tell the customer when the team is back".

### 6. Security and privacy (LGPD, Brazil's data protection law)
- `consultar_pedido` requires the **order number + the registered email or phone number**. The check happens in code.
- "Order does not exist" and "data does not match" return **the same message**, so nobody can find out which orders exist.
- Fields marked `aviso_interno` (internal notice) guide the agent without being shown to the customer.

### 7. Conversation history
- **Within a session:** the agent keeps the history (messages, tool calls and results) in its own list, so the customer can ask follow-up questions ("and with PIX?", "how does the refund work?").
- **Across sessions:** there is no persistent memory. In message-based support each contact is usually independent, and storing conversations would require a retention policy (LGPD). Conversations are **saved as Markdown** in `logs/` for auditing and debugging only.
- Complaints are stored in `logs/reclamacoes.jsonl` with a ticket number, simulating a handoff to the team.

### 8. Interfaces: CLI + Streamlit
The focus of the challenge is the agent. The CLI has an interactive mode, a `--debug` mode (shows the tools called in real time) and a `--roteiro` (script) mode that generates the example conversations reproducibly. The Streamlit web interface reuses the same `AgenteEmporio`, without changing the agent, and makes the central decision of the challenge visible: in each answer, which data or policy tools Lia consulted. The agent and its history live in `st.session_state`, so each browser tab has its own conversation.

---

## Data handling and inconsistencies found

### Operational data (CSVs)
| Issue | Handling |
|---|---|
| `specs` is JSON stored as text, with a different schema per category | Converted to a dictionary; search also looks at its values |
| `discontinued` and `coming_soon` products, and products with zero stock | **Kept**, with a readable status ("out of the catalog", "coming soon", "temporarily out of stock"), so the agent can explain and suggest alternatives, as the manual requires |
| Descriptions of basses, drums and keyboards mention **a different brand/model** (e.g., "Music Man Bass 1X" described as a "Fender Jazz Bass"; "Korg Synth 1" described as an "88-key Roland", while its specs say 61 keys) | Description dropped for these categories; the agent uses only name + specs |
| Duplicate promotions per product and inactive promotions | Only `is_active = 1` counts; if a product has more than one active promotion, the largest discount wins (promotions do not stack) |
| Orders 3 and 20: recorded total ≠ sum of items (R$ 3,450 vs. R$ 3,498; R$ 1,400 vs. R$ 1,488) | `total_confere` column; the agent reports the recorded total and refers questions about it to the team |
| Orders 3 and 14 contain a `coming_soon` product | Kept as is (historical record) |
| Orders 9 and 16 paid in 6 installments below the R$ 80 minimum | Historical record kept; the rule applies to new installment calculations |
| Categories 6, 7 and 8 (woodwinds, brass and orchestral strings) have no products | Search knows the synonyms for these categories and returns "no products", instead of items from another category |
| Customer searches with or without accents, singular or plural ("violao", "violões") | Normalization (lowercase, no accents) + category synonyms + stop words ignored ("de", "com"...) |

### Policy manual (PDF)
| Issue | Interpretation adopted |
|---|---|
| Two phone numbers: (67) 3341-4444 (cover and company data) and (67) 3321-4500 (WhatsApp section) | (67) 3341-4444 as the official one, since it appears in the company records |
| Email with an accent in one place (`contato@empóriodamusica.com.br`) | Treated as a typo; `contato@emporiodamusica.com.br` is used |
| "Up to 3x with no minimum installment (except below R$ 50.00)" | Minimum installment of R$ 50.00 for up to 3x |
| "Over 300 instruments, including woodwinds and orchestral strings", but the catalog has 65 items and no woodwinds | The system's catalog prevails over the institutional text |

These interpretations are returned to the agent along with the manual section (`nota_de_interpretacao`).

### Assumptions
- **Delivery date = estimated delivery date.** The CSV has no actual delivery date, and the return and warranty deadlines count from it.
- **Reference date:** all orders are from 2025 and 2026, so as of today their deadlines have passed. `DATA_REFERENCIA` simulates "today" to demonstrate cases within the deadline.
- **Status `pending`** = awaiting payment confirmation; **`confirmed`** = payment approved and being prepared.
- **Shipping to other cities** is not calculated (it depends on ZIP code, weight and dimensions); the agent gives the shipping options and lead times from the manual.

---

## Example conversations

Generated with `python main.py --roteiro examples/roteiros/<file>.txt`. Each example shows the tools called (🔧) and, at the end, which models generated the answers. The conversations are in Portuguese, the language customers use with Lia. On the day they were generated, the main model's daily quota had run out during testing, so most answers came from the fallback `gemini-3.5-flash-lite`, through the automatic model fallback. Every price, installment and deadline in the examples was checked against the data.

| # | Scenario | What it shows |
|---|---|---|
| [01](examples/01_catalogo_violoes.md) | Acoustic guitars up to R$ 1,000 | Filtered search (category, price, availability), recommendation, PIX price and installments |
| [02](examples/02_preco_e_promocao.md) | Price and promotion | Promotional price, the rule that the PIX discount does not stack with promotions, out-of-stock product with alternatives |
| [03](examples/03_informacoes_e_fora_de_escopo.md) | Store info and out-of-scope questions | Manual lookup (address, hours), accessories, a category the store does not carry, and an off-topic request |
| [04](examples/04_devolucao_arrependimento.md) | **Return within the cooling-off period** | Identity verification, deadline computed in code, and the return policy applied |
| [05](examples/05_pedido_atrasado_reclamacao.md) | **Late order + complaint** | Mismatched data (nothing is revealed), delay detected, complaint filed with a ticket number |

---

## Known limitations and next steps

**Limitations**
- **Gemini free tier:** low quota (~20 requests/day per model) and instability at peak times. The *lite* fallback models answer well but follow the rules less strictly than the main one. Also, on the free tier Google may use the data sent to train its models. The data here is fictional; production would need the paid tier.
- **Holidays** are not considered when computing "store open".
- **Time zone:** uses the machine's clock. In production, I would pin `America/Campo_Grande`.
- **No memory across sessions** (a deliberate choice; see [Conversation history](#7-conversation-history)).
- **Keyword-based product search:** it does not understand vague requests such as "something to play MPB"; in those cases, the model itself translates the intent into filters.
- **No automated evaluation** of the answers; validation was manual, with the scripted conversations.

**With more time, I would build**
1. **Automated evaluation:** a set of questions with expected outcomes (right tool called, right price, off-topic declined), run on every prompt change, possibly with an LLM as a judge.
2. **Unit tests** for the tools (prices, installments, deadlines, identity verification) with `pytest`.
3. **Real WhatsApp integration** (official API) and an HTTP API (FastAPI) in front of the agent.
4. **A real handoff to a human agent**, instead of only filing the complaint.
5. **Observability:** latency, cost and tool-usage metrics per conversation.
6. **A database** (SQLite/Postgres) instead of the CSVs, with real-time stock.
7. **Hybrid RAG** for the manual, if it grows.

---

## Use of AI coding assistants

I used **Claude Code** (Anthropic's desktop app, Claude Opus model) as a pair programmer throughout the project. The workflow was:

1. **Problem analysis:** I shared the challenge, the CSVs and the PDF. Claude summarized the requirements and surfaced the **inconsistencies** listed above (swapped descriptions, mismatched totals, duplicate phone numbers, ambiguous installment rules), which I then validated.
2. **Architecture decisions:** we discussed the alternatives (function calling vs. SQL agent, vector RAG vs. section index, Claude vs. Gemini). Choosing the **free Gemini tier** was my call, so the project costs nothing and the reviewer can reproduce it.
3. **Step-by-step implementation:** Claude Code wrote the code in small steps (data → tools → policies → agent → CLI → web interface). At each step I reviewed it, asked for explanations of the code and the decisions, and made a separate commit, which is reflected in the repository history.
4. **Testing and debugging:** Claude ran real scenarios against the API and found problems we fixed together: numbered lists in the manual mistaken for sections, the agent guessing names from email addresses, hangs caused by free-tier overload (which led to the retry and model-fallback mechanism) and, while generating the examples, **made-up prices** after an API failure. That last case led to rewriting the tool loop and adding the anti-hallucination check. Reviewing every generated conversation, number by number, is what revealed the problem.
5. **Environment setup:** it also guided me through the Windows setup (virtual environment, PowerShell execution policy, `.gitignore`, keeping the API key out of the repository).

**My role:** setting priorities and product choices, reviewing and understanding every part of the code, validating the agent's behavior and managing version control. In my assessment, AI greatly sped up the implementation and the data analysis, but the decisions and the validation required human judgment: for example, interpreting ambiguous rules in the manual and deciding what to do with inconsistent data.
