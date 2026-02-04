"""
Tunnel Manager — Start cloudflared, capture URL, deploy to Neocities.

Starts a cloudflared tunnel pointing at the local Willow server,
captures the generated URL, verifies the tunnel is actually working,
patches the Neocities pocket Willow with the URL pre-configured,
and deploys it.

Usage:
    python apps/tunnel.py          # start tunnel + deploy
    python apps/tunnel.py --no-deploy  # tunnel only, print URL

GOVERNANCE: Tunnel exposes only 127.0.0.1:8420. No other ports.
"""

import subprocess
import sys
import re
import os
import time
import json
import logging
import tempfile
import threading
from pathlib import Path

import requests

log = logging.getLogger("tunnel")

WILLOW_PORT = 8420
TUNNEL_URL_PATTERN = re.compile(r"(https://[a-z0-9\-]+\.trycloudflare\.com)")


def wait_for_server(port: int = WILLOW_PORT, timeout: int = 60) -> bool:
    """Wait for the local Willow server to respond."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _drain_pipe(pipe, logfile):
    """Drain a pipe to a file continuously so cloudflared doesn't block."""
    try:
        for line in iter(pipe.readline, b""):
            logfile.write(line)
            logfile.flush()
    except Exception:
        pass


def start_tunnel(port: int = WILLOW_PORT, timeout: int = 45) -> tuple:
    """
    Start cloudflared tunnel and capture the public URL.

    Stderr is redirected to a temp file and drained continuously
    so cloudflared doesn't block on a full pipe buffer.

    Returns:
        (url: str, process: subprocess.Popen)
    """
    # Use local binary if present, otherwise PATH
    local_bin = Path(__file__).parent.parent / "cloudflared.exe"
    exe = str(local_bin) if local_bin.exists() else "cloudflared"

    # Log file for cloudflared output
    log_path = Path(__file__).parent.parent / ".cloudflared.log"
    log_file = open(log_path, "wb")

    cmd = [
        exe, "tunnel",
        "--url", f"http://127.0.0.1:{port}",
        "--protocol", "http2",
        "--proxy-connect-timeout", "30s",
        "--proxy-keepalive-timeout", "60s",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Drain stderr in a background thread so pipe never fills
    drain_thread = threading.Thread(
        target=_drain_pipe,
        args=(proc.stderr, log_file),
        daemon=True,
    )
    drain_thread.start()

    # Poll the log file for the tunnel URL
    url = None
    start = time.time()

    while time.time() - start < timeout:
        time.sleep(1)
        if proc.poll() is not None:
            break
        try:
            content = log_path.read_bytes().decode("utf-8", errors="ignore")
            match = TUNNEL_URL_PATTERN.search(content)
            if match:
                url = match.group(1)
                break
        except Exception:
            pass

    if not url:
        proc.kill()
        # Show what cloudflared said for debugging
        try:
            content = log_path.read_text(errors="ignore")
            print(f"[tunnel] cloudflared output:\n{content[-500:]}")
        except Exception:
            pass
        raise RuntimeError("Failed to capture cloudflared tunnel URL within timeout")

    return url, proc


def verify_tunnel(tunnel_url: str, retries: int = 10, delay: int = 3) -> bool:
    """Verify the tunnel is actually forwarding traffic."""
    for i in range(retries):
        try:
            r = requests.get(f"{tunnel_url}/api/health", timeout=15)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def deploy_with_url(tunnel_url: str) -> dict:
    """
    Read the pocket Willow template, inject the tunnel URL as default,
    and deploy to Neocities.
    """
    template_path = Path(__file__).parent.parent / "neocities" / "index.html"
    if not template_path.exists():
        return {"error": f"Template not found: {template_path}"}

    html = template_path.read_text(encoding="utf-8")

    # Inject the tunnel URL into the baked constant
    patched = html.replace(
        'const BAKED_TUNNEL = "";  // TUNNEL_INJECT_POINT',
        f'const BAKED_TUNNEL = "{tunnel_url}";  // TUNNEL_INJECT_POINT',
    )

    from apps.neocities import upload_text
    result = upload_text({"willow/index.html": patched})
    return result


def save_url(url: str):
    """Save current tunnel URL for other processes to read."""
    url_file = Path(__file__).parent.parent / ".tunnel_url"
    url_file.write_text(url, encoding="utf-8")


def get_saved_url() -> str:
    """Read the last known tunnel URL."""
    url_file = Path(__file__).parent.parent / ".tunnel_url"
    if url_file.exists():
        return url_file.read_text().strip()
    return ""


if __name__ == "__main__":
    no_deploy = "--no-deploy" in sys.argv
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Step 1: Confirm local server is up
    print("[tunnel] Checking local server...")
    if not wait_for_server(timeout=60):
        print("[tunnel] FAIL: Server not responding on :8420")
        print("[tunnel] Start it first: python server.py")
        sys.exit(1)
    print("[tunnel] Server is up.")

    # Step 2: Start tunnel
    print("[tunnel] Starting cloudflared...")
    try:
        url, proc = start_tunnel()
    except FileNotFoundError:
        print("[tunnel] cloudflared not found.")
        print("         Place cloudflared.exe in the Willow folder or install via:")
        print("         winget install Cloudflare.cloudflared")
        sys.exit(1)
    except RuntimeError as e:
        print(f"[tunnel] {e}")
        sys.exit(1)

    print(f"[tunnel] URL: {url}")
    save_url(url)

    # Step 3: Verify tunnel is actually working
    print("[tunnel] Verifying tunnel (this takes ~15-30s for DNS)...")
    if verify_tunnel(url):
        print("[tunnel] Tunnel verified — traffic flowing.")
    else:
        print("[tunnel] WARNING: Could not verify tunnel.")
        print("[tunnel]          Check .cloudflared.log for errors.")

    # Step 4: Deploy to Neocities
    if not no_deploy:
        print("[tunnel] Deploying to Neocities...")
        from core.llm_router import load_keys_from_json
        load_keys_from_json()
        result = deploy_with_url(url)
        if result.get("result") == "success":
            print("[tunnel] Deployed: https://seancampbell.neocities.org/willow/")
        else:
            print(f"[tunnel] Deploy issue: {result}")

    # Step 5: Hold tunnel open
    print(f"[tunnel] Running. Ctrl+C to stop.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        print("\n[tunnel] Stopped.")
