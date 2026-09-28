@echo off
setlocal enabledelayedexpansion
title SRE Memory Agent - launcher
cd /d "%~dp0"

rem ===========================================================================
rem  SRE Memory Agent - one-click launcher
rem
rem  Everything the project needs is brought up in dependency order:
rem    1. the Hindsight memory container (created once, started thereafter)
rem    2. the sandbox image generated repairs are tested in
rem    3. the Python environment and dependencies
rem    4. the demo repository with its deliberate failures
rem    5. the dashboard build
rem    6. the API, then the browser on the dashboard URL
rem
rem  Safe to re-run: every step checks before it acts. Flags:
rem    --skip-ui      never build the dashboard (use the existing build)
rem    --no-browser   do not open a browser at the end
rem    --nopause      do not wait for a keypress at the end
rem ===========================================================================

set "ROOT=%~dp0"
set "PY=%ROOT%venv\Scripts\python.exe"
set "ENV_FILE=%ROOT%.env"
set "ENV_TEMPLATE=%ROOT%.env.example"
set "SANDBOX_IMAGE=sre-memory-agent/sandbox:pytest"
set "HINDSIGHT_IMAGE=ghcr.io/vectorize-io/hindsight:latest"
set "HINDSIGHT_NAME=hindsight"

set "SKIP_UI=0"
set "OPEN_BROWSER=1"
set "NO_PAUSE=0"
rem An empty `for` set is a syntax error in cmd, so guard it: this runs with no
rem arguments most of the time.
if "%~1"=="" goto :flags_done
for %%A in (%*) do (
  if /i "%%~A"=="--skip-ui" set "SKIP_UI=1"
  if /i "%%~A"=="--no-browser" set "OPEN_BROWSER=0"
  if /i "%%~A"=="--nopause" set "NO_PAUSE=1"
)
:flags_done

echo.
echo ============================================================
echo   SRE MEMORY AGENT - incident recovery that remembers
echo ============================================================
echo   project:  %ROOT%
echo.

rem ---------------------------------------------------------------------------
rem  0. environment file
rem ---------------------------------------------------------------------------
if not exist "%ENV_FILE%" (
  if exist "%ENV_TEMPLATE%" (
    copy /y "%ENV_TEMPLATE%" "%ENV_FILE%" >nul
    echo [env]  Created .env from the template.
  )
)

set "GROQ_API_KEY="
set "API_PORT=8000"
if exist "%ENV_FILE%" (
  for /f "usebackq tokens=1,* delims==" %%K in ("%ENV_FILE%") do (
    if /i "%%K"=="GROQ_API_KEY" set "GROQ_API_KEY=%%L"
    if /i "%%K"=="API_PORT" set "API_PORT=%%L"
  )
)
if "!API_PORT!"=="" set "API_PORT=8000"
set "URL=http://127.0.0.1:!API_PORT!/"

if "!GROQ_API_KEY!"=="" (
  echo [env]  GROQ_API_KEY is not set in .env
  echo        The agent needs it to classify, repair and review.
  echo        Add your key from https://console.groq.com/keys and run this again.
  echo.
  goto :finish
)

rem ---------------------------------------------------------------------------
rem  1. Hindsight memory
rem ---------------------------------------------------------------------------
set "DOCKER_OK=0"
where docker >nul 2>&1
if errorlevel 1 (
  echo [mem]  docker was not found. Memory will be unavailable and the agent
  echo        will run degraded: it still investigates and verifies, but it
  echo        cannot recall or learn. Install Docker Desktop for the full demo.
  echo.
  goto :skip_memory
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [mem]  The Docker daemon is not running. Start Docker Desktop, or the
  echo        agent will run degraded without memory.
  echo.
  goto :skip_memory
)
set "DOCKER_OK=1"

docker container inspect "%HINDSIGHT_NAME%" >nul 2>&1
if errorlevel 1 (
  echo [mem]  Creating the Hindsight container...
  docker run -d --name "%HINDSIGHT_NAME%" --restart unless-stopped ^
    -p 8888:8888 -p 9999:9999 ^
    -v hindsight-data:/home/hindsight/.pg0 ^
    -e HINDSIGHT_API_LLM_PROVIDER=groq ^
    -e HINDSIGHT_API_LLM_API_KEY=!GROQ_API_KEY! ^
    -e HINDSIGHT_API_LLM_MODEL=openai/gpt-oss-120b ^
    -e HINDSIGHT_API_LLM_GROQ_SERVICE_TIER=on_demand ^
    -e "HINDSIGHT_API_RETAIN_LLM_EXTRA_BODY={\"service_tier\":\"on_demand\"}" ^
    -e "HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY={\"service_tier\":\"on_demand\"}" ^
    -e "HINDSIGHT_API_CONSOLIDATION_LLM_EXTRA_BODY={\"service_tier\":\"on_demand\"}" ^
    -e "HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_EXTRA_BODY={\"service_tier\":\"on_demand\"}" ^
    "%HINDSIGHT_IMAGE%" >nul
  if errorlevel 1 (
    echo [mem]  Could not create the container - pulling the image may take a
    echo        moment on first run. Memory will be unavailable this time.
    echo.
    goto :skip_memory
  )
  echo [mem]  Container created.
) else (
  docker start "%HINDSIGHT_NAME%" >nul 2>&1
  echo [mem]  Container started.
)

rem Hindsight initialises an embedded database on first boot, so give it a moment.
echo [mem]  Waiting for Hindsight on port 8888...
set "MEM_READY=0"
for /l %%N in (1,1,45) do (
  if "!MEM_READY!"=="0" (
    curl -s -m 3 -o nul http://127.0.0.1:8888/version >nul 2>&1
    if not errorlevel 1 set "MEM_READY=1"
    if "!MEM_READY!"=="0" timeout /t 2 /nobreak >nul 2>&1
  )
)
if "!MEM_READY!"=="1" (
  echo [mem]  Hindsight is answering.
) else (
  echo [mem]  Hindsight has not answered yet. It may still be starting.
  echo        The dashboard will report it as unavailable until it does.
)
echo.

:skip_memory

rem ---------------------------------------------------------------------------
rem  2. sandbox image
rem ---------------------------------------------------------------------------
if "!DOCKER_OK!"=="1" (
  docker image inspect "%SANDBOX_IMAGE%" >nul 2>&1
  if errorlevel 1 (
    echo [box]  Building the sandbox image ^(first run only, about a minute^)...
    docker build -f docker\sandbox.Dockerfile -t "%SANDBOX_IMAGE%" . 
    if errorlevel 1 (
      echo [box]  The build failed. Generated code will be tested in a local
      echo        temporary workspace instead, and the dashboard will say so.
    ) else (
      echo [box]  Sandbox image ready.
    )
  ) else (
    echo [box]  Sandbox image present.
  )
  echo.
)

rem ---------------------------------------------------------------------------
rem  3. python environment
rem ---------------------------------------------------------------------------
if not exist "%PY%" (
  echo [py]   Creating the virtual environment ^(first run only^)...
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv venv
  ) else (
    python -m venv venv
  )
  if not exist "%PY%" (
    echo [py]   Could not create the virtual environment.
    echo        Install Python 3.11 or newer from https://python.org and re-run.
    echo.
    goto :finish
  )
)

"%PY%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
  echo [py]   Installing dependencies ^(first run only^)...
  "%PY%" -m pip install --upgrade pip >nul 2>&1
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [py]   Dependency installation failed. See the messages above.
    echo.
    goto :finish
  )
)
echo [py]   Environment ready.
echo.

rem ---------------------------------------------------------------------------
rem  4. demo repository
rem ---------------------------------------------------------------------------
if not exist "%ROOT%data\demo-repo\.git" (
  echo [repo] Building the demo repository and its failing scenarios...
  "%PY%" scripts\setup_demo_repo.py --no-verify
  if errorlevel 1 (
    echo [repo] Setup failed. See the messages above.
    echo.
    goto :finish
  )
)
echo [repo] Demo repository ready.
echo.

rem ---------------------------------------------------------------------------
rem  5. dashboard build
rem ---------------------------------------------------------------------------
if "!SKIP_UI!"=="0" (
  where npm >nul 2>&1
  if errorlevel 1 (
    echo [ui]   npm was not found, so the dashboard cannot be built.
    echo        Install Node.js 18 or newer from https://nodejs.org.
    echo        The API still runs; only the dashboard will be missing.
    echo.
  ) else (
    pushd web
    if not exist node_modules (
      echo [ui]   Installing dashboard dependencies ^(first run only^)...
      call npm install --no-fund --no-audit
    )
    rem Built on every launch rather than only when dist is missing. A stale build serves
    rem the previous interface from web\dist without any warning, which is a far worse
    rem failure than five seconds of building. Use --skip-ui to bypass it.
    echo [ui]   Building the dashboard...
    call npm run build
    if errorlevel 1 (
      echo [ui]   The build reported errors. See the messages above; the existing
      echo        build in web\dist will be served if there is one.
    )
    popd
    echo.
  )
)

rem ---------------------------------------------------------------------------
rem  6. the API
rem ---------------------------------------------------------------------------
set "ALREADY=0"
netstat -ano | findstr /r /c:"TCP.*:!API_PORT! .*LISTENING" >nul 2>&1
if not errorlevel 1 set "ALREADY=1"

if "!ALREADY!"=="1" (
  echo [api]  Something is already serving port !API_PORT! - using it.
) else (
  echo [api]  Starting the agent on port !API_PORT! ...
  start "SRE Memory Agent - API" /min "%PY%" scripts\serve.py --port !API_PORT!
  echo [api]  Waiting for the API to answer...
  set "API_READY=0"
  for /l %%N in (1,1,45) do (
    if "!API_READY!"=="0" (
      curl -s -m 3 -o nul "http://127.0.0.1:!API_PORT!/api/status" >nul 2>&1
      if not errorlevel 1 set "API_READY=1"
      if "!API_READY!"=="0" timeout /t 2 /nobreak >nul 2>&1
    )
  )
  if "!API_READY!"=="1" (
    echo [api]  The API is answering.
  ) else (
    echo [api]  The API has not answered yet. Check the API window for errors;
    echo        the dashboard will connect as soon as it comes up.
  )
)
echo.

if "!OPEN_BROWSER!"=="1" (
  set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  if not exist "!CHROME!" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  if not exist "!CHROME!" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
  if exist "!CHROME!" (
    echo [web]  Opening Chrome at !URL!
    start "" "!CHROME!" "!URL!"
  ) else (
    echo [web]  Opening the default browser at !URL!
    start "" "!URL!"
  )
  echo.
)

echo ============================================================
echo   READY
echo ============================================================
echo   Dashboard   !URL!
echo   API docs    http://127.0.0.1:!API_PORT!/docs
echo.
echo   The guided product tour starts by itself when the dashboard
echo   loads. Press Skip to dismiss it ^(it returns on a later visit,
echo   or immediately from "Restart product tour" in the sidebar^).
echo.
echo   Close the "SRE Memory Agent - API" window to stop the agent.
echo   Hindsight keeps running; stop it with:
echo       docker stop %HINDSIGHT_NAME%
echo ============================================================

:finish
if "!NO_PAUSE!"=="0" (
  echo.
  pause
)
endlocal
