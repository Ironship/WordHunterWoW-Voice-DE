#!/usr/bin/env bash
#
# Put the working copies of the three addons into the live client.
#
#   Tools/install_dev.sh [-n] [-v] [path to Interface/AddOns]
#
# Runs under WSL Debian, where the client is reached through /mnt/c.
#
# What gets copied is read out of each addon's .toc every time, and is never
# written down here. The ad-hoc step this replaces named its files by hand and
# named only Core.lua, so QuestPanel.lua sat in the client at a revision from
# weeks earlier. The callback the German voiceover hangs its play buttons on was
# in the source and absent from the game, and the buttons simply never appeared.
#
# Nothing reported it, and nothing could have. A .toc that names a file the
# folder does not have is the half of this the client complains about; a folder
# holding an older copy of a file the .toc does name is silent by definition --
# it loads, it works, it is just not the code that was written. Reading the .toc
# means the list cannot drift from what the game loads, because it is the same
# list the game loads from.
#
# The sound packs are left alone. They are gigabytes, they are assembled by
# Tools/build_pack.py from audio generated locally, and folding them in here
# would turn a two-second step into a twenty-minute one -- which is how the
# previous step came to be skipped and hand-patched instead.

set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ADDONS_DEFAULT="/mnt/c/Program Files (x86)/World of Warcraft/_retail_/Interface/AddOns"

ADDON_NAMES=(WordHunterWoW WordHunterWoW-ENPanel WordHunterWoW-Voice-DE)

# Files the client can load that no .toc can name: the icon a .toc points at by
# path, and the placeholder clips Voice.lua builds a path to at runtime. Matched
# by extension rather than by a list of names, so an asset added later arrives
# without this script being edited -- editing it is the failure being designed
# out. The corollary is that the generator's inputs stay behind on their own
# merit: the client cannot load a .json, so Data/*.json needs no exclusion that
# somebody has to remember to write.
ASSET_EXTENSIONS=(tga blp ogg mp3 xml ttf otf)

# Above this an asset belongs to a sound pack, not to the addon. Every refusal
# is printed with its size, because an asset that disappears quietly is the same
# class of fault this whole script exists to end.
ASSET_MAX_BYTES=$((2 * 1024 * 1024))

DRY_RUN=0
VERBOSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1; shift ;;
    -v|--verbose) VERBOSE=1; shift ;;
    -h|--help) sed -n '3,7p' "${BASH_SOURCE[0]}" | sed -e 's/^#$//' -e 's/^# //'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done
ADDONS=${1:-$ADDONS_DEFAULT}

if [ ! -d "$ADDONS" ]; then
  echo "no AddOns folder at: $ADDONS" >&2
  exit 1
fi

# Every path a .toc asks the client to load, plus the .toc files themselves.
# Backslashes become slashes because a .toc writes Windows paths and this runs
# on a filesystem that does not.
toc_manifest() {
  local dir="$1" toc found=0
  for toc in "$dir"/*.toc; do
    [ -e "$toc" ] || continue
    found=1
    basename "$toc"
    sed -e 's/\r$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$toc" \
      | grep -v '^#' | grep -v '^$' | tr '\134' '/'
  done | sort -u
  [ "$found" = 1 ]
}

# What the CurseForge packager is told to leave out of a release. Reused here
# because "not part of the shipped addon" and "not wanted in the client" are the
# same question, and answering it twice is how two answers start disagreeing.
pkgmeta_ignores() {
  local meta="$1/.pkgmeta"
  [ -f "$meta" ] || return 0
  sed -e 's/\r$//' "$meta" \
    | sed -n '/^ignore:/,/^[^ -]/p' \
    | sed -n 's/^[[:space:]]*-[[:space:]]*//p'
}

total_copied=0
total_same=0
total_failed=0
total_considered=0

for addon in "${ADDON_NAMES[@]}"; do
  src="$ROOT/$addon"
  dst="$ADDONS/$addon"
  echo "== $addon"
  if [ ! -d "$src" ]; then
    echo "   no source folder at $src" >&2
    total_failed=$((total_failed + 1))
    continue
  fi

  manifest=()
  while IFS= read -r rel; do
    [ -n "$rel" ] && manifest+=("$rel")
  done < <(toc_manifest "$src")
  if [ "${#manifest[@]}" -eq 0 ]; then
    echo "   no .toc in $src -- nothing describes what this addon loads" >&2
    total_failed=$((total_failed + 1))
    continue
  fi

  ignores=()
  while IFS= read -r entry; do
    [ -n "$entry" ] && ignores+=("$entry")
  done < <(pkgmeta_ignores "$src")

  # The ignored paths are pruned inside find rather than filtered after it.
  # sounds/ alone holds hundreds of thousands of clips: walking it to throw the
  # result away takes minutes, and a step slow enough to be annoying is a step
  # that gets skipped.
  prune=()
  for entry in "${ignores[@]}"; do
    prune+=(-path "./$entry" -prune -o)
  done
  prune+=(-name '.*' -prune -o)
  # -mindepth 1 below keeps the starting directory out of these tests. Without
  # it the "." that find is handed matches -name ".*", the whole tree is pruned
  # on the first step, and the search returns nothing -- silently, and looking
  # exactly like an addon that happens to own no assets. It did precisely that
  # here, and the icon and the placeholder clips were quietly left behind.
  match=()
  for ext in "${ASSET_EXTENSIONS[@]}"; do
    [ "${#match[@]}" -gt 0 ] && match+=(-o)
    match+=(-name "*.$ext")
  done

  assets=()
  skipped_large=()
  while IFS= read -r -d '' rel; do
    rel=${rel#./}
    size=$(stat -c%s "$src/$rel")
    if [ "$size" -gt "$ASSET_MAX_BYTES" ]; then
      skipped_large+=("$rel ($((size / 1024)) KB)")
    else
      assets+=("$rel")
    fi
  done < <(cd "$src" && find . -mindepth 1 "${prune[@]}" -type f \( "${match[@]}" \) -print0)

  wanted=()
  while IFS= read -r rel; do
    [ -n "$rel" ] && wanted+=("$rel")
  done < <(printf '%s\n' "${manifest[@]}" "${assets[@]}" | sort -u)

  copied=0; same=0; failed=0
  for rel in "${wanted[@]}"; do
    total_considered=$((total_considered + 1))
    if [ ! -f "$src/$rel" ]; then
      # A .toc naming a file the folder does not hold stops the client loading
      # the addon at all, so it is an error here rather than a note.
      echo "   MISSING IN SOURCE   $rel" >&2
      failed=$((failed + 1))
      continue
    fi
    if [ -f "$dst/$rel" ] && cmp -s "$src/$rel" "$dst/$rel"; then
      same=$((same + 1))
      [ "$VERBOSE" = 1 ] && echo "   same                $rel"
      continue
    fi
    reason="changed"
    [ -f "$dst/$rel" ] || reason="new"
    if [ "$DRY_RUN" = 1 ]; then
      echo "   would copy, $reason  $rel"
      copied=$((copied + 1))
      continue
    fi
    if ! mkdir -p "$dst/$(dirname "$rel")"; then
      echo "   CANNOT MAKE FOLDER  $(dirname "$rel")" >&2
      failed=$((failed + 1))
      continue
    fi
    if ! cp -p "$src/$rel" "$dst/$rel"; then
      echo "   COPY FAILED         $rel" >&2
      failed=$((failed + 1))
      continue
    fi
    # Read back rather than trust the exit code. A copy onto a full disk, or one
    # the filesystem has buffered away, can report success while the old bytes
    # stay where they are -- and that outcome is indistinguishable from the
    # fault this script was written to end.
    if ! cmp -s "$src/$rel" "$dst/$rel"; then
      echo "   COPY DID NOT TAKE   $rel" >&2
      failed=$((failed + 1))
      continue
    fi
    echo "   copied, $reason      $rel"
    copied=$((copied + 1))
  done

  for entry in "${skipped_large[@]}"; do
    echo "   held back, too large $entry"
  done

  # A .lua sitting in the client that no .toc names is either dead or a file
  # somebody forgot to declare. The game loads neither, so it is reported and
  # left alone: deleting out of a live client is a bigger promise than an
  # install script should make.
  if [ -d "$dst" ]; then
    while IFS= read -r -d '' rel; do
      rel=${rel#./}
      if ! printf '%s\n' "${wanted[@]}" | grep -qxF -- "$rel"; then
        echo "   in the client, named by no .toc: $rel"
      fi
    done < <(cd "$dst" && find . -mindepth 1 -name '.*' -prune -o -type f -name '*.lua' -print0)
  fi

  echo "   $copied copied, $same already current, ${#skipped_large[@]} held back, $failed failed"
  total_copied=$((total_copied + copied))
  total_same=$((total_same + same))
  total_failed=$((total_failed + failed))
done

echo
# Nothing examined is not a pass. An empty run would otherwise print the same
# cheerful last line as a correct one, and that is the shape of every failure
# this file is a reaction to.
if [ "$total_considered" -eq 0 ]; then
  echo "install_dev: NOTHING WAS EXAMINED -- no .toc was read, so nothing was checked" >&2
  exit 1
fi
if [ "$total_failed" -gt 0 ]; then
  echo "install_dev: $total_failed problems -- the client is NOT current" >&2
  exit 1
fi
if [ "$DRY_RUN" = 1 ]; then
  echo "install_dev: dry run -- $total_copied files would change, $total_same already current"
  exit 0
fi
echo "install_dev: ok -- $total_copied copied, $total_same already current, $total_considered checked"
if [ "$total_copied" -gt 0 ]; then
  # The client reads a .lua once, as the addon loads. Until it is told to do that
  # again, the files on disk and the code running are two different things.
  echo "            /reload in game to pick the new files up"
fi
