#!/usr/bin/env python3
"""
Agent Builder — Willow AI OS

Builds new Willow agents from a domain description.
Fleet writes the profile. AgentBuilder orchestrates.

Usage:
    python agent_builder.py "NASARally" "Community archive agent for scooter rally history" WORKER fleet
    python agent_builder.py --list
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import llm_router, agent_registry
from core.hook_generator import ClaudeCLIHookGenerator

ARTIFACTS_BASE = Path(__file__).parent.parent / "artifacts"


def build_agent(username: str, domain: str, role: str,
                trust_level: str = "WORKER", agent_type: str = "fleet") -> dict:
    """
    Build and register a new Willow agent.

    Steps:
    1. Normalize agent name from domain
    2. Scaffold domain hooks via ClaudeCLIHookGenerator
    3. Use fleet to write AGENT_PROFILE.md
    4. Write profile + builder_meta.json to artifacts/{name}/
    5. Register in agent_registry
    Returns: {name, display_name, trust_level, agent_type, profile_path, hooks, provider, success}
    """
    name = domain.lower().replace(" ", "_").replace("-", "_")
    display_name = domain

    gen = ClaudeCLIHookGenerator()
    gen.generate_domain_hooks(domain)
    hooks = [h.name for h in gen.hooks]
    hooks_text = "\n".join(f"- {h}" for h in hooks)

    profile_prompt = f"""Write an AGENT_PROFILE.md for a Willow AI OS agent.

Agent details:
- Name: {name}
- Display Name: {display_name}
- Type: {agent_type}
- Trust Level: {trust_level}
- Role: {role}
- Domain Hooks:
{hooks_text}

Format (Markdown):
# Agent Profile: {name}

## Identity
- **Name:** {name}
- **Display Name:** {display_name}
- **Type:** {agent_type}
- **Trust Level:** {trust_level}
- **Registered:** {datetime.now(timezone.utc).date()}

## Purpose
[2-3 sentences describing what this agent does in the {domain} domain]

## Capabilities
[Bullet list of 5-7 specific capabilities for {domain}]

## Constraints
- Follows Willow governance (gate.py Dual Commit)
- All actions logged to knowledge DB
- Cannot elevate own trust level
- Trust level {trust_level}: read, search, delegate only

## Domain Hooks
{hooks_text}

## Cultural Principle
[One sentence naming a domain-specific cultural value.]

Output ONLY the Markdown, no explanation."""

    response = llm_router.ask(profile_prompt, preferred_tier="free")
    if not response:
        return {"success": False, "error": "Fleet unavailable — all providers failed"}

    profile_content = response.content
    provider = response.provider

    agent_dir = ARTIFACTS_BASE / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    profile_path = agent_dir / "AGENT_PROFILE.md"
    profile_path.write_text(profile_content, encoding="utf-8")

    meta = {
        "built_by": "agent_builder",
        "requested_by": username,
        "domain": domain,
        "role": role,
        "trust_level": trust_level,
        "agent_type": agent_type,
        "hooks": hooks,
        "provider": provider,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (agent_dir / "builder_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    agent_registry.register_agent(
        username=username,
        name=name,
        display_name=display_name,
        trust_level=trust_level,
        agent_type=agent_type,
        purpose=role,
        capabilities="\n".join(f"- {h}" for h in hooks),
    )

    print(f"  [HOOK:PRES] new_agent_created: {name} ({trust_level}) by agent_builder")

    return {
        "name": name,
        "display_name": display_name,
        "trust_level": trust_level,
        "agent_type": agent_type,
        "profile_path": str(profile_path),
        "hooks": hooks,
        "provider": provider,
        "success": True,
    }


def list_built_agents() -> list:
    """Return agents created by agent_builder (have builder_meta.json)."""
    agents = []
    for meta_path in ARTIFACTS_BASE.glob("*/builder_meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            agents.append({
                "name": meta_path.parent.name,
                "domain": meta.get("domain"),
                "role": meta.get("role"),
                "trust_level": meta.get("trust_level"),
                "provider": meta.get("provider"),
                "timestamp": meta.get("timestamp"),
            })
        except Exception:
            pass
    return agents


def main():
