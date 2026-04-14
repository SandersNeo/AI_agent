@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

start "AI Agent UI Test" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%REPO_ROOT%'; python -u automation\ui\ui_1c_agent_test.py %*"

endlocal
