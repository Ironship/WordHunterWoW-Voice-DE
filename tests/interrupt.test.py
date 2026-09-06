"""Ctrl-C during a run stops the run.

The interrupt is caught inside the retry loop, which is where it has to be --
the wait for a reader that has gone away is minutes long and has to be
escapable. But leaving that loop is not leaving the run: the batch it abandoned
looks exactly like a batch that timed out, and the line below sends those on to
the next one. So an interrupt skipped sixteen clips and carried on, and stopping
a run of a quarter of a million meant holding Ctrl-C down through fifteen
thousand batches.

Checked by counting calls rather than by reading the code, because the fault was
invisible in the reading: every piece of that loop does the right thing on its
own.
"""
import io
import json
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent / "Tools"
sys.path.insert(0, str(TOOLS))

import generate_voxtral as gv


def run(source, batches_before_interrupt=1):
    """Run main() over `source`'s loop with the reader and disk stubbed out."""
    module = types.ModuleType("gv_under_test")
    module.__file__ = str(TOOLS / "generate_voxtral.py")
    exec(compile(source, str(TOOLS / "generate_voxtral.py"), "exec"), module.__dict__)

    rows = [{"path": "sounds/q/%d.ogg" % n, "voice": "de_female",
             "text": "Satz %d." % n, "stamp": "x", "id": n, "kind": "quest"}
            for n in range(64)]
    module.load_plan = lambda only=None: rows
    module.cast = lambda r: r
    module.in_release_order = lambda r: r
    module.outstanding = lambda r, sounds, force=False: r
    module.encode = lambda wav, clip, quality: None
    module.heartbeat = lambda *a, **k: None

    calls = []

    def speak(client, base, chunk, timeout):
        calls.append(len(chunk))
        if len(calls) > batches_before_interrupt:
            raise KeyboardInterrupt
        return [b"" for _ in chunk]

    module.speak = speak

    fake_httpx = types.ModuleType("httpx")

    class Client:
        def get(self, *a, **k):
            return types.SimpleNamespace(raise_for_status=lambda: None)

    fake_httpx.Client = Client
    sys.modules["httpx"] = fake_httpx

    tmp = HERE / "_interrupt_sounds"
    tmp.mkdir(exist_ok=True)
    argv = sys.argv
    sys.argv = ["generate_voxtral.py", "--sounds", str(tmp),
                "--progress", str(tmp / "p.json"), "--order", "plan", "--batch", "16"]
    out = io.StringIO()
    stdout = sys.stdout
    sys.stdout = out
    try:
        module.main()
    finally:
        sys.argv = argv
        sys.stdout = stdout
    return calls, out.getvalue()


source = (TOOLS / "generate_voxtral.py").read_text(encoding="utf-8")

calls, out = run(source)
assert len(calls) == 2, (
    "Ctrl-C on the second batch left %d batches attempted: the run carried on "
    "past the interrupt" % len(calls))
assert "stopped after" in out, "the run said nothing about having been stopped"

# The same test against the behaviour this fixes, so a silent return of the
# fault does not pass. 64 clips in batches of 16 is four batches; the old code
# tried every one of them.
BREAK = """            if stopped:
                break
"""
assert source.count(BREAK) == 1, "the guard this test is about has moved"
old, _ = run(source.replace(BREAK, ""))
assert len(old) == 4, (
    "the old behaviour was meant to attempt all four batches, attempted %d -- "
    "this test is no longer measuring what it claims to" % len(old))

for leftover in (HERE / "_interrupt_sounds").glob("*"):
    leftover.unlink()
(HERE / "_interrupt_sounds").rmdir()
print("interrupt: ok -- Ctrl-C stops after %d batches, not %d" % (len(calls), len(old)))
