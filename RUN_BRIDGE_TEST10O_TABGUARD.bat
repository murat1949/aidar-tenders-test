@echo off
title Aidar Tenders - Samruk TEST10O TAB GUARD
cd /d "%~dp0"
python -u procurevision_bridge_TEST10O_TABGUARD.py
echo.
echo TEST10O bridge stopped or failed.
pause
