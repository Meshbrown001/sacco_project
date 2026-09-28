@echo off
rem Runs the SACCO penalty sweep and records the result in logs\penalty_sweep.log.
rem Safe to run as often as needed: each unpaid month is fined only once.

cd /d "%~dp0.."
if not exist logs mkdir logs

echo ==== %date% %time% ==== >> logs\penalty_sweep.log
"venv\Scripts\python.exe" manage.py run_penalty_sweep >> logs\penalty_sweep.log 2>&1