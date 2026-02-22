# Minimal AIOS - Proof of Dual Commit Governance

**7 files, 323 lines, proves AI proposes + Human ratifies = works**

## What's Included

```
minimal-aios/
├── core/                    (reused - production-ready)
│   ├── gate.py             (1068 lines - gatekeeper validation)
│   ├── state.py            (364 lines - state machine)
│   ├── storage.py          (519 lines - persistence)
│   └── llm_router.py       (751 lines - free fleet routing)
├── aios_minimal.py         (131 lines - intake loop)
├── server_minimal.py       (143 lines - Dual Commit API)
├── agent_minimal.py        (49 lines - Willow agent)
└── data/
    ├── intake/             (drop files here)
    ├── artifacts/          (routed files)
    └── aios.db             (auto-created)
```

## Quick Start

### 1. Start the daemon
```bash
python aios_minimal.py
```

Watches `data/intake/` → classifies via LLM → validates via gate → routes if approved.

### 2. Start the API (separate terminal)
```bash
python server_minimal.py
```

Runs on http://localhost:8421

### 3. Drop a file
```bash
echo "Hello world" > data/intake/test.txt
```

Watch the daemon classify and route it!

## API Endpoints

### POST /validate (AI Proposes)
```json
{
  "mod_type": "external",
  "target": "data/artifacts/documents/file.txt",
  "new_value": "data/intake/file.txt",
  "reason": "Route file to documents"
}
```

### POST /approve (Human Ratifies)
```json
{
  "request_id": "abc123..."
}
```

### POST /reject (Human Rejects)
```json
{
  "request_id": "abc123...",
  "reason": "Not appropriate"
}
```

### GET /health
```json
{
  "status": "ok",
  "sequence": 42,
  "pending_count": 0,
  "checksum": "ΔΣ=42"
}
```

## What Was Cut

❌ 7 extra agents (Jane, Riggs, Ada, Gerald, Steve, etc.)
❌ 12 daemons (governance monitor, coherence scanner, etc.)
❌ Drive sync, Vision API, knowledge base
❌ N2N packets, topology builder, compactor
❌ Multiple databases

## What Remains

✅ Dual Commit governance (gate, state, storage)
✅ Free fleet LLM routing ($0 cost)
✅ Single agent (Willow)
✅ Intake → Process → Route → Govern loop
✅ Full audit trail (hash-chained)
✅ HTTP API for human approval

## Verification

1. Daemon classifies files via LLM
2. Gate validates (AI proposes = PROPOSED state)
3. Human approves via `/approve`
4. Audit log records everything
5. Files route to correct folders

**Proves: AI can't act alone. Human ratification required. Dual Commit works.**

ΔΣ=42
