@echo off
setlocal

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

set "PYTHON=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

echo ========================================
echo   Patient Care Assistant - Tunnel Start
echo ========================================
echo.

echo [1/5] Docker + Containers...
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker not running.
    pause
    exit /b 1
)

cd /d "%ROOT%"
docker compose up -d >nul 2>&1
if errorlevel 1 (
    docker-compose up -d >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] docker-compose failed.
        pause
        exit /b 1
    )
)

echo [2/5] PostgreSQL...
"%PYTHON%" -c "import psycopg2; psycopg2.connect(host='localhost',port=5433,user='postgres',password='postgres',dbname='patient_agent',connect_timeout=5).close(); print('OK')" 2>nul | findstr "OK" >nul
if errorlevel 1 (
    echo [ERROR] PostgreSQL not ready.
    pause
    exit /b 1
)

echo [3/5] Building React demo...
if not exist "%ROOT%\frontend\node_modules" (
    echo Installing frontend dependencies...
    cd /d "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] Frontend dependency installation failed.
        pause
        exit /b 1
    )
)
cd /d "%ROOT%\frontend"
call npm run build
if errorlevel 1 (
    echo [ERROR] React build failed.
    pause
    exit /b 1
)

echo [4/5] Starting demo backend...
cd /d "%ROOT%"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING" 2^>nul') do taskkill /f /pid %%a >nul 2>&1

set "DEMO_MODE=true"
set "LOG=%TEMP%\patient_care_assistant_backend.log"
start "Patient Care Assistant Backend" /min cmd /c ""%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 > "%LOG%" 2>&1"

timeout /t 3 /nobreak >nul
curl -s -o nul http://127.0.0.1:8001/ 2>nul
if errorlevel 1 (
    echo [ERROR] Backend not responding. See %LOG%
    pause
    exit /b 1
)

echo [5/5] Cloudflare Tunnel...
set "CF=cloudflared"
where cloudflared >nul 2>&1
if not errorlevel 1 goto cloudflared_ready

set "CF=%ROOT%\.tools\cloudflared.exe"
if not exist "%ROOT%\.tools" mkdir "%ROOT%\.tools"
if not exist "%CF%" powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF%'"
if not exist "%CF%" (
    echo [ERROR] cloudflared not found.
    pause
    exit /b 1
)

:cloudflared_ready
set "CFG=%ROOT%\.cloudflared\config.yml"
if exist "%CFG%" (
    echo Named tunnel configuration found.
    "%CF%" --config "%CFG%" tunnel --protocol http2 run
) else (
    echo Quick tunnel: share the temporary URL printed below.
    "%CF%" tunnel --protocol http2 --url http://127.0.0.1:8001
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING" 2^>nul') do taskkill /f /pid %%a >nul 2>&1
pause
endlocal
