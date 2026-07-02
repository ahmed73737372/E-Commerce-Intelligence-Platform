@echo off
REM Run the ETL pipeline locally (Python 3.11 venv)
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
echo Running ETL pipeline - this takes 5-15 minutes...
python main.py
if exist data\economic_stress.db (
    echo.
    echo SUCCESS: data\economic_stress.db created
    dir data\economic_stress.db
    echo.
    echo Next: push to Azure via GitHub — scripts\push_db_to_azure.bat
) else (
    echo.
    echo FAILED: database not created - check logs\platform.log
    exit /b 1
)
