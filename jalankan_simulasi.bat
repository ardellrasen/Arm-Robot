@echo off
cd /d "%~dp0"
.venv\Scripts\python -m app.main --mode sim %*
