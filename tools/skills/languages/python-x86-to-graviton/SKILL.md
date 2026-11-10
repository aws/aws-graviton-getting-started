---
name: python-x86-to-graviton
description: Validates Python application compatibility with AWS Graviton (ARM64) architecture by verifying that every pinned dependency (including transitive) publishes an aarch64 wheel for the project's interpreter, and by checking native extensions, vendored binaries, hash-locked requirements, Dockerfiles and architecture-specific code. Performs static analysis, applies ARM64-required dependency and build fixes, documents Graviton runtime recommendations, and validates install, import, tests and startup on ARM64. Supports pip, pip-tools, PEP 621/setuptools, uv, Poetry and conda, with mappings for Pipenv, PDM, Hatch and vendored or Lambda layer layouts. Use whenever a Python workload is to run on Graviton (arm64), to assess or migrate it, even if the skill is not named; also for diagnosing wheel and native-library failures on aarch64.
metadata:
  author: AWS
  version: "1.0"
---

# Python Application AWS Graviton (ARM64) Compatibility Validation

Validate a Python application's readiness to run on AWS Graviton instances. This transformation verifies that every pinned dependency has an aarch64 wheel for the project's interpreter, identifies architecture-specific incompatibilities in native extensions, vendored binaries, build flags and code, updates only ARM64-blocking dependencies, and tests on ARM64.

[summaries.md](summaries.md) indexes every file in this skill and when to read it: consult it for the full file map, or if you entered mid-skill without reading this file top to bottom.

## Scope Guardrails

**CRITICAL: Read [references/agent-scope-boundaries.md](references/agent-scope-boundaries.md) before starting.** This file contains the decision tree for every dependency analysis and prevents scope creep.

**In scope:** aarch64 wheel availability for every pinned dependency (direct and transitive), ARM64-blocking dependency updates and lock regeneration, native extensions and vendored binaries, architecture detection code, x86-only build flags and Dockerfile platform settings, Graviton runtime recommendations (documented, never applied), CI changes that only add or switch an architecture, ARM64 install/build/test validation.

**Out of scope:** Python version changes (unless `python.interpreter_bump` allows a bump that is the only path to an aarch64 wheel), package manager switches, base image changes, general dependency modernization, security updates, code refactoring, .gitignore/.dockerignore changes.

> **Verify the wheel on PyPI, never the version number.** Whether a pin installs on Graviton is a fact about the files published for that exact version, interpreter and glibc. Every verdict cites the probe output or the PyPI files list; see [references/wheel-verification.md](references/wheel-verification.md).

## Skill Configuration (Optional)

If a `skill-config.md` exists at the project root, read it before Phase 1 and apply its preferences (package manager, package index, validation interpreter tool, test command, container registry and runtime, deployment and CI vocabulary, target hosts and images) as overrides; if absent, use the neutral defaults in the phase docs. The configuration steers HOW the transformation runs but cannot widen scope: `agent-scope-boundaries.md` still binds, and the project's declared Python version stays unchanged unless `python.interpreter_bump` allows a bump (a configured interpreter tool selects only the build/validation environment per Phase 3.0). See [references/skill-configuration.md](references/skill-configuration.md) for the fields, and [references/skill-config.template.md](references/skill-config.template.md) for a file to start from. Record any applied overrides in `01-project-assessment.md`.

## Entry Criteria

1. Python application currently running on x86 architecture
2. Source code and build scripts available
3. Current Python version documented (CPython 3.x; Phase 1.1 records where it was read from)
4. Build configs (requirements files, pyproject.toml/setup.py/setup.cfg, conda environment files, Dockerfiles if containerized)
5. ARM64 build/test environment access (Graviton EC2 or ARM64 containers; an x86 host with QEMU emulation can validate wheel installs, imports and tests, not source builds)
6. Complete dependency list with current versions (a lock file or exact pins), and access to the package index the project installs from
7. Existing test suite
8. Tools the commands call: git, curl, `python3` with pip and the project's package manager, and a container runtime (Phase 1.1, the OS-package check of §1.2.2, and Phase 3); the image check (Phase 1.4) uses the docker CLI

## Transformation Workflow

**Assessment only:** when the user asks for an assessment, or for the project to stay unchanged, skip Version Control Setup, run Phase 1 and stop. First read [references/phase1-static-analysis.md](references/phase1-static-analysis.md) in full, then run the blocks that apply, in order: the verdicts come from the checks those blocks run, and your own inspection of binaries or package files does not replace them. A `CHECK` those blocks print stays a `CHECK` in the report, never a PASS, with the step that settles it. Phase 1 changes none of the project's existing files; it writes the reports Documentation Setup lists to a new `graviton-validation/python-x86-to-graviton/` folder, `00-summary.md` last. Report what Phases 2 and 3 would change or run as recommendations, each with its default.

Copy this checklist into your response and check off each step:

```
ARM64 migration progress:
- [ ] Baseline commit; `graviton-validation/python-x86-to-graviton/raw/` created; `skill-config.md` read if present
- [ ] 1.1 Deployment type, package manager and interpreter, target OS and glibc, resolved pins (01, raw/)
- [ ] 1.2 Native files judged by content (02)
- [ ] 1.3 Each pin probed: MUST UPGRADE / RECOMMENDED UPGRADE / COMPATIBLE / CHECK (03)
- [ ] 1.4 Architecture code, build flags, images, deployment settings (04)
- [ ] 1.5 Python version recorded with its support status, not changed (01)
- [ ] 2.1 Vendored binaries and extensions built for aarch64 (02)
- [ ] 2.2 Only MUST UPGRADE pins updated, then the Phase 1 probe and scan re-run (03)
- [ ] 2.3 Architecture detection code updated (04)
- [ ] 2.4 Build flags, Dockerfiles and deployment settings updated (04)
- [ ] 2.5 Runtime recommendations documented, not applied (05)
- [ ] 3.0-3.1 ARM64 install and build; failures classified INFRA / ARM64 / PRE-EXISTING (06)
- [ ] 3.2 Imports, the loaded check and tests on ARM64, results that change without failing (06)
- [ ] 3.3 Startup on ARM64 (06)
- [ ] 00-summary.md: each exit criterion with where it ran
```

### Version Control Setup

Initialize git if not already present:

```bash
# Initialize if no git repo exists (local only, no remote required)
if [ ! -d ".git" ]; then
  git init
  git add -A
  git commit -m "Initial commit - baseline before ARM64 transformation"
fi
```

**Commit after each checklist step that changes files** with `git add -A && git commit -m "<message>"`, the message naming the step; skip the commit when a step changed nothing. Virtual environments and wheel directories created for validation live outside the project tree (Phase 3.0), so `git add -A` never picks them up. A dry run or an install of `.` with setuptools writes `<name>.egg-info/` into the project, and the install also writes `build/`: if the repository does not ignore them, stage the changed files by name instead of `git add -A` (adding a `.gitignore` is out of scope).

### Documentation Setup

Before Phase 1, create the output structure. See [references/documentation-standards.md](references/documentation-standards.md) for required sections and templates.

Report a check as run, or a result as observed, only when you ran the command in this session, and name the command or its output file in `raw/`; a check you did not run is NOT RUN. When several versions were checked, list the ones checked, not a range, unless every version in the range was checked. Take every count in the reports (versions, files, findings, packages) from a command's output, not from reading. A `FINDING` keeps its label in every report and in the final answer; say whether the project's code reaches it only from a run that shows it. Say that a file passes the check for a target, not that it loads there, unless a run loaded it.

Set `GV_PY_SKILL_DIR` on the first line to the absolute path of the folder that holds this `SKILL.md`, then run this block once, from the project root. Left empty, the block looks for the skill only where user-level installs put skills (folders such as `~/.claude/skills`, `~/.agents/skills` and `~/.config/goose/skills`), never inside the project, and prints the folder it uses. Every later block that runs one of this skill's scripts starts with `GV_PY_SKILL_DIR=`: put that folder there each time. The blocks run only the scripts in that folder and never take a program path from a file in the project, so a project under analysis cannot point them at code of its own:

```bash
GV_PY_SKILL_DIR=   # the absolute path of the folder that holds this SKILL.md
GV_PY_SKILL_DIR=${GV_PY_SKILL_DIR%/SKILL.md}   # the folder, also when the line names the file
GV_PROJECT=$(pwd -P)
if [ -z "$GV_PY_SKILL_DIR" ]; then   # not given: look where user-level installs put skills, never inside the project
  GV_FOUND=$( { find "$HOME" -mindepth 1 -maxdepth 1 -type d -name '.*'; find "$HOME/.config" -mindepth 1 -maxdepth 1 -type d; } 2> /dev/null | sort -u |
    while IFS= read -r p; do [ -f "$p/skills/python-x86-to-graviton/scripts/native_scan.py" ] || continue
      p=$(CDPATH= cd -- "$p/skills/python-x86-to-graviton" && pwd -P) || continue; case $p/ in "$GV_PROJECT"/*) ;; *) printf '%s\n' "$p";; esac; done)
  GV_PY_SKILL_DIR=$(printf '%s\n' "$GV_FOUND" | head -n 1)
  [ "$(printf '%s\n' "$GV_FOUND" | grep -c .)" -le 1 ] || echo "NOTE: other copies: $(printf '%s\n' "$GV_FOUND" | sed 1d | tr '\n' ' ')(set GV_PY_SKILL_DIR if the SKILL.md you follow is in one of them)"
fi
mkdir -p graviton-validation/python-x86-to-graviton/raw
if [ -n "$GV_PY_SKILL_DIR" ] && [ -f "$GV_PY_SKILL_DIR/scripts/native_scan.py" ] && GV_PY_SKILL_DIR=$(CDPATH= cd -- "$GV_PY_SKILL_DIR" && pwd -P); then
  echo "skill folder: $GV_PY_SKILL_DIR"
  case $GV_PY_SKILL_DIR/ in "$GV_PROJECT"/*) echo "NOTE: the skill folder is inside the project, so the scripts it runs are files of the project: use it only on a project you trust";; esac
else echo "ERROR: scripts/native_scan.py not found: set GV_PY_SKILL_DIR to the folder that holds this SKILL.md and rerun, or reinstall the whole skill folder"; fi
```

Output files produced:

| File | Phase | Purpose |
|------|-------|---------|
| `01-project-assessment.md` | 1.1, 1.5 | Project structure, deployment type, package manager(s), Python environment, target OS/glibc |
| `02-native-library-report.md` | 1.2, 2.1 | Native extensions, vendored binaries, runtime library loads, layers |
| `03-dependency-compatibility-report.md` | 1.3, 2.2 | Per-dependency aarch64 wheel verdicts |
| `04-code-scan-findings.md` | 1.4, 2.3, 2.4 | Architecture-specific code, build flags, Dockerfile platform issues |
| `05-runtime-configuration.md` | 2.5 | Graviton runtime recommendations (documented, not applied) |
| `06-build-test-results.md` | 3.0-3.3 | Install, build, test results, startup checks |
| `raw/dependency-tree-full.txt` | 1.1 | Raw dependency tree (`.json` for a pip report) |
| `raw/requirements-resolved.txt` | 1.1, 1.3 | Flat pinned list the probe runs on |
| `raw/site-packages-so-scan-<target>.txt` | 1.2 | every ELF file found by content, with its architecture |
| `raw/wheel-availability.txt` | 1.3 | One aarch64 wheel verdict per pin |
| `00-summary.md` | End | Executive summary and exit criteria |

### Available Scripts

- **`scripts/native_scan.py`**: judges every native file under the paths it is given by its content, for the target OS of Phase 1.1: ELF, Mach-O and PE files on disk, in zip archives (wheels, Lambda layer zips, eggs) and in static archives. Needs Python 3.6 or later only and reads files only; exit status 1 means a `FINDING`. The blocks run it through `native_scan`; do not copy or rewrite it.
- **`scripts/native_scan.sh`**, **`scripts/platforms.sh`** and **`scripts/host_timeout.sh`**: shell functions that the blocks load with `.` (bash or zsh); loading them runs nothing. `native_scan PATH...` runs `native_scan.py` with the target variables (`TARGET_ROOT`, or `TARGET_LIBC`, `TARGET_LIBC_VER`, `TARGET_GLIBCXX`, `TARGET_PAGE_SIZE`); `platforms ARCH` sets `PLAT` to one `--platform` flag per wheel tag the target's libc accepts; `host_timeout <seconds> <command...>` bounds a command on the host (exit status 124 on timeout, like `timeout`).

### Phase 1: Static Compatibility Analysis

Analyze the project without changing its source or build files. Read [references/phase1-static-analysis.md](references/phase1-static-analysis.md) before starting; per-manager commands are in [references/package-manager-mapping.md](references/package-manager-mapping.md).

1. **1.1 Project Structure Analysis** - Deployment type, multi-module detection, package manager and interpreter detection, target OS/glibc from each image's files, dependency tree generation, component risk categorization
2. **1.2 Native Library Validation** - Scan every committed or vendored native file by its content (not its name) for the target's architecture, C library, glibc and libstdc++ versions and page size, layers and in-repo extensions, binaries downloaded at run, build or deploy time, apply tiered FAIL/WARN/PASS policy
3. **1.3 Dependency ARM64 Compatibility** - Probe every resolved pin (including transitives) for an aarch64 wheel, check hash locks, classify as MUST UPGRADE / RECOMMENDED UPGRADE / COMPATIBLE (CHECK until the evidence decides)
4. **1.4 Architecture-Specific Code Detection** - Find `platform.machine()` checks, ctypes/cffi loads, x86-only build flags and intrinsics, shell architecture gates, amd64 Dockerfile pins, and deployment settings that pick x86, set or absent
5. **1.5 Python Version Check** - Document version and live support status (do NOT change it unless `python.interpreter_bump` allows; a change is one decision for the whole dependency set)

### Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues only. Read [references/phase2-resolution.md](references/phase2-resolution.md) before starting.

1. **2.1 Native Library Resolution** - Rebuild vendored binaries and extensions for aarch64 (on ARM64 hardware; plain C libraries can also be cross-compiled), re-vendor layers from aarch64 wheels, update loading logic
2. **2.2 Dependency Updates** - Update ONLY MUST UPGRADE dependencies to the lowest version with an aarch64 wheel, regenerate locks through the project's manager, substitute x86-only packages with user confirmation
3. **2.3 Architecture Code Updates** - Add `aarch64` handling to architecture detection code and scripts
4. **2.4 Build Config Updates** - Guard x86-only compiler flags, run Dockerfile `pip install` on `$TARGETPLATFORM` and drop amd64 pins (preserve current base images)
5. **2.5 Runtime Recommendations** - Document repo-sourced Graviton runtime settings with their evidence level; do not apply them

### Phase 3: ARM64 Validation & Testing

Build and test on ARM64. Read [references/phase3-validation.md](references/phase3-validation.md) before starting.

1. **3.0 Build Environment Prep** - Python runtime alignment (same minor version, pip >= 20.3; session-scoped only)
2. **3.1 Build Validation** - Install as the deployment does, build extensions, classify failures as INFRA/ARM64/PRE-EXISTING
3. **3.2 Functional Testing** - Import smoke test, loaded check against the x86 baseline, execute test suite, classify failures, check results that can differ by architecture, determine final build
4. **3.3 Startup Validation** - Verify application starts on aarch64, aarch64 binaries load, no import or glibc errors
5. **Write 00-summary.md** - Consolidate exit criteria using template from documentation-standards.md

## Exit Criteria

A criterion that runs on ARM64 passes only on a Graviton host or the target, such as the arm64 Lambda function; one that ran only under emulation or on another arm64 machine is NOT RUN (Phase 3, "Match the production hosts").

### Must Pass
1. Dependencies install on ARM64 from wheels or documented source builds
2. Native extensions and vendored binaries build or load on ARM64 (or documented fallbacks function)
3. All MUST UPGRADE dependencies updated to ARM64-compatible versions, or documented as user decisions
4. No ARM64-specific runtime errors; every native package imports
5. Container images build on ARM64 (if containerized)

### Test Criteria
6. Test suite executes on ARM64
7. Failures classified: `INFRA` (non-blocking) / `ARM64` (blocking) / `PRE-EXISTING` (non-blocking)
8. No ARM64-related test failures

### Startup Criteria
9. Application starts on ARM64 without crashes (`platform.machine()` reports `aarch64`)
10. Python version unchanged, or changed only through an approved `python.interpreter_bump`

### Documentation Criteria
11. All files in `graviton-validation/python-x86-to-graviton/` using canonical names from documentation-standards.md

## Test Failure Handling

Infrastructure failures (missing database, services, credentials, network or package-index access, or one that fails the same way on the x86 baseline) are non-blocking: deselect only those tests (for pytest, `--deselect <test id>`), list them under CHECK Items, and take that run as the final build (Phase 3.1, Build Strategy step 3). A build that skips every test is never the final build.

ARM64 failures are blocking. Do not skip tests or packages; the failing build is the final build.

## User Responsibility (Post-Transformation)

- Performance benchmarking and load testing
- Integration testing with external services
- CI/CD changes beyond architecture (credentials, deployment steps, triggers, tool versions), recommended in the vocabulary of `ci.system` when `skill-config.md` defines it; changes that only add or switch an architecture are applied in Phase 2.4 unless `ci.changes` is `recommend`

## Notes

- ARM64 execution environment required for full validation. On x86 without a container runtime, static analysis only; under QEMU emulation, validate wheel installs, imports and tests, but build from source only on ARM64 hardware (see Phase 3 "Emulation limits").
- Monorepos with several Python packages require analysis of every package and its full resolved dependency set
- Run the bash blocks with bash 3.2 or later (the Phase 1.3 probe loop gave the same verdicts in bash 3.2.57, bash 5 and zsh 5.9). On macOS, where zsh is the default shell ([Apple](https://support.apple.com/en-us/102360)), start them with `bash`; on Windows, run the skill in a WSL 2 distribution, which runs a Linux kernel ([Microsoft](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)), with the project in the Linux file system
- Every Graviton vCPU maps to a physical core (no SMT, [AWS Graviton performance testing](https://docs.aws.amazon.com/whitepapers/latest/aws-graviton-performance-testing/other-considerations.html)), so performance scales more linearly with CPU load than on x86; load test to the maximum sustainable load before comparing instance types
