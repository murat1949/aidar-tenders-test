@echo off
title Aidar Tenders - Samruk TEST10M OPERATIONAL
cd /d "%~dp0"
python -u procurevision_bridge_TEST10M_OPERATIONAL.py
echo.
echo TEST10M bridge stopped or failed.
pause
