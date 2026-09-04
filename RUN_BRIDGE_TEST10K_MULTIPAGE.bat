@echo off
title Aidar Tenders - Samruk TEST10K MULTIPAGE
cd /d "%~dp0"
python -u procurevision_bridge_TEST10K_MULTIPAGE.py
echo.
echo TEST10K bridge stopped or failed.
pause
