@echo off
title Aidar Tenders - Samruk TEST10O LOGGING
cd /d "%~dp0"
python -u procurevision_bridge_TEST10O_LOGGING.py
echo.
echo TEST10O bridge stopped or failed.
pause
