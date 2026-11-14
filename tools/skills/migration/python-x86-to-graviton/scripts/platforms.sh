# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# shellcheck shell=bash
# Loaded with `. "$GV_PY_SKILL_DIR/scripts/platforms.sh"` (bash or zsh) by the probe blocks of phase1-static-analysis.md
# and wheel-verification.md: it defines platforms and runs nothing.
# platforms ARCH: sets PLAT to one --platform flag per wheel tag the target's libc (TARGET_LIBC, TARGET_LIBC_VER) accepts,
# newest first; pip matches each --platform value exactly.
platforms() { # $1=arch ; sets PLAT to one --platform flag per wheel tag the target's libc accepts, newest first
  local i="${TARGET_LIBC_VER#*.}"; PLAT=()
  case "$i" in ''|*[!0-9]*) i=99;; esac   # no version given: every tag; the wheel's tag names the version it needs
  if [ "$TARGET_LIBC" = musl ]; then
    while [ "$i" -ge 1 ]; do PLAT+=(--platform "musllinux_1_${i}_$1"); i=$((i - 1)); done
  else
    while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_$1"); i=$((i - 1)); done
    PLAT+=(--platform "manylinux2014_$1")
  fi
}
