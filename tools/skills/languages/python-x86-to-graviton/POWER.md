---
name: python-x86-to-graviton
displayName: "Python x86 to Graviton Migration"
description: "Validates Python application compatibility with AWS Graviton (ARM64) architecture by verifying that every pinned dependency (including transitive) publishes an aarch64 wheel for the project's interpreter, and by checking native extensions, vendored binaries, hash-locked requirements, Dockerfiles and architecture-specific code. Performs static analysis, applies ARM64-required dependency and build fixes, documents Graviton runtime recommendations, and validates install, import, tests and startup on ARM64."
keywords: ["python", "graviton", "arm64", "aarch64", "migration", "pip", "wheels", "native extensions", "dependencies"]
author: "AWS"
---

# Python Application AWS Graviton (ARM64) Compatibility Validation

Validate a Python application's readiness to run on AWS Graviton instances. This transformation verifies that every pinned dependency has an aarch64 wheel for the project's interpreter, identifies architecture-specific incompatibilities in native extensions, vendored binaries, build flags and code, updates only ARM64-blocking dependencies, and tests on ARM64.

[summaries.md](summaries.md) indexes every file in this skill and when to read it: consult it for the full file map, or if you entered mid-skill without reading this file top to bottom.

## Scope Guardrails

**CRITICAL: Read [document_references/agent-scope-boundaries.md](document_references/agent-scope-boundaries.md) before starting.** This file contains the decision tree for every dependency analysis and prevents scope creep.

**In scope:** aarch64 wheel availability for every pinned dependency (direct and transitive), ARM64-blocking dependency updates and lock regeneration, native extensions and vendored binaries, architecture detection code, x86-only build flags and Dockerfile platform settings, Graviton runtime recommendations (documented, never applied), ARM64 install/build/test validation.

**Out of scope:** Python version changes (unless `python.interpreter_bump` allows a bump that is the only path to an aarch64 wheel), package manager switches, base image changes, general dependency modernization, security updates, code refactoring, .gitignore/.dockerignore changes.

> **Verify the wheel on PyPI, never the version number.** Whether a pin installs on Graviton is a fact about the files published for that exact version, interpreter and glibc. Every verdict cites the probe output or the PyPI files list; see [document_references/wheel-verification.md](document_references/wheel-verification.md).

## Skill Configuration (Optional)

If a `skill-config.md` exists at the project root, read it before Phase 1 and apply its preferences (package manager, package index, validation interpreter tool, test command, container registry and runtime, deployment and CI vocabulary) as overrides; if absent, use the neutral defaults in the phase docs. The configuration steers HOW the transformation runs but cannot widen scope: `agent-scope-boundaries.md` still binds, and the project's declared Python version stays unchanged unless `python.interpreter_bump` allows a bump (a configured interpreter tool selects only the build/validation environment per Phase 3.0). See [document_references/skill-configuration.md](document_references/skill-configuration.md). Record any applied overrides in `01-project-assessment.md`.

## Entry Criteria

1. Python application currently running on x86 architecture
2. Source code and build scripts available
3. Current Python version documented (CPython 3.x; Phase 1.1 records where it was read from)
4. Build configs (requirements files, pyproject.toml/setup.py/setup.cfg, conda environment files, Dockerfiles if containerized)
5. ARM64 build/test environment access (Graviton EC2 or ARM64 containers; an x86 host with QEMU emulation can validate wheel installs, imports and tests, not source builds)
6. Complete dependency list with current versions (a lock file or exact pins), and access to the package index the project installs from
7. Existing test suite

## Transformation Workflow

### Version Control Setup

Initialize git if not already present. Commit after each meaningful step for traceability and rollback.

```bash
# Initialize if no git repo exists (local only, no remote required)
if [ ! -d ".git" ]; then
  git init
  git add -A
  git commit -m "Initial commit - baseline before ARM64 transformation"
fi
```

**Commit at each step that produces output or changes files.** Use `git add -A && git commit -m "<message>"` with descriptive messages. Typical commit points:

1. After documentation setup (graviton-validation/ folder created)
2. After Phase 1 static analysis complete (all analysis reports written)
3. After native library resolution (Phase 2.1 - vendored binaries rebuilt, extension flags fixed)
4. After dependency updates (Phase 2.2 - requirements, pyproject or environment files and locks changed)
5. After architecture code updates (Phase 2.3 - Python source and scripts changed)
6. After Dockerfile/build config updates (Phase 2.4)
7. After runtime recommendations (Phase 2.5)
8. After build validation (Phase 3.1 - install and build results documented)
9. After final validation and summary (Phase 3.3 + 00-summary.md written)

Not every project will have all steps (e.g., no Dockerfile changes for host-based deployments, no native library resolution if none found). Commit whenever files change, skip commits for steps that produced no changes. Virtual environments and wheel directories created for validation live outside the project tree (Phase 3.0), so `git add -A` never picks them up.

### Documentation Setup

Before Phase 1, create the output structure. See [document_references/documentation-standards.md](document_references/documentation-standards.md) for required sections and templates.

```bash
mkdir -p graviton-validation/raw
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
| `raw/site-packages-so-scan.txt` | 1.2 | every ELF file found by content, with its architecture |
| `raw/wheel-availability.txt` | 1.3 | One aarch64 wheel verdict per pin |
| `00-summary.md` | End | Executive summary and exit criteria |

### Phase 1: Static Compatibility Analysis

Analyze the project without making changes. See [phases/phase1-static-analysis.md](phases/phase1-static-analysis.md) for detailed steps; per-manager commands are in [document_references/package-manager-mapping.md](document_references/package-manager-mapping.md).

1. **1.1 Project Structure Analysis** - Deployment type, multi-module detection, package manager and interpreter detection, target OS/glibc, dependency tree generation, component risk categorization
2. **1.2 Native Library Validation** - Scan every committed or vendored native file by its content (not its name) for the target's architecture, C library, glibc and libstdc++ versions and page size, layers and in-repo extensions, binaries downloaded at run, build or deploy time, apply tiered FAIL/WARN/PASS policy
3. **1.3 Dependency ARM64 Compatibility** - Probe every resolved pin (including transitives) for an aarch64 wheel, check hash locks, classify as MUST UPGRADE / RECOMMENDED / COMPATIBLE
4. **1.4 Architecture-Specific Code Detection** - Find `platform.machine()` checks, ctypes/cffi loads, x86-only build flags and intrinsics, shell architecture gates, amd64 Dockerfile pins
5. **1.5 Python Version Check** - Document version and live support status (do NOT change it unless `python.interpreter_bump` allows; a change is one decision for the whole dependency set)

### Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues only. See [phases/phase2-resolution.md](phases/phase2-resolution.md) for detailed steps.

1. **2.1 Native Library Resolution** - Rebuild vendored binaries and extensions for aarch64 (on ARM64 hardware; plain C libraries can also be cross-compiled), re-vendor layers from aarch64 wheels, update loading logic
2. **2.2 Dependency Updates** - Update ONLY MUST UPGRADE dependencies to the lowest version with an aarch64 wheel, regenerate locks through the project's manager, substitute x86-only packages with user confirmation
3. **2.3 Architecture Code Updates** - Add `aarch64` handling to architecture detection code and scripts
4. **2.4 Build Config Updates** - Guard x86-only compiler flags, run Dockerfile `pip install` on `$TARGETPLATFORM` and drop amd64 pins (preserve current base images)
5. **2.5 Runtime Recommendations** - Document repo-sourced Graviton runtime settings with their evidence level; do not apply them

### Phase 3: ARM64 Validation & Testing

Build and test on ARM64. See [phases/phase3-validation.md](phases/phase3-validation.md) for detailed steps.

1. **3.0 Build Environment Prep** - Python runtime alignment (same minor version, pip >= 20.3; session-scoped only)
2. **3.1 Build Validation** - Install as the deployment does, build extensions, classify failures as INFRA/ARM64/PRE-EXISTING
3. **3.2 Functional Testing** - Import smoke test, loaded check against the x86 baseline, execute test suite, classify failures, determine final build
4. **3.3 Startup Validation** - Verify application starts on aarch64, aarch64 binaries load, no import or glibc errors
5. **Write 00-summary.md** - Consolidate exit criteria using template from documentation-standards.md

## Exit Criteria

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
11. All files in `graviton-validation/` using canonical names from documentation-standards.md

## Test Failure Handling

Infrastructure failures (missing database, services, credentials, network or package-index access) are non-blocking. Classify and document them, then run the final build without tests (the Phase 3.1 install and build, without the test step):
- pip, pip-tools, PEP 621: `python3 -m pip install --require-hashes -r requirements-locked.txt` (if the project has one), `python3 -m pip install -r requirements.txt`, then `python3 -m pip install .` for the project's own extensions
- uv: `uv sync --frozen`
- Poetry: `poetry sync`
- conda: `conda env create -f environment.yml`

ARM64 failures are blocking. Do not skip tests or packages; the failing build is the final build.

## User Responsibility (Post-Transformation)

- Performance benchmarking and load testing
- Integration testing with external services
- CI/CD pipeline configuration for ARM64 builds (if `skill-config.md` defines `ci.system`, phrase this recommendation in that system's vocabulary; the skill makes no CI changes itself)

## Notes

- ARM64 execution environment required for full validation. On x86 without a container runtime, static analysis only; under QEMU emulation, validate wheel installs, imports and tests, but build from source only on ARM64 hardware (see Phase 3 "Emulation limits").
- Monorepos with several Python packages require analysis of every package and its full resolved dependency set
- Run the bash blocks with bash 3.2 or later (the Phase 1.3 probe loop gave the same verdicts in bash 3.2.57, bash 5 and zsh 5.9). On macOS, where zsh is the default shell ([Apple](https://support.apple.com/en-us/102360)), start them with `bash`; on Windows, run the skill in a WSL 2 distribution, which runs a Linux kernel ([Microsoft](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)), with the project in the Linux file system
- Every Graviton vCPU maps to a physical core (no SMT), so performance scales more linearly with CPU load than on x86; load test to the maximum sustainable load before comparing instance types ([transition guide](https://github.com/aws/aws-graviton-getting-started/blob/main/transition-guide.md))
