#!/usr/bin/env bash
# Keep the reader working, not merely running, for as long as there is speech
# left to make.
#
# THE FAULT THIS EXISTS FOR
#
# The card is a 24 GB 4090 under Windows, and the reader is the only thing in
# the machine that wants all of it. vLLM takes its memory once at startup and
# holds it: measured at 22.0 GB of 24.6 GB, leaving 740 MB. Windows will not
# refuse another program that wants video memory -- under WDDM the driver evicts
# somebody else to system RAM and pages it back across the bus on demand.
#
# So the moment anything else asks for a couple of gigabytes, part of the reader
# goes to host memory and stays there. It was caught in the act at 12:41 on
# 6 September: World of Warcraft was launched, and over the next three minutes
# mean request latency went 2.3s, 3.2s, 5.1s, 7.1s, 44s. It settled with 2,919 MB
# of video memory living in host RAM, the card reading 100% busy at 89 W of a
# 450 W board -- the shape of a GPU servicing page faults rather than computing
# -- and the run down from 236 clips a minute to 32.
#
# The reader never notices. Its log carries no error, no out-of-memory, no
# preempted request, no scheduler stall, because from where it stands nothing is
# wrong: every kernel it launches returns, only slowly. /health stays 200 and
# every batch still succeeds. That is why this is a supervisor and not a retry:
# the failure the generator already handles is a reader that stops answering,
# and this one answers all night.
#
# The heavy copying onto /mnt/c that preceded two earlier occurrences was a
# bystander. During the occurrence measured above the disks were idle -- eight
# sectors written in five seconds, no copy running anywhere on the machine. What
# the two have in common is a person at the desktop, and a person at the desktop
# opens things that want the card.
#
# TWO PARTS, AND WHY BOTH
#
# Headroom stops it happening. Capping the reader's KV cache at 4 GiB brings it
# down to about 16 GiB and leaves better than 3 GB free, which is enough for the
# game and the desktop to take what they need without evicting anyone. Measured
# with the game still running: 217 clips a minute against 32 before the change,
# and 236 on a card with nothing else on it. Per-request latency 2.4-2.8s
# against 2.3s clean. The smaller cache costs nothing here because it was never
# the constraint -- 4 GiB is still 40,320 tokens, and sixteen clips of quest
# text in flight want under 5,000 between them.
#
# Restarting cures it once it has happened. It works because vLLM measures the
# memory actually free at startup and sizes itself to fit around whoever got
# there first, which is why a restart mid-session needs no help from anybody to
# pick the right number.
#
# Neither part is sufficient alone: headroom can be eaten by a big enough
# newcomer, and a cure that needs a person awake to apply it is no use to a run
# left overnight.
set -u

ROOT="${ROOT:-/mnt/c/Users/Oleg/Desktop/WordHunterProjects/WordHunterWoW-Voice-DE}"
VOXTRAL="${VOXTRAL:-$HOME/voxtral}"
PYTHON="$VOXTRAL/.venv/bin/python"
PROGRESS="$ROOT/voxtral.progress"
RUNLOG="$ROOT/voxtral.log"
SERVELOG="$VOXTRAL/serve.log"
LOG="$ROOT/voxtral-watchdog.log"
PORT="${PORT:-8000}"
MODEL="mistralai/Voxtral-4B-TTS-2603"

# 4 GiB, the figure measured above. Raise it only against a measurement: the
# whole point of the number is the space it leaves unused.
KV_CACHE_BYTES="${KV_CACHE_BYTES:-4294967296}"

# What the generator is asked to speak. Named here rather than assumed, because
# a supervisor that restarted the run with arguments other than the ones it was
# started with would quietly reorder a week of work.
GEN_ARGS="${GEN_ARGS:---first Data/priority.json}"

CHECK_SECONDS="${CHECK_SECONDS:-60}"
# Below a third of the healthy rate, three checks running. The floor sits well
# under the 217 a minute a busy card still manages, so an evening's gaming does
# not trip it; the occurrence this was written for sat at 32. Three checks
# because one minute can be legitimately slow -- a batch of long quest text, or
# the encoders backed up behind the Windows disk.
FLOOR_PER_MIN="${FLOOR_PER_MIN:-70}"
PATIENCE="${PATIENCE:-3}"
# How long to allow after a restart before judging the result. The weights take
# about two and a half minutes to load and the first batches after that are slow.
SETTLE_SECONDS="${SETTLE_SECONDS:-300}"

# Say something even when there is nothing wrong, this often.
#
# A supervisor that only speaks up about problems writes exactly the same log as
# one that died hours ago, and the second is the case you most need to notice --
# it is the one where nothing is watching and nobody knows. A line every half
# hour makes a stale log mean something: if the last stamp is old, the watchdog
# is gone, whatever the rest of the file says.
SAY_EVERY_SECONDS="${SAY_EVERY_SECONDS:-1800}"

LAST_SAID=0
say() {
  LAST_SAID=$(date +%s)
  printf "%s  %s\n" "$(date +%Y-%m-%dT%H:%M:%S)" "$*" | tee -a "$LOG"
}

# The card's own account of itself, which is the difference between a diagnosis
# and a guess. 100% busy at low wattage is the eviction signature; 100% busy at
# 200 W and still slow is something else entirely, and worth saying so.
gpu_line() {
  local q
  q=$(nvidia-smi --query-gpu=utilization.gpu,power.draw,memory.used,memory.total \
      --format=csv,noheader,nounits 2>/dev/null) || { echo "gpu unreadable"; return; }
  echo "util/power/mem: $q"
}

# Processes matching the pattern, never counting this script or the shell that
# launched it. Both readings matter and they fail in opposite directions: a
# false negative restarts something that was working, a false positive leaves a
# dead generator unnoticed until morning. The pattern is a substring of a
# command line, and the command line that ran this script is a candidate like
# any other.
procs_matching() {
  local pid out=""
  for pid in $(pgrep -f "$1" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    out="$out $pid"
  done
  [ -n "$out" ] && echo "$out"
}

reader_up()    { curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }
reader_procs() { [ -n "$(procs_matching 'vllm serve')" ]; }
gen_up()       { [ -n "$(procs_matching 'generate_voxtral.py')" ]; }

# One field of the heartbeat, or a failure if it cannot be read. Deliberately no
# default of zero: zero is indistinguishable from a run that has not spoken
# anything yet, and the caller has to tell those two apart.
progress_field() {
  [ -f "$PROGRESS" ] || return 1
  "$PYTHON" - "$PROGRESS" "$1" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.load(fh)[sys.argv[2]])
except Exception:
    sys.exit(1)
PY
}

start_reader() {
  say "starting reader, kv-cache-memory=$KV_CACHE_BYTES ($((KV_CACHE_BYTES/1024/1024)) MiB)"
  ( cd "$VOXTRAL" && VLLM_USE_FLASHINFER_SAMPLER=0 setsid nohup ./.venv/bin/vllm serve \
      "$MODEL" --omni --port "$PORT" --kv-cache-memory "$KV_CACHE_BYTES" \
      >> "$SERVELOG" 2>&1 < /dev/null & )
  local i
  for i in $(seq 1 60); do
    sleep 5
    reader_up && { say "reader ready after $((i * 5))s"; return 0; }
  done
  say "ALARM: reader did not answer /health within 300s. The end of its log:"
  tail -20 "$SERVELOG" | tee -a "$LOG"
  return 1
}

# pkill spares itself but not its parent, so a pattern that appears anywhere in
# the launching command line makes it cut its own throat. That happened here:
# it killed the supervising shell mid-sentence and left the run stopped with a
# reader still cheerfully answering /health. A supervisor is the one program
# that cannot afford to take itself down quietly.
kill_matching() {
  local sig="$1" pid
  for pid in $(procs_matching "$2"); do kill "-$sig" "$pid" 2>/dev/null || true; done
}

stop_reader() {
  kill_matching TERM "vllm serve"
  local i
  for i in $(seq 1 30); do reader_procs || break; sleep 1; done
  reader_procs && { say "reader ignored TERM, using KILL"; kill_matching KILL "vllm serve"; }
  sleep 3
}

start_generator() {
  say "starting generator: $GEN_ARGS"
  ( cd "$ROOT" && setsid nohup "$PYTHON" -u Tools/generate_voxtral.py $GEN_ARGS \
      >> "$RUNLOG" 2>&1 < /dev/null & )
  sleep 10
  gen_up || { say "ALARM: generator exited within 10s. The end of its log:"
              tail -20 "$RUNLOG" | tee -a "$LOG"; return 1; }
  return 0
}

say "watchdog up. floor ${FLOOR_PER_MIN}/min over ${PATIENCE} checks of ${CHECK_SECONDS}s; $(gpu_line)"

reader_up || { say "no reader answering at start"; stop_reader; start_reader || exit 1; }
gen_up    || { say "no generator running at start"; start_generator || exit 1; }

last_spoken=""
last_at=0
slow=0
restarts=0
settle_until=$(( $(date +%s) + SETTLE_SECONDS ))

while true; do
  sleep "$CHECK_SECONDS"
  now=$(date +%s)

  if [ "$(progress_field done 2>/dev/null || echo False)" = "True" ]; then
    say "the run reports itself finished, $(progress_field spoken) clips spoken. Standing down."
    exit 0
  fi

  # A generator that is gone without declaring itself finished was killed, or
  # died. Either way there is speech left, so put it back.
  if ! gen_up; then
    say "generator is not running and has not finished. The end of its log:"
    tail -5 "$RUNLOG" | tee -a "$LOG"
    reader_up || { stop_reader; start_reader || say "ALARM: the reader will not start"; }
    start_generator || { say "ALARM: cannot restart the generator, giving up"; exit 1; }
    last_spoken=""
    slow=0
    settle_until=$(( now + SETTLE_SECONDS ))
    continue
  fi

  spoken=$(progress_field spoken) || {
    # No heartbeat to read. Either the run predates this file being written, or
    # it has not finished its first batch. Said out loud every time rather than
    # assumed healthy -- a supervisor quietly watching nothing is the failure
    # this whole script exists to avoid.
    say "no readable heartbeat at $PROGRESS, though the generator is alive; waiting"
    continue
  }

  if [ -z "$last_spoken" ]; then
    last_spoken="$spoken"
    last_at="$now"
    continue
  fi

  elapsed=$(( now - last_at ))
  [ "$elapsed" -lt 1 ] && elapsed=1
  rate=$(( (spoken - last_spoken) * 60 / elapsed ))
  last_spoken="$spoken"
  last_at="$now"

  if [ "$now" -lt "$settle_until" ]; then
    say "settling: ${rate}/min"
    continue
  fi

  if [ "$rate" -ge "$FLOOR_PER_MIN" ]; then
    if [ "$slow" -gt 0 ]; then
      say "recovered: ${rate}/min"
    elif [ $(( now - LAST_SAID )) -ge "$SAY_EVERY_SECONDS" ]; then
      say "healthy: ${rate}/min, ${spoken} clips spoken; $(gpu_line)"
    fi
    slow=0
    restarts=0
    continue
  fi

  slow=$(( slow + 1 ))
  say "slow: ${rate}/min against a floor of ${FLOOR_PER_MIN} (${slow}/${PATIENCE}); $(gpu_line)"
  [ "$slow" -lt "$PATIENCE" ] && continue

  restarts=$(( restarts + 1 ))
  say "RESTARTING READER, attempt ${restarts} since the last healthy stretch; $(gpu_line)"
  # Nothing lost that matters. Every clip is encoded and stamped before the run
  # moves on, so this costs the batch of sixteen that was in flight, and the
  # generator reconnects by itself once the reader answers again.
  stop_reader
  start_reader || say "ALARM: the reader will not come back. The run is stalled and needs a person."
  slow=0
  settle_until=$(( $(date +%s) + SETTLE_SECONDS ))

  # Three restarts with no healthy stretch between them means restarting is not
  # the answer to whatever this is. Keep trying, because the alternative is a
  # lost night either way, but stop implying it is under control.
  if [ "$restarts" -ge 3 ]; then
    say "ALARM: ${restarts} restarts without recovery. Something has the card that a"
    say "ALARM: restart cannot size around. Look at what else is running on it."
  fi
done
