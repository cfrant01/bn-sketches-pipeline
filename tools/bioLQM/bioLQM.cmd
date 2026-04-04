@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PATH=%SCRIPT_DIR%;%PATH%"
java -cp "%SCRIPT_DIR%bioLQM-0.7.1.jar;%SCRIPT_DIR%lib\*" org.colomoto.biolqm.LQMLauncher %*
