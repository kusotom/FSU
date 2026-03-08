@echo off
setlocal
cd /d %~dp0\..\frontend
set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"
if exist "%NPM_CMD%" (
  "%NPM_CMD%" run build
  "%NPM_CMD%" run preview -- --host 0.0.0.0 --port 5173
) else (
  npm run build
  npm run preview -- --host 0.0.0.0 --port 5173
)
