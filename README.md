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
                 ├─ build system prompt: SOUL.md
                 │    + "## What you remember about this user" ← rolling summary, if any
                 │    + runtime_context.md + retrieved chunks
                 ├─ history = last 20 messages
                 └─ _call_llm() → Anthropic / OpenRouter / OpenAI
                      └─ response text
  └─ bot.py: reply_text(response)
  └─ _maybe_compact(): if 10+ messages have aged out of the last-20 window
       since the last summary update, fold them into the rolling summary
       via a separate _call_llm() — by default anthropic/claude-haiku-4.5
       on OpenRouter (MEMORY_MODEL/MEMORY_PROVIDER), since fact extraction
       needs far less reasoning than the persona response.

Full conversation history stored forever per chat_id in PostgreSQL (LangGraph checkpointer).
Last 20 messages + rolling summary carried as context on each turn.
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

## Project structure

```
ramit-agent/
├─ .env.example          Template for local config — copy to .env and fill in
├─ src/
│   ├─ bot.py              Telegram bot entry point (long polling)
│   ├─ agent.py            LangGraph agent, LLM routing, conversation history
│   ├─ tools.py            Semantic search over the knowledge index
│   ├─ invite_system.py    Invite code auth — runtime DB ops
│   └─ admin_cli.py        Admin CLI: generate codes, list users, revoke, remove
├─ persona/
│   └─ SOUL.md             System prompt — Ramit's persona, frameworks, and rules
├─ knowledge/
│   ├─ sources/            Raw source files (gitignored)
│   ├─ output/             Pipeline outputs including evidence_index.jsonl (gitignored)
│   ├─ config/
│   │   └─ ramit-sethi.yaml   Pipeline configuration (tiers, chunking, models)
│   ├─ prompts/            LLM prompts for pipeline stages
│   ├─ src/                Pipeline stage modules (ingest, chunk, summarize, etc.)
│   └─ run_pipeline.py     Pipeline CLI entry point
├─ Dockerfile              Container image for Railway deployment
├─ .dockerignore           Excludes sources, pipeline code, secrets from image
├─ .railwayignore          Like .gitignore, but keeps knowledge/output/ for `railway up`
├─ docker-compose.yml      PostgreSQL for local dev (pgvector/pg17)
├─ pyproject.toml          Python package + dependencies
└─ Makefile                Convenience commands
```

---

## Quick start (local)

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

## Running locally vs. deploying to Railway

This is one codebase and one Postgres schema (`authorized_users` + LangGraph's
`checkpoints` tables) — "local" and "Railway" are just two places to run the
same Docker image, pointed at two different Postgres instances.

| | Local | Railway |
|---|---|---|
| Code | `src/bot.py` (same Docker image) | same |
| Postgres | `docker compose` on your machine | Railway-managed Postgres add-on |
| Uptime | only while your process is running — long polling stops if your laptop sleeps | 24/7 |
| Conversation history & invites | stored in your local Postgres | stored in Railway's Postgres — separate DB unless `DATABASE_URL` is shared |

A few things that follow from this:

- **Multi-user / multi-chat support is built into the bot, not Railway.**
  Every Telegram `chat_id` gets its own LangGraph thread in the `checkpoints`
  tables, and `authorized_users` tracks invites. This works identically
  against either Postgres instance.
- **The knowledge/extraction pipeline never runs on Railway.** It's a local,
  occasional batch job (`knowledge/run_pipeline.py`) that produces
  `evidence_index.jsonl` and `runtime_context.md`. Those files are baked into
  the Docker image at build time (see `Dockerfile`) and loaded into memory at
  bot startup — Railway just ships the prebuilt artifacts.
- Local and Railway each have their own Postgres, so conversation history and
  invites don't carry over between them unless you point both at the same
  `DATABASE_URL`.

Railway is used for the always-on deployment because long polling needs the
process running 24/7 and LangGraph checkpoints need persistent Postgres — see
[Design decisions](#design-decisions) for the full rationale.

### One-time Railway setup

```bash
npm install -g @railway/cli
railway login
railway init         # links this repo to a Railway project (railway.toml is optional — Railway auto-detects the Dockerfile)

# Add Postgres add-on in the Railway dashboard — it auto-sets DATABASE_URL

railway variables set \
  TELEGRAM_BOT_TOKEN=<token> \
  ANTHROPIC_API_KEY=<key> \
  CHAT_PROVIDER=anthropic \
  CHAT_MODEL=claude-haiku-4-5-20251001 \
  ADMIN_TELEGRAM_USER_IDS=<your_telegram_user_id>

railway up --no-gitignore
```

### Deploy updates

```bash
railway up --no-gitignore
```

`knowledge/output/` is excluded by `.gitignore` (the pipeline artifacts are
large and rebuilt locally), but the Dockerfile needs it in the build context.
`--no-gitignore` tells `railway up` to use `.railwayignore` instead — same
exclusions as `.gitignore` (secrets, `.venv`, raw sources, etc.) but with
`knowledge/output/` included. Forgetting `--no-gitignore` is the most common
deploy failure: Railway reports `knowledge/output/ramit-sethi/` missing from
the build context.

### Monitor

```bash
railway logs
```

---

## Invite-only access

The bot is invite-only. Unauthorized users get a prompt to request a code. Each code can only be redeemed once.

**Generate codes:**

```bash
# Against your local Postgres (DATABASE_URL from .env)
python -m src.admin_cli --generate 5
# prints 5 codes like: AB3KXJ2L

# Against the Railway-deployed bot's Postgres
DATABASE_URL=<DATABASE_PUBLIC_URL> python -m src.admin_cli --generate 5
```

`admin_cli` connects to whatever `DATABASE_URL` resolves to — by default your
local `.env`. To manage invites/users for the deployed bot, override it with
the Postgres service's `DATABASE_PUBLIC_URL` (Railway dashboard → Postgres →
Variables, or `railway variables --service Postgres`). Its plain
`DATABASE_URL` (`postgres.railway.internal`) only resolves inside Railway's
network, so `railway run` won't work for this — it executes locally, not in
the container. The same `DATABASE_URL=<...>` override works for all commands
below.

Share a code with someone and tell them to DM the bot:
```
/start AB3KXJ2L
```

**Other admin commands:**

```bash
# List all authorized users and redemption dates
python -m src.admin_cli --list-users

# Revoke a code (prevents redemption; doesn't affect already-authorized users)
python -m src.admin_cli --revoke AB3KXJ2L

# Remove a user and wipe their conversation history
python -m src.admin_cli --remove-user 123456789
```

**Admin bypass** — set `ADMIN_TELEGRAM_USER_IDS` to a comma-separated list of Telegram user IDs that skip the invite check entirely. Your own ID should always be in this list.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `CHAT_PROVIDER` | Yes | `anthropic`, `openrouter`, or `openai` |
| `CHAT_MODEL` | Yes | Model ID for the chosen provider |
| `MEMORY_MODEL` | No | Model for the memory-flush/compaction LLM call (default: same as `CHAT_MODEL`) |
| `MEMORY_PROVIDER` | No | Provider for the memory-flush call (default: same as `CHAT_PROVIDER`) |
| `ANTHROPIC_API_KEY` | If using Anthropic | Anthropic API key |
| `OPENROUTER_API_KEY` | If using OpenRouter for `CHAT_PROVIDER` or `MEMORY_PROVIDER` | OpenRouter API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `ADMIN_TELEGRAM_USER_IDS` | No | Comma-separated Telegram user IDs that bypass invite check |
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

## Commands & operations

| Command | What it does |
|---|---|
| `make run-bot` | Start the Telegram bot |
| `make pipeline` | Run the knowledge pipeline |
| `make install` | Install Python dependencies (`pip install -e ".[dev]"`) |
| `make db-up` | Start PostgreSQL via Docker Compose |
| `make db-down` | Stop PostgreSQL |
| `make reset-memory` | Drop LangGraph checkpoint tables (clears all conversation history) |

**Start everything:**
```bash
make db-up
source .venv/bin/activate
python -m src.bot
```

**Stop everything:** `Ctrl+C` to stop the bot, then `make db-down`.

**Reset conversation memory** (drops all per-user history from Postgres): `make reset-memory`.

**Token usage:** The bot does not log token usage at runtime. Check your provider's dashboard — OpenRouter tracks spend and tokens per API key natively.

---

## Design decisions

**OpenRouter as default provider** — env vars control provider and model, so you can swap between deepseek, Claude, GPT-4o, etc. with no code changes. OpenRouter is cheaper than Anthropic direct for high-volume use and gives access to many models under one key.

**LangGraph + PostgreSQL for conversation memory** — persistent checkpointing over in-memory state so conversation history survives bot restarts. Each Telegram `chat_id` maps to its own LangGraph thread, giving full per-user isolation.

**Rolling summary + memory flush for long conversations** — once a chat exceeds 20 messages, older turns are periodically condensed into a running summary (prepended to the system prompt) via a separate LLM call, which by default runs on `anthropic/claude-haiku-4.5` via OpenRouter (configurable via `MEMORY_MODEL`/`MEMORY_PROVIDER`) since fact-extraction needs far less reasoning than the persona response. Full history stays in Postgres. Mirrors OpenClaw's compaction/memory-flush pattern at a much smaller scale.

**Local embeddings (sentence-transformers)** — `all-MiniLM-L6-v2` runs on-device (MPS on Apple Silicon), zero cost per query, no API dependency. Trade-off: ~10s cold start on first run and ~94MB index held in memory.

**Pre-built knowledge artifacts, not built at runtime** — `evidence_index.jsonl` is produced by the pipeline and loaded at startup. The bot has no pipeline dependency at runtime; startup is fast and cheap.

**Retrieval-augmented prompting over fine-tuning** — top-6 semantically matched chunks are injected into the system prompt each turn. Keeps responses grounded in Ramit's actual source material without the cost or inflexibility of fine-tuning a model.

**Long-polling over webhooks** — no reverse proxy or public URL needed for local development. Trade-off: slightly higher message latency versus webhooks in production.

**Invite codes over a user whitelist** — codes can be generated and shared without knowing a user's Telegram ID in advance. Frank generates a batch, hands them out, and revokes individually if needed. An `ADMIN_TELEGRAM_USER_IDS` env var bypasses the check entirely for the owner.

**Railway over other hosting options** — see [Running locally vs. deploying to Railway](#running-locally-vs-deploying-to-railway) for the full rationale (24/7 uptime for long polling + managed Postgres + auto-deploy on push).

**Tier system in the pipeline (primary / secondary / non-canonical)** — sources are classified by authority so the pipeline can weight them accordingly. Only primary and secondary tiers get embedded and returned at retrieval time; non-canonical material is excluded.

**7-stage pipeline with per-stage resumability** — each stage writes its output to disk independently. `--from-stage N` lets you reprocess from any point without re-running expensive LLM stages (summarization, doctrine extraction) unnecessarily.
