# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# shellcheck shell=bash
# Loaded with `. scripts/run_arm64.sh` (bash or zsh) by the Phase 3 blocks of phase3-validation.md, after
# scripts/host_timeout.sh: it defines run_arm64 and runs nothing. run_arm64 needs host_timeout and CONTAINER_CMD.
run_arm64() {  # usage: run_arm64 <seconds> <image> <command...>; extra docker options go in RUN_ARM64_OPTS (a string)
  local limit="$1" img="$2" name="graviton-check-$$"; shift 2
  # The options go through $(printf) so that zsh splits them too (zsh does not split ${RUN_ARM64_OPTS}).
  # shellcheck disable=SC2046
  host_timeout "$((limit + 20))" $CONTAINER_CMD run --rm --init --name "$name" --platform linux/arm64 $(printf '%s' "${RUN_ARM64_OPTS:-}") \
    --entrypoint timeout "$img" "$limit" sh -c "$*"
  local rc=$?
  $CONTAINER_CMD rm -f "$name" >/dev/null 2>&1   # no-op if the container already exited
  return $rc
}
