# ramit-agent

A Telegram chatbot that channels Ramit Sethi's personal finance philosophy. It diagnoses financial problems as behavioral first, retrieves grounding context from a knowledge base built on his books and podcasts, and responds in his voice via Claude or any OpenAI-compatible provider.

---

## How it works

### Runtime flow

```
User sends Telegram message
  └─ bot.py: handle_message()
       └─ agent.py: chat(graph, chat_id, text)
            └─ LangGraph: _respond() node
                 ├─ tools.py: query_knowledge(text)
                 │    └─ encode query → cosine similarity → top-6 chunks from evidence_index.jsonl
                 ├─ build system prompt: SOUL.md + runtime_context.md + retrieved chunks
                 └─ _call_llm() → Anthropic / OpenRouter / OpenAI
                      └─ response text
  └─ bot.py: reply_text(response)

Conversation history stored per chat_id in PostgreSQL (LangGraph checkpointer)
Last 20 messages carried as context on each turn.
```

### Knowledge pipeline (run once, or when adding new content)

```
knowledge/sources/  ←  drop PDFs, TXTs, DOCXs, podcast transcripts here
  │
  Stage 1: Ingest     parse files, hash, tokenize, save raw text
  Stage 2: Classify   assign tier: primary / secondary / non-canonical
  Stage 3: Chunk      split into ~500-token boundary-aware chunks
  Stage 4: Summarize  per-source LLM extraction (key arguments, voice, archetypes)
  Stage 5: Doctrine   cross-source synthesis → canonical_doctrine.md
  Stage 6: Assemble   compress to runtime_context.md + embed all chunks → evidence_index.jsonl
  Stage 7: Report     token budget stats + upload checklist
  │
  └─ knowledge/output/ramit-sethi/
       ├─ evidence_index.jsonl   (chunks + embeddings — loaded by bot at startup)
       ├─ runtime_context.md     (2500–3500 token always-on persona context)
       ├─ canonical_doctrine.md  (full unified doctrine)
       └─ assembly_report.md     (stats + deployment guide)
```

---

## Quick start

**Prerequisites:** Python 3.11+, Docker

### 1. Clone and configure

```bash
git clone <repo>
cd ramit-agent
cp .env.example .env   # then fill in the values below
```

### 2. Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Start PostgreSQL

```bash
docker compose up -d
```

### 4. Run the bot

```bash
python -m src.bot
# or: make run-bot
```

Wait for `Ramit agent ready.` in the logs — the bot is live.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `CHAT_PROVIDER` | Yes | `anthropic`, `openrouter`, or `openai` |
| `CHAT_MODEL` | Yes | Model ID for the chosen provider |
| `ANTHROPIC_API_KEY` | If using Anthropic | Anthropic API key |
| `OPENROUTER_API_KEY` | If using OpenRouter | OpenRouter API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `KNOWLEDGE_OUTPUT_DIR` | No | Path to knowledge output (default: `knowledge/output/ramit-sethi`) |
| `LLM_PROVIDER` | No | Provider for the knowledge pipeline (default: `anthropic`) |

**Example `.env`:**

```env
TELEGRAM_BOT_TOKEN=your-token-here
DATABASE_URL=postgresql://ramit:ramit@localhost:5432/ramit

CHAT_PROVIDER=openrouter
CHAT_MODEL=deepseek/deepseek-v3.2
OPENROUTER_API_KEY=sk-or-v1-...
```

---

## LLM providers

Switch providers by changing `CHAT_PROVIDER` and `CHAT_MODEL` in `.env`:

| Provider | `CHAT_PROVIDER` | Example `CHAT_MODEL` | Key var |
|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6-20250514` | `ANTHROPIC_API_KEY` |
| OpenRouter | `openrouter` | `deepseek/deepseek-v3.2` | `OPENROUTER_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |

---

## Adding new content (updating the knowledge base)

1. Drop source files into `knowledge/sources/` — supported formats: `.pdf`, `.txt`, `.md`, `.docx`

2. Optionally classify new files in `knowledge/config/ramit-sethi.yaml` by adding filename patterns under `classification_rules` (primary / secondary / non-canonical). Unmatched files fall back to LLM classification.

3. Run the pipeline:

```bash
source .venv/bin/activate
make pipeline

# Resume from a specific stage (e.g. re-embed only):
cd knowledge && python run_pipeline.py --from-stage 6

# Force reprocess even if source hasn't changed:
cd knowledge && python run_pipeline.py --force
```

4. Restart the bot — it loads `evidence_index.jsonl` at startup and needs a restart to pick up new chunks.

---

## Commands

| Command | What it does |
|---|---|
| `make run-bot` | Start the Telegram bot |
| `make pipeline` | Run the knowledge pipeline |
| `make install` | Install Python dependencies (`pip install -e ".[dev]"`) |
| `make db-up` | Start PostgreSQL via Docker Compose |
| `make db-down` | Stop PostgreSQL |
| `make reset-memory` | Drop LangGraph checkpoint tables (clears all conversation history) |

---

## Project structure

```
ramit-agent/
├─ src/
│   ├─ bot.py          Telegram bot entry point (long polling)
│   ├─ agent.py        LangGraph agent, LLM routing, conversation history
│   └─ tools.py        Semantic search over the knowledge index
├─ persona/
│   └─ SOUL.md         System prompt — Ramit's persona, frameworks, and rules
├─ knowledge/
│   ├─ sources/        Raw source files (gitignored)
│   ├─ output/         Pipeline outputs including evidence_index.jsonl (gitignored)
│   ├─ config/
│   │   └─ ramit-sethi.yaml   Pipeline configuration (tiers, chunking, models)
│   ├─ prompts/        LLM prompts for pipeline stages
│   ├─ src/            Pipeline stage modules (ingest, chunk, summarize, etc.)
│   └─ run_pipeline.py Pipeline CLI entry point
├─ docker-compose.yml  PostgreSQL (pgvector/pg17)
├─ pyproject.toml      Python package + dependencies
└─ Makefile            Convenience commands
```

---

## Design decisions

**OpenRouter as default provider** — env vars control provider and model, so you can swap between deepseek, Claude, GPT-4o, etc. with no code changes. OpenRouter is cheaper than Anthropic direct for high-volume use and gives access to many models under one key.

**LangGraph + PostgreSQL for conversation memory** — persistent checkpointing over in-memory state so conversation history survives bot restarts. Each Telegram `chat_id` maps to its own LangGraph thread, giving full per-user isolation.

**Local embeddings (sentence-transformers)** — `all-MiniLM-L6-v2` runs on-device (MPS on Apple Silicon), zero cost per query, no API dependency. Trade-off: ~10s cold start on first run and ~94MB index held in memory.

**Pre-built knowledge artifacts, not built at runtime** — `evidence_index.jsonl` is produced by the pipeline and loaded at startup. The bot has no pipeline dependency at runtime; startup is fast and cheap.

**Retrieval-augmented prompting over fine-tuning** — top-6 semantically matched chunks are injected into the system prompt each turn. Keeps responses grounded in Ramit's actual source material without the cost or inflexibility of fine-tuning a model.

**Long-polling over webhooks** — no reverse proxy or public URL needed for local development. Trade-off: slightly higher message latency versus webhooks in production.

**Tier system in the pipeline (primary / secondary / non-canonical)** — sources are classified by authority so the pipeline can weight them accordingly. Only primary and secondary tiers get embedded and returned at retrieval time; non-canonical material is excluded.

**7-stage pipeline with per-stage resumability** — each stage writes its output to disk independently. `--from-stage N` lets you reprocess from any point without re-running expensive LLM stages (summarization, doctrine extraction) unnecessarily.

---

## Operations

**Stop everything:**
```bash
# Ctrl+C to stop the bot
docker compose down
```

**Start everything:**
```bash
docker compose up -d
source .venv/bin/activate
python -m src.bot
```

**Reset conversation memory** (drops all per-user history from Postgres):
```bash
make reset-memory
```

**Token usage:** The bot does not log token usage at runtime. Check your provider's dashboard — OpenRouter tracks spend and tokens per API key natively.
