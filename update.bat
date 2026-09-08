@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Скачиваем таблицы и пересобираем расписание...
python tools\build_data.py
pause
