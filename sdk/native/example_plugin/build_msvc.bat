@echo off
rem 在 “x64 Native Tools Command Prompt for VS” 中运行本脚本。
setlocal
cd /d "%~dp0"
cl /nologo /LD /O2 /utf-8 /W4 /I.. plugin.c /Fe:plugin.dll
if errorlevel 1 exit /b 1
echo 已生成 %cd%\plugin.dll
