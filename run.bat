@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "docs\data\schedule.json" (
  echo Расписание ещё не собрано, собираем...
  python tools\build_data.py
)
echo.
echo Сайт открыт на http://localhost:8000
echo Закройте это окно, чтобы остановить.
echo.
python -m http.server 8000 --directory docs
