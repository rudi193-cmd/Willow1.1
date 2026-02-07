"""
LLM ROUTER v2.0 (JSON LOADER)
Routes prompts based on cost (Free -> Cheap -> Paid).
NOW INCLUDES: Native support for loading keys from 'credentials.json'.

Logic:
1. Load keys from credentials.json
2. Check provider availability.
3. If Tier 1 (Free) is available, use it.
4. Else, check Tier 2 (Cheap).
5. Else, check Tier 3 (Paid).
"""

import os
import json
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

# Round-robin state
_round_robin_index = {"free": 0, "cheap": 0, "paid": 0}

# --- 1. KEY LOADER ( The Fix) ---
def load_keys_from_json():
    """
    Reads 'credentials.json' and loads any API keys found into the environment.
    This bridges the gap between the file on your desktop and the script.
    """
    key_path = Path("credentials.json")
    if not key_path.exists():
        return

    try:
        with open(key_path, 'r') as f:
            data = json.load(f)
            
        # Flatten simple JSON structure
        # We look for specific keys expected by the router
        target_keys = [
            "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
            "SAMBANOVA_API_KEY", "HUGGINGFACE_API_KEY", "DEEPSEEK_API_KEY",
            "MISTRAL_API_KEY", "TOGETHER_API_KEY", "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FIREWORKS_API_KEY",
            "COHERE_API_KEY"
        ]
        
        loaded_count = 0
        for k, v in data.items():
            if k.upper() in target_keys:
                os.environ[k.upper()] = str(v)
                loaded_count += 1
                
        # Handle case where keys might be nested under "api_keys" or similar
        if "api_keys" in data and isinstance(data["api_keys"], dict):
            for k, v in data["api_keys"].items():
                if k.upper() in target_keys:
                    os.environ[k.upper()] = str(v)
                    loaded_count += 1

    except Exception as e:
        print(f"[!] Error reading credentials.json: {e}")

# EXECUTE LOADER IMMEDIATELY
load_keys_from_json()

# --- 2. CONFIGURATION ---

@dataclass
class ProviderConfig:
    name: str
    env_key: str
    base_url: str
    model: str
    tier: str  # "free", "cheap", "paid"
    cost_per_m: float = 0.0

PROVIDERS = [
    # --- TIER 1: TRULY FREE (Cloud First, Local Fallback) ---
    # ProviderConfig("Oracle OCI", "ORACLE_OCI", "", "cohere.command-r-16k", "free"),  # Disabled - auth issues
    ProviderConfig("Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant", "free"),
    ProviderConfig("Cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions", "llama3.1-8b", "free"),
    ProviderConfig("Google Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models/", "gemini-2.5-flash", "free"),
    ProviderConfig("SambaNova", "SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1/chat/completions", "Meta-Llama-3.1-8B-Instruct", "free"),
    ProviderConfig("Fireworks", "FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1/chat/completions", "accounts/fireworks/models/llama-v3p1-8b-instruct", "free"),
    ProviderConfig("Cohere", "COHERE_API_KEY", "https://api.cohere.ai/v1/chat", "command-r", "free"),
    ProviderConfig("HuggingFace Inference", "HUGGINGFACE_API_KEY", "https://api-inference.huggingface.co/models/", "meta-llama/Meta-Llama-3-8B-Instruct", "free"),
    ProviderConfig("Ollama", "PATH", "http://localhost:11434/api/generate", "llama3.2:latest", "free"),  # LOCAL FALLBACK

    # --- TIER 2: CHEAP (High Performance / Low Cost) ---
    ProviderConfig("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/chat/completions", "deepseek-chat", "cheap"),
    ProviderConfig("Mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1/chat/completions", "mistral-small", "cheap"),
    ProviderConfig("Together.ai", "TOGETHER_API_KEY", "https://api.together.xyz/v1/chat/completions", "meta-llama/Llama-3-8b-chat-hf", "cheap"),
    ProviderConfig("OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", "microsoft/wizardlm-2-8x22b", "cheap"),

    # --- TIER 3: PAID (SOTA / Heavy Lifting) ---
    ProviderConfig("Anthropic Claude", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages", "claude-3-5-sonnet-20240620", "paid"),
    ProviderConfig("OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions", "gpt-4o", "paid"),
]

@dataclass
class RouterResponse:
    content: str
    provider: str
    tier: str

def get_available_providers() -> Dict[str, List[ProviderConfig]]:
    """Check environment for available API keys."""
    available = {"free": [], "cheap": [], "paid": []}

    for p in PROVIDERS:
        # Check Ollama by testing local endpoint
        if p.name == "Ollama":
            try:
                if requests.get("http://localhost:11434/api/tags", timeout=1).status_code == 200:
                    available[p.tier].append(p)
            except:
                pass
        # Check cloud providers by API key
        elif os.environ.get(p.env_key):
            available[p.tier].append(p)

    return available

def get_provider_count() -> Dict[str, int]:
    """
    Get count of available providers by tier.
    Returns: {"free": N, "cheap": N, "paid": N, "total": N}
    """
    avail = get_available_providers()
    return {
        "free": len(avail["free"]),
        "cheap": len(avail["cheap"]),
        "paid": len(avail["paid"]),
        "total": sum(len(v) for v in avail.values())
    }

def ask(prompt: str, preferred_tier: str = "free", use_round_robin: bool = True) -> Optional[RouterResponse]:
    """
    Route the prompt to a provider.

    Args:
        prompt: The prompt to send
        preferred_tier: "free", "cheap", or "paid"
        use_round_robin: If True, rotates through providers to distribute load

    Returns:
        RouterResponse or None if all providers fail
    """
    available = get_available_providers()

    # Flatten priority list
    priority = []
    if preferred_tier in available:
        tier_providers = available[preferred_tier][:]  # Copy list

        # ROUND-ROBIN: Rotate providers in preferred tier
        if use_round_robin and tier_providers:
            idx = _round_robin_index[preferred_tier] % len(tier_providers)
            # Rotate: move providers before idx to the end
            tier_providers = tier_providers[idx:] + tier_providers[:idx]
            # Update index for next call
            _round_robin_index[preferred_tier] = (idx + 1) % len(tier_providers)

        priority.extend(tier_providers)

    # Fallback cascade to other tiers
    if preferred_tier != "free": priority.extend(available["free"])
    if preferred_tier != "cheap": priority.extend(available["cheap"])
    if preferred_tier != "paid": priority.extend(available["paid"])

    if not priority:
        return None

    # Try providers in order
    for provider in priority:
        try:
            # --- ORACLE OCI ADAPTER ---
            if provider.name == "Oracle OCI":
                try:
                    import oci
                    from oci.generative_ai_inference import GenerativeAiInferenceClient
                    from oci.generative_ai_inference.models import CohereChatRequest, OnDemandServingMode, ChatDetails

                    # Load Oracle config from credentials.json
                    creds_path = Path("credentials.json")
                    with open(creds_path) as f:
                        creds = json.load(f)

                    oracle_config = creds.get("ORACLE_OCI", {})
                    compartment_id = oracle_config.get("compartment_id")
                    endpoint = oracle_config.get("endpoint")
                    config_path = oracle_config.get("config_path", str(Path.home() / ".oci" / "config"))

                    # Initialize OCI config and client
                    config = oci.config.from_file(config_path)
                    client = GenerativeAiInferenceClient(config=config, service_endpoint=endpoint)

                    # Create chat request with proper structure
                    chat_details = ChatDetails(
                        compartment_id=compartment_id,
                        serving_mode=OnDemandServingMode(model_id=provider.model),
                        chat_request=CohereChatRequest(
                            message=prompt,
                            max_tokens=1024,
                            temperature=0.7
                        )
                    )

                    # Call Oracle OCI
                    response = client.chat(chat_details)

                    return RouterResponse(response.data.chat_response.text, provider.name, provider.tier)
                except Exception as oci_err:
                    logging.warning(f"Oracle OCI failed: {oci_err} — trying next")
                    continue

            # --- OLLAMA ADAPTER ---
            elif provider.name == "Ollama":
                resp = requests.post(provider.base_url, json={
                    "model": provider.model,
                    "prompt": prompt,
                    "stream": False
                }, timeout=120)
                if resp.status_code == 200:
                    return RouterResponse(resp.json()['response'], provider.name, provider.tier)
                else:
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

            # --- OPENAI-COMPATIBLE ADAPTER (Groq, DeepSeek, Cerebras, Fireworks, etc) ---
            elif provider.name in ["Groq", "DeepSeek", "Cerebras", "SambaNova", "Together.ai", "OpenRouter", "OpenAI", "Fireworks", "Mistral"]:
                headers = {"Authorization": f"Bearer {os.environ.get(provider.env_key)}"}
                if provider.name == "OpenRouter":
                    headers["HTTP-Referer"] = "https://github.com/die-namic"

                payload = {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": prompt}]
                }

                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return RouterResponse(resp.json()['choices'][0]['message']['content'], provider.name, provider.tier)
                elif resp.status_code == 429:
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    body = resp.text[:200] if resp.text else "no body"
                    logging.warning(f"Provider {provider.name} returned {resp.status_code}: {body} — trying next")
                    continue

            # --- GEMINI ADAPTER ---
            elif provider.name == "Google Gemini":
                url = f"{provider.base_url}{provider.model}:generateContent?key={os.environ.get(provider.env_key)}"
                payload = {"contents": [{"parts": [{"text": prompt}]}]}
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    return RouterResponse(resp.json()['candidates'][0]['content']['parts'][0]['text'], provider.name, provider.tier)
                elif resp.status_code == 429:
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

            # --- ANTHROPIC ADAPTER ---
            elif provider.name == "Anthropic Claude":
                headers = {
                    "x-api-key": os.environ.get(provider.env_key),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": provider.model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}]
                }
                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return RouterResponse(resp.json()['content'][0]['text'], provider.name, provider.tier)
                elif resp.status_code == 429:
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

            # --- COHERE ADAPTER ---
            elif provider.name == "Cohere":
                headers = {
                    "Authorization": f"Bearer {os.environ.get(provider.env_key)}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": provider.model,
                    "message": prompt
                }
                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return RouterResponse(resp.json()['text'], provider.name, provider.tier)
                elif resp.status_code == 429:
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

        except Exception as e:
            logging.warning(f"Provider {provider.name} failed: {e}")
            continue

    return None

def print_status():
    """Print available providers to console."""
    avail = get_available_providers()
    print("\nLLM Router Status")
    print("="*50)
    
    print(f"\nFREE providers ({len(avail['free'])}):")
    for p in avail['free']: print(f"  [OK] {p.name}")
    if not avail['free']: print("  [--] None")
    
    print(f"\nPAID/CHEAP providers ({len(avail['cheap']) + len(avail['paid'])}):")
    for p in avail['cheap'] + avail['paid']: print(f"  [OK] {p.name}")
    if not (avail['cheap'] + avail['paid']): print("  [--] None")
    
    print(f"\nUnavailable ({len(PROVIDERS) - sum(len(x) for x in avail.values())}):")
    active_names = [p.name for sublist in avail.values() for p in sublist]
    for p in PROVIDERS:
        if p.name not in active_names:
            print(f"  [--] {p.name} (set {p.env_key})")
    print("="*50 + "\n")

if __name__ == "__main__":
    # Test Run
    load_keys_from_json()
    print_status()
    # print(ask("What is the capital of France?"))