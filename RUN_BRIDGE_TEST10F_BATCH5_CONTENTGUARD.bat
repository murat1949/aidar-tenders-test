@echo off
title Aidar Tenders - Samruk TEST10F BATCH5 CONTENTGUARD
cd /d "%~dp0"
python -u procurevision_bridge_TEST10F_BATCH5_CONTENTGUARD.py
echo.
echo TEST10F bridge stopped or failed.
pause
