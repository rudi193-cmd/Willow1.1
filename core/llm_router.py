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
import time
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

# Import health tracking for resilient provider mesh
try:
    from . import provider_health
except ImportError:
    import provider_health

# Import performance tracking for learning optimal routing
try:
    from . import patterns_provider
except ImportError:
    import patterns_provider

# Import fleet feedback for prompt enhancement
try:
    from . import fleet_feedback
except ImportError:
    import fleet_feedback

# Round-robin state
_round_robin_index = {"free": 0, "cheap": 0, "paid": 0}

# Task type inference for performance tracking
def _infer_task_type(prompt: str) -> str:
    """Infer task type from prompt for performance tracking."""
    prompt_lower = prompt.lower()

    # Check for code generation types
    if 'html' in prompt_lower or '<div' in prompt_lower or 'webpage' in prompt_lower:
        return 'html_generation'
    if 'javascript' in prompt_lower or 'function' in prompt_lower and ('js' in prompt_lower or 'script' in prompt_lower):
        return 'javascript_generation'
    if 'css' in prompt_lower or 'style' in prompt_lower and 'color' in prompt_lower:
        return 'css_generation'
    if 'python' in prompt_lower or 'def ' in prompt_lower or 'import ' in prompt_lower:
        return 'python_generation'

    # Check for task types
    if 'refactor' in prompt_lower or 'improve' in prompt_lower or 'optimize' in prompt_lower:
        return 'code_refactoring'
    if 'fix' in prompt_lower or 'debug' in prompt_lower or 'error' in prompt_lower:
        return 'debugging'
    if 'explain' in prompt_lower or 'what does' in prompt_lower or 'how does' in prompt_lower:
        return 'code_explanation'
    if 'summarize' in prompt_lower or 'summary' in prompt_lower:
        return 'text_summarization'
    if 'translate' in prompt_lower:
        return 'translation'
    if 'test' in prompt_lower and ('write' in prompt_lower or 'generate' in prompt_lower):
        return 'test_generation'

    # Default
    return 'general_completion'

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
            "COHERE_API_KEY", "BASETEN_API_KEY", "BASETEN_API_KEY_2",
            "NOVITA_API_KEY", "NOVITA_API_KEY_2", "NOVITA_API_KEY_3",
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
    ProviderConfig("OCI Gemini Flash", "ORACLE_OCI", "https://inference.generativeai.us-phoenix-1.oci.oraclecloud.com", "ocid1.generativeaimodel.oc1.phx.amaaaaaask7dceyaftocxtdymuntmco34k6fosinafgzvp2ixctikldeb2mq", "free"),
    ProviderConfig("OCI Gemini Flash Lite", "ORACLE_OCI", "https://inference.generativeai.us-phoenix-1.oci.oraclecloud.com", "ocid1.generativeaimodel.oc1.phx.amaaaaaask7dceyaou4wnsto3famucn5b4eq7qxowzsbtco5mv5uzf3j37za", "free"),
    ProviderConfig("OCI Gemini Pro", "ORACLE_OCI", "https://inference.generativeai.us-phoenix-1.oci.oraclecloud.com", "ocid1.generativeaimodel.oc1.phx.amaaaaaask7dceyaaxukx6phswip5qkz4oeti6gg3mm4vbahum7bfjwzy3da", "free"),
    ProviderConfig("Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant", "free"),
    ProviderConfig("Cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions", "llama3.1-8b", "free"),
    ProviderConfig("Google Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models/", "gemini-2.5-flash", "free"),
    ProviderConfig("SambaNova", "SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1/chat/completions", "Meta-Llama-3.1-8B-Instruct", "free"),
    # ProviderConfig("Fireworks", "FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1/chat/completions", "accounts/fireworks/models/llama-v3p1-8b-instruct", "free"),  # Disabled - 404 model not found
    # ProviderConfig("Cohere", "COHERE_API_KEY", "https://api.cohere.ai/v1/chat", "command-r", "free"),  # Disabled - 401 auth error
    ProviderConfig("HuggingFace Inference", "HUGGINGFACE_API_KEY", "https://api-inference.huggingface.co/models/", "meta-llama/Meta-Llama-3-8B-Instruct", "free"),
    ProviderConfig("Ollama", "PATH", "http://localhost:11434/api/generate", "llama3.2:latest", "free"),  # LOCAL FALLBACK

    ProviderConfig("Baseten", "BASETEN_API_KEY", "https://inference.baseten.co/v1/chat/completions", "moonshotai/Kimi-K2.5", "free"),
    ProviderConfig("Baseten2", "BASETEN_API_KEY_2", "https://inference.baseten.co/v1/chat/completions", "moonshotai/Kimi-K2.5", "free"),
    ProviderConfig("Novita", "NOVITA_API_KEY", "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.1-8b-instruct", "free"),
    ProviderConfig("Novita2", "NOVITA_API_KEY_2", "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.1-8b-instruct", "free"),
    ProviderConfig("Novita3", "NOVITA_API_KEY_3", "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.1-8b-instruct", "free"),

    # --- TIER 2: CHEAP (High Performance / Low Cost) ---
    # ProviderConfig("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/chat/completions", "deepseek-chat", "cheap"),  # Disabled - requires deposit
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
        # Check OCI by checking config file
        elif p.env_key == "ORACLE_OCI":
            try:
                creds_path = Path("credentials.json")
                if creds_path.exists():
                    with open(creds_path) as f:
                        creds = json.load(f)
                    if creds.get("ORACLE_OCI"):
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
    # Infer task type from original prompt (before enhancement)
    task_type = _infer_task_type(prompt)

    # Enhance prompt with learned corrections from past feedback
    try:
        enhanced_prompt = fleet_feedback.enhance_prompt_with_feedback(prompt, task_type)
    except Exception as e:
        logging.warning(f"Failed to enhance prompt with feedback: {e}")
        enhanced_prompt = prompt  # Fall back to original prompt

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

    # Get provider success rates from health database
    provider_names = [p.name for p in priority]
    health_data = provider_health.get_all_health_status()

    # Calculate success rates and filter bad providers
    provider_scores = {}
    for p in priority:
        health = health_data.get(p.name)

        if not health or health.total_requests == 0:
            # No data yet - give benefit of doubt, neutral score
            provider_scores[p.name] = 0.5
        else:
            success_rate = health.total_successes / health.total_requests

            # Skip providers with catastrophic failure rates
            if success_rate < 0.2 and health.total_requests > 10:
                logging.warning(f"Skipping {p.name} - only {success_rate*100:.1f}% success rate")
                continue

            provider_scores[p.name] = success_rate

    # Filter out blacklisted providers
    healthy_names = provider_health.get_healthy_providers(provider_names)
    healthy_providers = [
        p for p in priority
        if p.name in healthy_names and p.name in provider_scores
    ]

    # Sort by success rate within tier
    # Tier rank (free=0, cheap=1, paid=2) * 10 + (1 - success_rate)
    # This keeps tier priority but sorts by success within tier
    tier_rank = {"free": 0, "cheap": 1, "paid": 2}
    healthy_providers.sort(
        key=lambda p: tier_rank.get(p.tier, 99) * 10 + (1 - provider_scores[p.name])
    )

    # Separate Ollama (local) from cloud providers
    ollama_provider = None
    cloud_providers = []
    for p in healthy_providers:
        if p.name == "Ollama":
            ollama_provider = p
        else:
            cloud_providers.append(p)

    # Prefer cloud providers; only use Ollama if no cloud providers available
    if cloud_providers:
        healthy_providers = cloud_providers
        logging.info(f"Using {len(cloud_providers)} cloud providers (Ollama available as backup)")
    elif ollama_provider:
        healthy_providers = [ollama_provider]
        logging.info("All cloud providers unavailable, using local Ollama")
    else:
        logging.warning("No healthy providers available — all blacklisted")
        return None

    # Try providers in order
    for provider in healthy_providers:
        start_time = time.time()
        try:
            # --- ORACLE OCI ADAPTER (GenericChatRequest for Google/xAI models) ---
            if provider.name.startswith("OCI "):
                try:
                    import oci
                    from oci.generative_ai_inference import GenerativeAiInferenceClient
                    from oci.generative_ai_inference.models import (
                        GenericChatRequest, OnDemandServingMode, ChatDetails,
                        TextContent, UserMessage
                    )

                    creds_path = Path("credentials.json")
                    with open(creds_path) as f:
                        creds = json.load(f)

                    oracle_config = creds.get("ORACLE_OCI", {})
                    compartment_id = oracle_config.get("compartment_id")
                    config_path = oracle_config.get("config_path", str(Path.home() / ".oci" / "config"))

                    oci_config = oci.config.from_file(config_path)
                    client = GenerativeAiInferenceClient(
                        config=oci_config, service_endpoint=provider.base_url
                    )

                    response = client.chat(ChatDetails(
                        compartment_id=compartment_id,
                        serving_mode=OnDemandServingMode(model_id=provider.model),
                        chat_request=GenericChatRequest(
                            messages=[UserMessage(content=[TextContent(text=enhanced_prompt)])],
                            max_tokens=1024
                        )
                    ))

                    response_time_ms = int((time.time() - start_time) * 1000)
                    choice = response.data.chat_response.choices[0]
                    if not choice.message or not choice.message.content:
                        raise ValueError(f"Empty response (finish={choice.finish_reason})")
                    response_text = choice.message.content[0].text

                    provider_health.record_success(provider.name, response_time_ms)
                    patterns_provider.log_provider_performance(
                        provider=provider.name, file_type='text',
                        category=task_type, response_time_ms=response_time_ms, success=True
                    )
                    return RouterResponse(response_text, provider.name, provider.tier)
                except Exception as oci_err:
                    provider_health.record_failure(provider.name, type(oci_err).__name__, str(oci_err)[:200])
                    logging.warning(f"OCI {provider.name} failed: {oci_err} — trying next")
                    continue

            # --- OLLAMA ADAPTER ---
            elif provider.name == "Ollama":
                resp = requests.post(provider.base_url, json={
                    "model": provider.model,
                    "prompt": enhanced_prompt,
                    "stream": False
                }, timeout=120)
                if resp.status_code == 200:
                    response_time_ms = int((time.time() - start_time) * 1000)
                    response_text = resp.json()['response']

                    provider_health.record_success(provider.name, response_time_ms)

                    # Performance tracking (task_type already computed at top of function)
                    patterns_provider.log_provider_performance(
                        provider=provider.name,
                        file_type='text',
                        category=task_type,
                        response_time_ms=response_time_ms,
                        success=True
                    )

                    return RouterResponse(response_text, provider.name, provider.tier)
                else:
                    provider_health.record_failure(provider.name, str(resp.status_code), resp.text[:200])
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

            # --- OPENAI-COMPATIBLE ADAPTER (Groq, DeepSeek, Cerebras, Fireworks, etc) ---
            elif provider.name in ["Groq", "DeepSeek", "Cerebras", "SambaNova", "Together.ai", "OpenRouter", "OpenAI", "Fireworks", "Mistral",
                                    "Baseten", "Baseten2", "Novita", "Novita2", "Novita3"]:
                headers = {"Authorization": f"Bearer {os.environ.get(provider.env_key)}"}
                if provider.name == "OpenRouter":
                    headers["HTTP-Referer"] = "https://github.com/die-namic"

                payload = {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": enhanced_prompt}]
                }

                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    response_time_ms = int((time.time() - start_time) * 1000)
                    response_text = resp.json()['choices'][0]['message']['content']

                    provider_health.record_success(provider.name, response_time_ms)

                    # Performance tracking (task_type already computed at top of function)
                    patterns_provider.log_provider_performance(
                        provider=provider.name,
                        file_type='text',
                        category=task_type,
                        response_time_ms=response_time_ms,
                        success=True
                    )

                    return RouterResponse(response_text, provider.name, provider.tier)
                elif resp.status_code == 429:
                    provider_health.record_failure(provider.name, "429", "Rate limit exceeded")
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    body = resp.text[:200] if resp.text else "no body"
                    provider_health.record_failure(provider.name, str(resp.status_code), body)
                    logging.warning(f"Provider {provider.name} returned {resp.status_code}: {body} — trying next")
                    continue

            # --- GEMINI ADAPTER ---
            elif provider.name == "Google Gemini":
                url = f"{provider.base_url}{provider.model}:generateContent?key={os.environ.get(provider.env_key)}"
                payload = {"contents": [{"parts": [{"text": enhanced_prompt}]}]}
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    response_time_ms = int((time.time() - start_time) * 1000)
                    response_text = resp.json()['candidates'][0]['content']['parts'][0]['text']

                    provider_health.record_success(provider.name, response_time_ms)

                    # Performance tracking (task_type already computed at top of function)
                    patterns_provider.log_provider_performance(
                        provider=provider.name,
                        file_type='text',
                        category=task_type,
                        response_time_ms=response_time_ms,
                        success=True
                    )

                    return RouterResponse(response_text, provider.name, provider.tier)
                elif resp.status_code == 429:
                    provider_health.record_failure(provider.name, "429", "Rate limit exceeded")
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    provider_health.record_failure(provider.name, str(resp.status_code), resp.text[:200])
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
                    "messages": [{"role": "user", "content": enhanced_prompt}]
                }
                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    response_time_ms = int((time.time() - start_time) * 1000)
                    response_text = resp.json()['content'][0]['text']

                    provider_health.record_success(provider.name, response_time_ms)

                    # Performance tracking (task_type already computed at top of function)
                    patterns_provider.log_provider_performance(
                        provider=provider.name,
                        file_type='text',
                        category=task_type,
                        response_time_ms=response_time_ms,
                        success=True
                    )

                    return RouterResponse(response_text, provider.name, provider.tier)
                elif resp.status_code == 429:
                    provider_health.record_failure(provider.name, "429", "Rate limit exceeded")
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    provider_health.record_failure(provider.name, str(resp.status_code), resp.text[:200])
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
                    "message": enhanced_prompt
                }
                resp = requests.post(provider.base_url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    response_time_ms = int((time.time() - start_time) * 1000)
                    response_text = resp.json()['text']

                    provider_health.record_success(provider.name, response_time_ms)

                    # Performance tracking (task_type already computed at top of function)
                    patterns_provider.log_provider_performance(
                        provider=provider.name,
                        file_type='text',
                        category=task_type,
                        response_time_ms=response_time_ms,
                        success=True
                    )

                    return RouterResponse(response_text, provider.name, provider.tier)
                elif resp.status_code == 429:
                    provider_health.record_failure(provider.name, "429", "Rate limit exceeded")
                    logging.warning(f"Provider {provider.name} quota exceeded (429) — trying next")
                    continue
                else:
                    provider_health.record_failure(provider.name, str(resp.status_code), resp.text[:200])
                    logging.warning(f"Provider {provider.name} returned {resp.status_code} — trying next")
                    continue

        except Exception as e:
            provider_health.record_failure(provider.name, type(e).__name__, str(e))
            logging.warning(f"Provider {provider.name} failed: {e}")
            continue

    return None

def ask_with_vision(prompt: str, image_data: str, preferred_tier: str = "free") -> Optional[str]:
    """
    Send a prompt with an image to a vision-capable LLM.

    Args:
        prompt: The text prompt
        image_data: Base64-encoded image data
        preferred_tier: Preferred tier (currently only "free" supports vision via Gemini)

    Returns:
        Response text or None if all providers fail
    """
    # Only Gemini 2.5 Flash supports vision in the free tier
    if not os.environ.get("GEMINI_API_KEY"):
        logging.warning("Vision requires Gemini API key")
        return None

    # Try Gemini Vision
    provider = None
    for p in PROVIDERS:
        if p.name == "Google Gemini":
            provider = p
            break

    if not provider:
        logging.error("Gemini provider not configured")
        return None

    start_time = time.time()

    try:
        # Gemini multimodal API format
        url = f"{provider.base_url}{provider.model}:generateContent?key={os.environ.get(provider.env_key)}"

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",  # Assume JPEG, works for PNG too
                            "data": image_data
                        }
                    }
                ]
            }]
        }

        resp = requests.post(url, json=payload, timeout=60)

        if resp.status_code == 200:
            response_time_ms = int((time.time() - start_time) * 1000)
            response_text = resp.json()['candidates'][0]['content']['parts'][0]['text']

            provider_health.record_success(provider.name, response_time_ms)

            # Performance tracking
            patterns_provider.log_provider_performance(
                provider=provider.name,
                file_type='image',
                category='vision_ocr',
                response_time_ms=response_time_ms,
                success=True
            )

            return response_text
        else:
            provider_health.record_failure(provider.name, str(resp.status_code), resp.text[:200])
            logging.warning(f"Gemini Vision returned {resp.status_code}: {resp.text[:200]}")
            return None

    except Exception as e:
        provider_health.record_failure(provider.name, type(e).__name__, str(e))
        logging.error(f"Gemini Vision failed: {e}")
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