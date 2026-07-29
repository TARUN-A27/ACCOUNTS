@echo off
title AI-Accounts Scanner Agent Installer

echo ========================================
echo AI-Accounts Scanner Agent Installer
echo ========================================
echo.

cd /d C:\AIAccountsScanner 2>nul
if errorlevel 1 (
    mkdir C:\AIAccountsScanner
    cd /d C:\AIAccountsScanner
)

echo Copying scanner agent...
copy /Y "%~dp0scanner_agent.py" "C:\AIAccountsScanner\scanner_agent.py"

echo.
echo Creating Python virtual environment...
py -m venv venv

echo.
echo Installing Flask...
call C:\AIAccountsScanner\venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install flask

echo.
echo Creating desktop start shortcut batch...
copy /Y "%~dp0START_AI_ACCOUNTS_SCANNER.bat" "%USERPROFILE%\Desktop\START_AI_ACCOUNTS_SCANNER.bat"

echo.
echo ========================================
echo INSTALLATION COMPLETE
echo ========================================
echo.
echo IMPORTANT:
echo 1. Install NAPS2 if not installed.
echo 2. Create NAPS2 profile named AI_ACCOUNTS_ADF_A5.
echo 3. Double-click START_AI_ACCOUNTS_SCANNER.bat on Desktop.
echo.
pause
