@echo off
setlocal
cd /d "%~dp0"
title WILLOW

echo.
echo   W I L L O W
echo   ___________
echo.

:: ── 1. OLLAMA ──────────────────────────────────────────
echo [1/13] Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo       Starting Ollama service...
    start "OLLAMA" /min ollama serve
    echo       Waiting for Ollama...
    :wait_ollama
    timeout /t 2 >nul
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if %errorlevel% neq 0 goto :wait_ollama
)
echo       OK.

:: ── 2. GOVERNANCE CHECK ────────────────────────────────
echo [2/13] Governance Check...
for %%f in (core\state.py core\gate.py core\storage.py) do (
    if not exist %%f (
        echo       [FATAL] %%f missing. Halted.
        pause
        exit /b 1
    )
)
echo       OK.

:: ── 3. AIOS ENGINE (background) ───────────────────────
echo [3/13] Engine...
start "AIOS ENGINE" /min python aios_loop.py
echo       OK.

:: ── 4. KARTIKEYA REFINERY (background) ────────────────
echo [4/13] Kart...
start "KARTIKEYA REFINERY" /min python kart.py --user Sweet-Pea-Rudi19
echo       OK.

:: ── 5. WEB SERVER (background, wait for ready) ────────
echo [5/13] Server...
start "WILLOW SERVER" /min python -m uvicorn server:app --host 0.0.0.0 --port 8420 --reload --log-level info
echo       Waiting for :8420...
set retries=0
:wait_server
timeout /t 2 >nul
curl -s http://127.0.0.1:8420/api/health >nul 2>&1
if %errorlevel% equ 0 goto :server_ok
set /a retries+=1
if %retries% geq 15 (
    echo       [FAIL] Server did not start after 30s.
    echo       Check the WILLOW SERVER window for errors.
    pause
    goto :shutdown
)
goto :wait_server
:server_ok
echo       OK. http://127.0.0.1:8420

:: ── 6. GOVERNANCE MONITOR (background) ─────────────────
echo [6/13] Governance Monitor...
start "WILLOW-GovernanceMonitor" /min python governance\monitor.py --interval 60 --daemon
echo       OK.

:: ── 7. COHERENCE SCANNER (background) ──────────────────
echo [7/13] Coherence Scanner...
start "WILLOW-CoherenceScanner" /min python core\coherence_scanner.py --interval 3600 --daemon
echo       OK.

:: ── 8. TOPOLOGY BUILDER (background) ───────────────────
echo [8/13] Topology Builder...
start "WILLOW-TopologyBuilder" /min python core\topology_builder.py --interval 3600 --daemon
echo       OK.

:: ── 9. KNOWLEDGE COMPACTOR (background) ────────────────
echo [9/13] Knowledge Compactor...
start "WILLOW-KnowledgeCompactor" /min python core\knowledge_compactor.py --interval 86400 --daemon
echo       OK.

:: ── 10. SAFE SYNC (background) ─────────────────────────
echo [10/13] SAFE Sync...
start "WILLOW-SAFESync" /min python core\safe_sync.py --interval 300 --daemon
echo       OK.

:: ── 11. PERSONA SCHEDULER (background) ─────────────────
echo [11/13] Persona Scheduler...
start "WILLOW-PersonaScheduler" /min python core\persona_scheduler.py --interval 60 --daemon
echo       OK.

:: ── 12. INBOX WATCHER (background) ─────────────────────
echo [12/13] Inbox Watcher...
start "WILLOW-InboxWatcher" /min python apps\watcher.py --no-consent
echo       OK.

:: ── 13. TUNNEL + DEPLOY (foreground) ───────────────────
echo [13/13] Tunnel...
:: Check for local binary first, then PATH
set CF_EXE=cloudflared
if exist "%~dp0cloudflared.exe" set CF_EXE=%~dp0cloudflared.exe
%CF_EXE% version >nul 2>&1
if %errorlevel% neq 0 (
    echo       cloudflared not found. Local only.
    echo       Run: curl -Lo cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
    echo.
    echo   ────────────────────────────────────────
    echo   Willow is running at:
    echo   http://127.0.0.1:8420
    echo   No tunnel. Close window to stop.
    echo   ────────────────────────────────────────
    pause
    goto :shutdown
)

echo       Starting tunnel + deploying to Neocities...
echo.
echo   ────────────────────────────────────────
echo   All systems running.
echo   Tunnel starting — Neocities auto-deploy.
echo   Close this window to stop everything.
echo   ────────────────────────────────────────
echo.
python apps\tunnel.py

:: ── SHUTDOWN ───────────────────────────────────────────
:shutdown
echo.
echo   Shutting down...
taskkill /FI "WINDOWTITLE eq AIOS ENGINE" >nul 2>&1
taskkill /FI "WINDOWTITLE eq KARTIKEYA REFINERY" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW SERVER" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-GovernanceMonitor" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-CoherenceScanner" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-TopologyBuilder" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-KnowledgeCompactor" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-SAFESync" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-PersonaScheduler" >nul 2>&1
taskkill /FI "WINDOWTITLE eq WILLOW-InboxWatcher" >nul 2>&1
echo   All engines stopped.
echo   (Ollama left running — use KILL_SWITCH in scripts\ to stop it)
pause
