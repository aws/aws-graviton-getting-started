# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# shellcheck shell=bash
# Loaded with `. "$GV_PY_SKILL_DIR/scripts/host_timeout.sh"` (bash or zsh) by the Phase 3 blocks of phase3-validation.md:
# it defines host_timeout and runs nothing.
# Host-side time limit: GNU timeout where it exists (Linux, WSL, Homebrew coreutils), else gtimeout, else Python in
# isolated mode (-I), which imports no module file from the current folder.
host_timeout() {  # usage: host_timeout <seconds> <command...>; exit code 124 on timeout, like timeout(1)
  if case "$(command -v timeout 2>/dev/null)" in /*) true;; *) false;; esac; then command timeout -k 10 "$@"   # the program: Phase 1 defines a shell function of that name with no limit
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout -k 10 "$@"
  else python3 -I -c 'import subprocess, sys
try: sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired: sys.exit(124)' "$@"
  fi
}
