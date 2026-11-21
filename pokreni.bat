@echo off
rem Provjera u 8:00 (pon/uto/sri) - kad se otvori novi dan.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python >nul 2>nul && (set PY=python) || (set PY=py)
%PY% padel_obavijest.py --watch --start-at 08:00 %* >> zapis.txt 2>&1
