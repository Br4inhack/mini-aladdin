@echo off
echo Starting CRPMS Development Environment...

REM Check if Windows Terminal (wt) is available
where wt >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Windows Terminal detected. Booting multi-tab interface...

    wt -w 0 new-tab -p "Command Prompt" -d "%CD%" cmd /k "wsl -d Ubuntu redis-server" ^
    ; split-pane -p "Command Prompt" -d "%CD%" cmd /k ".\venv\Scripts\activate && python manage.py runserver" ^
    ; split-pane -p "Command Prompt" -d "%CD%" cmd /k ".\venv\Scripts\activate && celery -A config worker --loglevel=info --pool=solo" ^
    ; split-pane -p "Command Prompt" -d "%CD%" cmd /k ".\venv\Scripts\activate && celery -A config beat --loglevel=info"
    
) else (
    echo [WARNING] Windows Terminal not found. Falling back to separate windows...
    
    start "CRPMS - Redis (WSL)" cmd /k "wsl -d Ubuntu redis-server"
    
    timeout /t 3 /nobreak >nul
    
    start "CRPMS - Django Server" cmd /k ".\venv\Scripts\activate && python manage.py runserver"
    start "CRPMS - Celery Worker" cmd /k ".\venv\Scripts\activate && celery -A config worker --loglevel=info --pool=solo"
    start "CRPMS - Celery Beat" cmd /k ".\venv\Scripts\activate && celery -A config beat --loglevel=info"
)

echo.
echo ===========================================
echo All services started!
echo.
echo Dashboard: http://127.0.0.1:8000
echo Admin:     http://127.0.0.1:8000/admin
echo ===========================================
exit
