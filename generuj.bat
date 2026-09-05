@echo off
rem Four workers. One does not fill the card: the reader makes a token at a time
rem and the launches, not the arithmetic, are the limit. Each worker takes every
rem fourth clip, so all four cover the whole range and none of them owns a zone.
cd /d "%~dp0"
for %%i in (0 1 2 3) do start "voice%%i" /b .venv\Scripts\python.exe -u Tools\generate.py --voice narrator --first Data\lochmodan.json --shard %%i --of 4 >> generate%%i.log 2>&1
