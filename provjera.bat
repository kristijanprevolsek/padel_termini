@echo off
rem Provjera svakih 10 minuta - javlja samo nove slobodne termine.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python >nul 2>nul && (set PY=python) || (set PY=py)
%PY% padel_obavijest.py --watch %* >> zapis.txt 2>&1
