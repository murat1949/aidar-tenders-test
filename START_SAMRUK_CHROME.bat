@echo off
title Samruk Chrome Collector
setlocal

set "CHROME1=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "CHROME2=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set "CHROME3=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME1%" (
  set "CHROME=%CHROME1%"
) else if exist "%CHROME2%" (
  set "CHROME=%CHROME2%"
) else if exist "%CHROME3%" (
  set "CHROME=%CHROME3%"
) else (
  echo Chrome not found.
  echo Please edit this file and set the correct chrome.exe path.
  pause
  exit /b 1
)

set "PROFILE=%~dp0samruk_chrome_profile"

start "" "%CHROME%" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  "https://zakup.sk.kz/"

echo.
echo Samruk Chrome started with remote debugging on port 9222.
echo Leave this Chrome window open while using ProcureVision bridge.
pause
