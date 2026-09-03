@echo off
title Aidar Tenders - Samruk TEST10G BATCH5 COVERAGECHECK
cd /d "%~dp0"
python -u procurevision_bridge_TEST10G_BATCH5_COVERAGECHECK.py
echo.
echo TEST10G bridge stopped or failed.
pause
