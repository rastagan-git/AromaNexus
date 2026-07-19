@echo off
cd /d "%~dp0"
call :find_python
"%PYTHON_EXE%" nist_excel_tool.py
pause
exit /b

:find_python
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    exit /b
)
if exist "myenv\Scripts\python.exe" (
    set "PYTHON_EXE=myenv\Scripts\python.exe"
    exit /b
)
if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"
exit /b
