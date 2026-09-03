@echo off
title Aidar Tenders - Samruk TEST10J LOTCARDFALLBACK
cd /d "%~dp0"
python -u procurevision_bridge_TEST10J_LOTCARDFALLBACK.py
echo.
echo TEST10J bridge stopped or failed.
pause
