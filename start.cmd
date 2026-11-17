@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Survey AI Agent - FlaUI + Python

set "ROOT=%~dp0"
set "AGENT=%ROOT%survey_ai_agent"
set "PY=%AGENT%\.venv\Scripts\python.exe"
set "PROFILE=%AGENT%\demo_profile.json"
set "CONF=%ROOT%survey.conf"
set "MARIADB_BASE=%ROOT%tools\mariadb"
set "MARIADB_DATA=%ROOT%tools\mariadb-data"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"

rem ---- survey URL comes from survey.conf (user-editable) ----
if not exist "%CONF%" (
  echo [ERROR] Config not found: %CONF%
  pause
  exit /b 1
)
set "SURVEY_URL="
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CONF%") do (
  if /i "%%A"=="SURVEY_URL" set "SURVEY_URL=%%~B"
)
if not defined SURVEY_URL (
  echo [ERROR] SURVEY_URL is missing in %CONF%
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo [ERROR] Python venv not found: %PY%
  pause
  exit /b 1
)
if not exist "%PROFILE%" (
  echo [ERROR] Profile not found: %PROFILE%
  pause
  exit /b 1
)
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [ERROR] chrome.exe not found
  pause
  exit /b 1
)

set "DOTNET=dotnet"
where dotnet >nul 2>nul
if errorlevel 1 set "DOTNET=C:\Program Files\dotnet\dotnet.exe"

echo [1/5] Ensure MariaDB on 127.0.0.1:3306
if not exist "%MARIADB_BASE%\bin\mariadbd.exe" (
  echo [ERROR] MariaDB binaries not found: %MARIADB_BASE%\bin\mariadbd.exe
  pause
  exit /b 1
)
if not exist "%MARIADB_DATA%\mysql" (
  echo [ERROR] MariaDB data directory not initialized: %MARIADB_DATA%
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath '%MARIADB_BASE%\bin\mariadbd.exe' -ArgumentList '--basedir=%MARIADB_BASE%','--datadir=%MARIADB_DATA%','--port=3306','--bind-address=127.0.0.1','--console' -WindowStyle Hidden; $d=(Get-Date).AddSeconds(40); while ((Get-Date) -lt $d -and -not (Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 } }; if (-not (Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue)) { exit 1 }"
if errorlevel 1 (
  echo [ERROR] MariaDB failed to start
  pause
  exit /b 1
)

echo [2/5] Restart Python Agent on 127.0.0.1:8790
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue; if ($c) { $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c.OwningProcess); if ($p.CommandLine -match 'uvicorn' -and $p.CommandLine -match 'main:app') { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800 } }; New-Item -ItemType Directory -Force '%AGENT%\artifacts' | Out-Null; Start-Process -FilePath '%PY%' -ArgumentList '-m','uvicorn','main:app','--host','127.0.0.1','--port','8790' -WorkingDirectory '%AGENT%' -RedirectStandardOutput '%AGENT%\artifacts\server.out.log' -RedirectStandardError '%AGENT%\artifacts\server.err.log' -WindowStyle Hidden; $d=(Get-Date).AddSeconds(40); while ((Get-Date) -lt $d -and -not (Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 }"
if errorlevel 1 (
  echo [ERROR] Python Agent failed to start
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8790/healthz' -TimeoutSec 5; Write-Host ('      mode=' + $h.llm.mode + ' configured=' + $h.llm.configured + ' db=' + $h.db.ok); if (-not $h.llm.configured) { Write-Host '      [WARN] DeepSeek key is not configured; LLM questions will need review.' } } catch { exit 1 }"
if errorlevel 1 (
  echo [ERROR] Python Agent health check failed
  pause
  exit /b 1
)

echo [3/5] Launch native Chrome (no CDP)
echo       survey: "%SURVEY_URL%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*survey-agent-chrome*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
start "" "%CHROME%" --force-renderer-accessibility --user-data-dir="%TEMP%\survey-agent-chrome" --no-first-run --no-default-browser-check --new-window "%SURVEY_URL%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).AddSeconds(45); $p=$null; while ((Get-Date) -lt $d) { $p=Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.MainWindowTitle -like '*Industrial Valve*' -or $_.MainWindowTitle -like '*ValveSpec*' -or $_.MainWindowTitle -like '*Survey*') } | Select-Object -First 1; if ($p) { break }; Start-Sleep -Milliseconds 500 }; if (-not $p) { exit 1 } else { Write-Host ('      window: ' + $p.MainWindowTitle) }"
if errorlevel 1 (
  echo [ERROR] Chrome window not ready
  pause
  exit /b 1
)

echo [4/5] Build C# executor
"%DOTNET%" build "%ROOT%FlaUI.UIA3.Automation.sln" -c Debug
if errorlevel 1 (
  echo [ERROR] C# build failed
  pause
  exit /b 1
)

echo [5/5] Analyze with Python Agent and execute in native Chrome
"%DOTNET%" run --project "%ROOT%src\FlaUI.UIA3.Automation" -c Debug --no-build -- --survey-ai --api http://127.0.0.1:8790 --profile "%PROFILE%" --url "%SURVEY_URL%" --no-submit --pace normal
set "EXITCODE=%ERRORLEVEL%"

echo.
echo Executor exit code: %EXITCODE%
echo Browser is left on the last step. Submit was NOT clicked.
pause
exit /b %EXITCODE%
