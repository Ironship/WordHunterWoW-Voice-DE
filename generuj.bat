@echo off
rem Speaks whatever is still missing, then stops. Safe to run again at any time:
rem a clip already on disk, in the right voice, with unchanged text, is skipped.
rem That is also why this is registered to run at logon -- a reboot in the middle
rem of a month-long run costs only the clip it was on.
cd /d "%~dp0"
.venv\Scripts\python.exe -u Tools\generate.py --voice narrator >> generate.log 2>> generate.err
