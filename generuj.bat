@echo off
rem Start the reader and the generator, both detached, and leave them to it.
rem
rem Voxtral runs as a server and vLLM has no Windows build, so both live inside
rem WSL. This file only starts them; the log to watch is voxtral.log.
rem
rem No workers here. The old reader needed four processes to fill the card;
rem this one takes sixteen clips in one request and the card sits at about 70%%
rem with a single process. Measured: it never drops below 20%% between batches,
rem so there is nothing for a second process to pick up.
cd /d "%~dp0"
wsl -d Debian -e bash -lc "cd /mnt/c/Users/Oleg/Desktop/WordHunterProjects/WordHunterWoW-Voice-DE && VLLM_USE_FLASHINFER_SAMPLER=0 setsid nohup $HOME/voxtral/.venv/bin/vllm serve mistralai/Voxtral-4B-TTS-2603 --omni --port 8000 > $HOME/voxtral/serve.log 2>&1 < /dev/null & sleep 2; echo czytnik startuje"

echo Czekam az czytnik odpowie...
wsl -d Debian -e bash -lc "for i in $(seq 1 120); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && { echo gotowy; exit 0; }; sleep 5; done; echo 'czytnik nie wstal -- zobacz $HOME/voxtral/serve.log'; exit 1"
if errorlevel 1 exit /b 1

wsl -d Debian -e bash -lc "cd /mnt/c/Users/Oleg/Desktop/WordHunterProjects/WordHunterWoW-Voice-DE && setsid nohup $HOME/voxtral/.venv/bin/python -u Tools/generate_voxtral.py > voxtral.log 2>&1 < /dev/null & sleep 1; echo generator startuje"

echo.
echo Postep:  type voxtral.log
echo Stop:    wsl -d Debian -e pkill -f generate_voxtral.py
