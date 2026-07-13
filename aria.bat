@echo off
:: Aria auto-start — place in shell:startup
:: Edit the path below to match your install folder
timeout /t 12 /nobreak >nul
cd /d "C:\path\to\desktop-assistant"
python main.py
