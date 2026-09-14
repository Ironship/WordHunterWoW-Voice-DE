#!/usr/bin/env python3
"""Build the CurseForge upload archives, and prove each one opens.

    python Tools/pack_release.py                 # engine and every pack
    python Tools/pack_release.py --only Words    # one of them
    python Tools/pack_release.py --check         # open what is already there

Until this existed the thirteen archives were zipped by hand, and on
2026-09-14 one of them was wrong: WordHunterWoW-Voice-DE-Words-1.0.5.zip had a
valid header, 643 MB of content and no end-of-central-directory record at all.
Nothing caught it. A directory listing showed a plausible file, slightly
smaller than its neighbours, which reads as "compressed well" rather than as
"stopped early"; the real archive is 828 MB, so a fifth of it was missing. The
size was quoted in a document being sent outside the project before anyone
opened the file.

So this writes the archives and then reopens every one. That second half is the
point of the tool. Packing is easy and a shell one-liner does it; knowing the
result is loadable is what was missing.

What goes in
------------

The files git tracks, minus what .pkgmeta tells the CurseForge packager to
ignore, minus .pkgmeta itself. Not a directory walk: the engine's working
folder carries the whole 341,731-clip master corpus, a build tree and a dozen
generator logs, none of which belong in a 0.1 MB code addon, and a walk would
need an exclusion list that drifts out of step with the one CurseForge already
reads. Asking git and .pkgmeta means the archive matches what the packager
would produce from the same tag, and neither list has to be maintained twice.

Verified against the archives that were already correct: for the engine, for
Classic and for Dragonflight, this rule reproduces the shipped file list
exactly -- 13, 25,242 and 14,581 files, no difference in either direction.

Deflated by default, which is not the obvious choice for audio and was decided
by measuring rather than by assuming. Ogg is already compressed, so the
expectation was that deflate would buy nothing; on the Dragonflight pack it
buys 3.3% -- 293.8 MB against 303.8 MB stored -- because a pack is 14,000 small
files and the savings are in the headers and the short tails, not in the audio
itself. A release is built rarely and downloaded often, so 3.3% across six
gigabytes is worth the minutes. --store trades it back for speed.

What it refuses to do
---------------------

Build from a dirty repository, or from one whose .toc version and newest tag
disagree. An archive is named after a version and is uploaded as that version;
if the working tree has moved on, the name is a lie that nothing downstream can
detect. --allow-dirty is there for trying things out, and says so in the
report.
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = "WordHunterWoW-Voice-DE"

# Beside the workspace rather than inside it, because that is where the
# archives have always been staged and where the submission notes sit. The nine
# code addons do not come through here at all: their CurseForge projects have
# packaging enabled, so pushing a tag builds them on CurseForge's side. The
# voice packs have it deliberately off -- the packager would have to be handed
# gigabytes of committed audio -- so these are the ones uploaded by hand, and
# these are the ones nothing was checking.
OUTDIR = ROOT.parent.parent / "curseforge-packages"

# CurseForge refuses a file larger than this. A pack that crosses it has to be
# split before it can ship, so building it and finding out at upload time is
# the wrong order.
FILE_LIMIT = 2 * 1000 ** 3


def run(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    return out.stdout.strip()


def pkgmeta_ignores(repo):
    """The ignore list CurseForge's own packager reads, if there is one.

    Parsed rather than guessed at. A hand-kept second copy of this list is how
    the engine archive would quietly regrow a Data directory the client cannot
    open.
    """
    meta = repo / ".pkgmeta"
    if not meta.exists():
        return []
    found, inside = [], False
    for line in meta.read_text(encoding="utf-8").splitlines():
        if re.match(r"^ignore:\s*$", line):
            inside = True
            continue
        if not inside:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entry = re.match(r"^\s+-\s+(\S+)\s*$", line)
        if entry:
            found.append(entry.group(1))
        else:
            # Dedented back to a new top-level key: the list is over.
            break
    return found


def contents(repo):
    """Every path that belongs in the archive, relative to the addon folder."""
    ignores = pkgmeta_ignores(repo)
    keep = []
    for path in run(repo, "ls-files").splitlines():
        if path == ".pkgmeta":
            continue
        if any(path == i or path.startswith(i + "/") for i in ignores):
            continue
        keep.append(path)
    return keep


def version_of(repo, folder):
    """The version in the manifest, which is what the archive is named after."""
    toc = repo / ("%s_Mainline.toc" % folder)
    if not toc.exists():
        toc = repo / ("%s.toc" % folder)
    if not toc.exists():
        return None
    found = re.search(r"^## Version:\s*(.+)$",
                      toc.read_text(encoding="utf-8-sig"), re.M)
    return found.group(1).strip() if found else None


def validate(archive, expected):
    """Reopen the finished file and compare it with what went in.

    Reopening is most of the check: a truncated archive has no
    end-of-central-directory record and cannot be opened at all, which is
    exactly how the Words pack failed. The size comparison catches the quieter
    version -- an entry that was written short but left the directory intact.
    """
    problems = []
    try:
        with zipfile.ZipFile(archive) as z:
            written = {i.filename: i.file_size for i in z.infolist()}
    except Exception as why:
        return ["will not open: %s" % why]

    missing = set(expected) - set(written)
    extra = set(written) - set(expected)
    if missing:
        problems.append("%d file(s) missing, e.g. %s"
                        % (len(missing), sorted(missing)[0]))
    if extra:
        problems.append("%d unexpected file(s), e.g. %s"
                        % (len(extra), sorted(extra)[0]))
    short = [n for n, size in written.items()
             if n in expected and size != expected[n]]
    if short:
        problems.append("%d file(s) stored at the wrong size, e.g. %s"
                        % (len(short), short[0]))
    return problems


def deep_check(archive):
    """Read every byte back and check its CRC. Slow, and sometimes worth it."""
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
    return ["corrupt entry: %s" % bad] if bad else []


def build(repo, folder, outdir, deep, allow_dirty, store):
    version = version_of(repo, folder)
    if not version:
        return None, ["no ## Version: in the manifest"]

    problems = []
    if run(repo, "status", "--porcelain") and not allow_dirty:
        problems.append("working tree is dirty -- commit, or pass --allow-dirty")
    tag = run(repo, "describe", "--tags", "--abbrev=0")
    if tag and tag.lstrip("v") != version and not allow_dirty:
        problems.append("manifest says %s, newest tag is %s" % (version, tag))
    if problems:
        return None, problems

    paths = contents(repo)
    if not paths:
        return None, ["git tracks nothing here -- is this a repository?"]

    # Sized before packing, so the check afterwards compares against the source
    # rather than against the archive's own account of itself.
    expected = {}
    for path in paths:
        full = repo / path
        if not full.exists():
            return None, ["git tracks %s but it is not on disk" % path]
        expected["%s/%s" % (folder, path)] = full.stat().st_size

    archive = outdir / ("%s-%s.zip" % (folder, version))
    partial = archive.with_suffix(".zip.partial")
    if partial.exists():
        partial.unlink()

    # Written under a different name and moved into place only once it has been
    # checked. An interrupted run then leaves a .partial nobody will upload,
    # instead of a plausible-looking archive sitting where the good one was.
    method = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(partial, "w", method, allowZip64=True) as z:
        for path in paths:
            z.write(repo / path, "%s/%s" % (folder, path))

    problems = validate(partial, expected)
    if not problems and deep:
        problems += deep_check(partial)
    size = partial.stat().st_size
    if size > FILE_LIMIT:
        problems.append("%.2f GB -- over CurseForge's %d GB limit for one file"
                        % (size / 1000 ** 3, FILE_LIMIT // 1000 ** 3))
    if problems:
        return None, problems

    if archive.exists():
        archive.unlink()
    os.replace(partial, archive)
    return archive, []


def check_only(outdir):
    """Open every archive already sitting in the output directory."""
    archives = sorted(outdir.glob("*.zip"))
    if not archives:
        sys.exit("no archives in %s" % outdir)
    bad = 0
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as z:
                count = len(z.namelist())
            note = "ok, %d entries" % count
        except Exception as why:
            note = "BROKEN: %s" % why
            bad += 1
        print("  %-52s %8.1f MB  %s"
              % (archive.name, archive.stat().st_size / 1e6, note))
    print("\n%d archive(s), %d broken" % (len(archives), bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=str(ROOT.parent),
                    help="where the engine and pack repositories live")
    ap.add_argument("--out", default=str(OUTDIR))
    ap.add_argument("--only", help="one pack by name, e.g. Words, or Engine")
    ap.add_argument("--store", action="store_true",
                    help="skip compression; faster, and about 3%% larger")
    ap.add_argument("--deep", action="store_true",
                    help="also read every byte back and check its CRC")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="build from an uncommitted tree anyway")
    ap.add_argument("--check", action="store_true",
                    help="open the archives already built and stop")
    args = ap.parse_args()

    repos = pathlib.Path(args.repos)
    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.check:
        sys.exit(check_only(outdir))

    folders = [ENGINE] + sorted(
        p.name for p in repos.glob("%s-*" % ENGINE) if (p / ".git").is_dir())
    if args.only:
        wanted = ENGINE if args.only.lower() == "engine" \
            else "%s-%s" % (ENGINE, args.only)
        folders = [f for f in folders if f == wanted]
        if not folders:
            sys.exit("no repository named %s under %s" % (wanted, repos))

    total, failures = 0, []
    for folder in folders:
        repo = repos / folder
        archive, problems = build(repo, folder, outdir, args.deep,
                                  args.allow_dirty, args.store)
        if problems:
            failures.append((folder, problems))
            print("  %-52s FAILED" % folder)
            for line in problems:
                print("      %s" % line)
            continue
        size = archive.stat().st_size
        total += size
        print("  %-52s %8.1f MB  ok%s"
              % (archive.name, size / 1e6, "  (dirty)" if args.allow_dirty else ""))

    print("\n%d archive(s) built, %.2f GB total"
          % (len(folders) - len(failures), total / 1000 ** 3))
    if failures:
        print("%d FAILED -- nothing was moved into place for those"
              % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
