@echo off
title AI-Accounts Scanner Agent

cd /d C:\AIAccountsScanner

if not exist scanner_agent.py (
    echo scanner_agent.py not found in C:\AIAccountsScanner
    echo Run INSTALL_AI_ACCOUNTS_SCANNER.bat first.
    pause
    exit /b 1
)

if not exist venv\Scripts\activate.bat (
    echo Python environment not found.
    echo Run INSTALL_AI_ACCOUNTS_SCANNER.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo Starting AI-Accounts Windows Scanner Agent...
echo.
echo Health URL:
echo http://127.0.0.1:6060/health
echo.
echo Keep this window open while scanning.
echo.

python scanner_agent.py

pause
