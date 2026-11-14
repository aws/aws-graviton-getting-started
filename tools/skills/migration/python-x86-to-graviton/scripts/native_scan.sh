# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# shellcheck shell=bash
# Loaded with `. "$GV_PY_SKILL_DIR/scripts/native_scan.sh"` (bash or zsh) by the scan blocks of this skill: it defines
# native_scan and runs nothing.
# native_scan PATH...: every native file under PATH, found by its first bytes (not its name or extension), including
# members of zip archives (Lambda layer zips, vendored wheels, eggs) and of static archives (.a). Installed environments
# (directories with pyvenv.cfg or conda-meta) are skipped. Each Linux file is judged for the target in TARGET_ROOT (the
# image's files, Phase 1.1) or else TARGET_LIBC, TARGET_LIBC_VER and, when known, TARGET_GLIBCXX, with TARGET_PAGE_SIZE:
# FINDING, CHECK and NOTE lines, then "findings: N, checks: M"; exit status 1 on a FINDING, 2 when a PATH does not exist
# or the skill folder is not set. The program is scripts/native_scan.py in the folder that GV_PY_SKILL_DIR names.
native_scan() {
  case ${GV_PY_SKILL_DIR-} in
    /?*) [ -f "$GV_PY_SKILL_DIR/scripts/native_scan.py" ] || { echo "ERROR: no scripts/native_scan.py in $GV_PY_SKILL_DIR" >&2; return 2; } ;;
    *) echo "ERROR: GV_PY_SKILL_DIR is not an absolute path to the skill folder" >&2; return 2 ;;
  esac
  TARGET_LIBC="${TARGET_LIBC-}" TARGET_LIBC_VER="${TARGET_LIBC_VER-}" TARGET_PAGE_SIZE="${TARGET_PAGE_SIZE-}" \
    TARGET_GLIBCXX="${TARGET_GLIBCXX-}" TARGET_ROOT="${TARGET_ROOT-}" python3 "$GV_PY_SKILL_DIR/scripts/native_scan.py" "$@"
}
