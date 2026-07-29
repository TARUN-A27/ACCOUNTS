# AI-Accounts Windows Scanner Agent

This folder contains the scanner agent that runs on the Windows PC where the scanner is connected.

PURPOSE:
The main AI-Accounts app may run on the server.
But the USB scanner is connected to a Windows user PC.
So this agent runs on the Windows PC and exposes a scan API.

FLOW:
AI-Accounts Web App -> Windows Scanner Agent -> NAPS2 -> USB Scanner -> PDF

WINDOWS REQUIREMENTS:
1. Scanner driver
2. NAPS2
3. Python 3

WINDOWS FOLDER:
Create this folder:
C:\AIAccountsScanner

Copy scanner_agent.py into:
C:\AIAccountsScanner\scanner_agent.py

PYTHON SETUP ON WINDOWS:
cd C:\AIAccountsScanner
py -m venv venv
.\venv\Scripts\activate
pip install flask

NAPS2 PROFILE:
Create a NAPS2 scan profile named:
AI_ACCOUNTS_ADF_A5

Recommended settings:
Source: Feeder / ADF
Page size: A5
DPI: 300
Color mode: Gray
Output: PDF

RUN AGENT ON WINDOWS:
cd C:\AIAccountsScanner
.\venv\Scripts\activate
python scanner_agent.py

TEST ON SAME WINDOWS PC:
http://127.0.0.1:6060/health
http://127.0.0.1:6060/scan

TEST FROM LINUX / SERVER:
curl -o /tmp/windows_scan_test.pdf http://WINDOWS_PC_IP:6060/scan
ls -lh /tmp/windows_scan_test.pdf

Replace WINDOWS_PC_IP with the Windows machine LAN IP.
