@echo off
REM Push data/economic_stress.db to GitHub — triggers API deploy via GitHub Actions.
REM No Kudu, SSH, or Azure CLI required.
setlocal

cd /d "%~dp0.."

where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git not found in PATH.
    echo Install Git for Windows or use GitHub Desktop to commit and push.
    echo   https://git-scm.com/download/win
    exit /b 1
)

if not exist data\economic_stress.db (
    echo data\economic_stress.db not found — running ETL first...
    call scripts\run_etl_local.bat
    if errorlevel 1 exit /b 1
)

git check-ignore -q data/economic_stress.db
if not errorlevel 1 (
    echo ERROR: data/economic_stress.db is still gitignored — check .gitignore
    exit /b 1
)

echo.
echo Staging bootstrap database...
git add data/economic_stress.db data/stress_model_params.json

git diff --cached --quiet
if not errorlevel 1 (
    echo Database already committed — nothing to push.
    echo To redeploy anyway: GitHub -^> Actions -^> run the API workflow manually.
    exit /b 0
)

for /f "delims=" %%i in ('git branch --show-current') do set BRANCH=%%i
if "%BRANCH%"=="" set BRANCH=main

echo.
echo Committing database for Azure deploy...
git commit -m "Deploy bootstrap database to Azure API"

echo.
echo Pushing to origin/%BRANCH% — GitHub Actions will deploy automatically...
git push origin %BRANCH%

echo.
echo Done. Watch deploy progress:
echo   https://github.com/M7MDGAMERG/E-Commerce-Intelligence-Platform/actions
echo.
echo After deploy completes, verify:
echo   https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/global-summary
