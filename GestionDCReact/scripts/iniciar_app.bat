@echo off
setlocal
cd /d "%~dp0.."
start "GestionDC API" cmd /k "npm run api"
start "GestionDC React" cmd /k "npm run dev"
start "" "http://127.0.0.1:5174"
