@echo off
setlocal
cd /d %~dp0\..\frontend
npm run build
npm run preview -- --host 0.0.0.0 --port 5173
