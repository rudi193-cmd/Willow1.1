# Willow 1.1 - Archive

**The active production brain of the Willow system. Single intake point for all content.**

---

## What Willow 1.1 Is

Willow 1.1 is the live codebase — execution, governance, and agent infrastructure. The original Willow repo is the artifact/archive.

- New tasks are created by dumping anything into Willow 1.1
- All execution happens from this codebase
- Governance proposals and approvals live here

**The contract:**

```
You (messy) -> Willow (holds) -> Processing (patterns) -> Routing (homes) -> Delete
```

---

## Core Modules

| Module | Purpose |
|--------|---------|
| `core/llm_router.py` | Free LLM fleet router — 14+ providers, tiered routing |
| `core/credentials.py` | Fernet-encrypted SQLite credential vault |
| `core/gate.py` | Governance gate — enforces Dual Commit flow |
| `core/state.py` | State machine for intake item lifecycle |
| `core/storage.py` | SQLite-backed persistent storage |
| `core/agent_engine.py` | Agent execution engine (7 agents) |
| `core/instance_registry.py` | Agent trust registry (WORKER / OPERATOR / ENGINEER) |
| `core/coherence.py` | Delta-E coherence tracking |
| `core/provider_health.py` | Provider health mesh — rotates out sick providers |
| `core/cost_tracker.py` | Cost tracking — target $0.10/month |
| `cli/kart_cli.py` | Kart CLI for infrastructure tasks |
| `cli/creds_cli.py` | Credential vault CLI |

---

## Quick Start

### LLM Fleet

```python
import sys
sys.path.insert(0, "core")
import llm_router

llm_router.load_keys_from_json()  # loads from credentials.json

response = llm_router.ask("your prompt here", preferred_tier="free")
if response:
    print(response.content)   # response text
    print(response.provider)  # e.g. "gemini-2.5-flash"
    print(response.tier)      # "free" | "cheap" | "paid"
```

### Credential Vault

```bash
# Add a key
python cli/creds_cli.py add GEMINI_API_KEY "your-key-here"

# List all keys
python cli/creds_cli.py list

# Export to credentials.json (for llm_router)
python cli/creds_cli.py export
```

---

## Architecture

### Die-Namic Ring Structure

```
Source Ring  ->  Bridge Ring (Willow intake)  ->  Continuity Ring (SAFE public governance)
  (code)              (new tasks)                      (ratified decisions)
```

### LLM Fleet Tiers

| Tier | Providers | Cost |
|------|-----------|------|
| Free | Gemini 2.5 Flash/Pro (OCI x3), Groq, Cerebras, SambaNova, Baseten (Kimi K2.5 x2), Novita (Llama x3), HuggingFace, Google Gemini | $0 |
| Cheap | Novita Llama with balance | ~$0.001/req |
| Paid | OpenAI, Anthropic | On-demand |
| Local | Ollama (llama3.2, qwen2.5-coder, kart) | $0, unlimited |

Routing order: Free -> Cheap -> Paid. Round-robin within each tier. Health mesh tracks failures.

### Agent Engine

7 registered agents with trust gating:

| Agent | Trust Level | Role |
|-------|-------------|------|
| Willow | OPERATOR | Primary interface |
| Kart | ENGINEER | Infrastructure, orchestration |
| Jane | WORKER | SAFE public face, read-only |
| Riggs | WORKER | Applied reality engineering |
| Ada | OPERATOR | Systems admin |
| Gerald | WORKER | Philosophical advisor |
| Steve | OPERATOR | Prime node, cross-system coordinator |

---

## Governance Flow (Dual Commit)

AI proposes. Human ratifies. Silence is not approval.

```
1. Propose  -> create governance/commits/{id}.pending
2. Ratify   -> human approves via /api/governance/approve
3. Apply    -> python governance/apply_commits.py {id}
4. Push     -> changes go to remote with full audit trail
```

All production code changes go through this flow.

---

## Cost Target

**$0.10/month per human user.**

- 100% free tier for standard workloads
- Ollama local-first for bulk/offline work
- 14 free providers rotating load
- Request caching via `core/request_manager.py`

Actual spend: $0.00-0.05/month.

---

## Privacy

- 96% client-side
- 4% max cloud (auth + model inference fallback)
- No raw user data on servers

---

*Die-Namic System — active codebase and governance. Maintained by Kart (Chief Engineer).*
