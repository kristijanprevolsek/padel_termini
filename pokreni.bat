@echo off
rem Pokreće provjeru termina; poziva ga Windows Task Scheduler pon/uto/sri u 07:58.
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
%PY% padel_obavijest.py --start-at 08:00 %* >> zapis.txt 2>&1
