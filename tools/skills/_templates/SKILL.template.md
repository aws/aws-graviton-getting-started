---
name: graviton-{{LANGUAGE}}-optimization
description: >
  Identifies and resolves {{LANGUAGE}} compatibility and performance issues
  when migrating workloads from x86_64 to AWS Graviton (ARM64/AArch64) processors.
metadata:
  author: "{{AUTHOR}}"
  version: "1.0"
---

# Graviton {{LANGUAGE_DISPLAY}} Optimization

## Goal

Analyze a {{LANGUAGE_DISPLAY}} project and produce a migration/optimization plan
for running on AWS Graviton (ARM64/AArch64) instances, covering:

1. **Dependency audit** — identify x86-specific or incompatible dependencies
2. **Build configuration** — ensure correct ARM64 compiler flags and targets
3. **Runtime configuration** — optimal JVM flags, runtime settings, etc.
4. **Performance validation** — benchmarks, profiling, and regression checks

## Context

AWS Graviton processors (Graviton2, Graviton3, Graviton4) are ARM64-based
and deliver better price-performance for most workloads. However, migrating
from x86_64 requires checking for:

- Native/binary dependencies compiled for x86 only
- Hardcoded architecture assumptions (e.g., SSE/AVX intrinsics)
- Build toolchain and CI/CD pipeline updates
- Language-specific runtime tuning for ARM64

Reference: https://github.com/aws/aws-graviton-getting-started

## Steps

### 1. Scan the project

- Identify the build system ({{BUILD_SYSTEMS}})
- List all dependencies, flagging any with native/binary components
- Check for architecture-specific code (inline assembly, SIMD intrinsics, etc.)

### 2. Check dependency compatibility

- For each native dependency, verify ARM64/AArch64 support
- Flag dependencies with no ARM64 build available
- Suggest alternatives where possible

### 3. Update build configuration

{{BUILD_CONFIG_INSTRUCTIONS}}

### 4. Update runtime configuration

{{RUNTIME_CONFIG_INSTRUCTIONS}}

### 5. Validate

- Build the project targeting `aarch64` / `arm64`
- Run the full test suite
- Compare performance metrics against x86_64 baseline
- Check for correctness regressions (especially floating-point edge cases)

### 6. Generate migration report

Write every report to `graviton-validation/{{SKILL_NAME}}/` at the project root, so the reports of two skills run on one repository stay apart. Produce a summary, `00-summary.md`, with:
- Compatible dependencies
- Dependencies requiring updates
- Blockers (no ARM64 support)
- Recommended Graviton instance type (c8g, m8g, r8g, etc.)
- Estimated performance delta (if benchmarks were run)

## Available Scripts

Code this skill runs lives in `scripts/` ([Agent Skills specification](https://agentskills.io/specification), "scripts/"): the agent runs it and does not read it into context.

- `scripts/{{SCRIPT}}`: {{WHAT_THE_SCRIPT_DOES}}

A block that runs a script names the skill folder on its first line and runs nothing unless that line is an absolute path to a folder that holds the script:

```bash
GV_SKILL_DIR=   # the folder that holds this SKILL.md
if case $GV_SKILL_DIR in /?*) [ -f "$GV_SKILL_DIR/scripts/{{SCRIPT}}" ];; *) false;; esac; then
  python3 "$GV_SKILL_DIR/scripts/{{SCRIPT}}" {{ARGUMENTS}}
else echo "ERROR: set GV_SKILL_DIR on the first line to the folder that holds this SKILL.md"; fi
```

Each script starts with the license header, after its shebang line:

```
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
```
