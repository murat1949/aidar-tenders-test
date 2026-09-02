@echo off
title Aidar Tenders - Samruk TEST9 BATCH3
cd /d "%~dp0"
python -u procurevision_bridge_TEST9_BATCH3.py
echo.
echo TEST9 bridge stopped or failed.
pause
