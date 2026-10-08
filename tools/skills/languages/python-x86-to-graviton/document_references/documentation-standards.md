# ARM64 Transformation — Documentation Standards

## Purpose

This document defines the output folder, canonical filenames and required content for every report produced during a Python Graviton compatibility transformation, so that two runs by different agents produce comparable results and a reviewer can audit each verdict back to its evidence.

## Output Folder Structure

All output goes into one folder, `graviton-validation/`, at the project root. Create it and its `raw/` subfolder before any analysis.

```
<project-root>/
└── graviton-validation/
    ├── 00-summary.md                         # Roll-up of findings and exit criteria (written last)
    ├── 01-project-assessment.md              # Deployment type, package manager(s), interpreter, target OS/glibc, config overrides
    ├── 02-native-library-report.md         # In-repo extensions, vendored binaries, ctypes/cffi loads, Lambda layers
    ├── 03-dependency-compatibility-report.md # Per-dependency aarch64 verdicts with wheel evidence
    ├── 04-code-scan-findings.md              # Architecture detection, build flags, shell scripts, Dockerfile platform issues
    ├── 05-runtime-configuration.md           # Graviton improvements (document-only), each with its evidence level
    ├── 06-build-test-results.md              # ARM64 install, import smoke test, test results, startup checks
    └── raw/                                  # Machine-generated artefacts, never hand-edited
        ├── dependency-tree-full.txt          # Manager-native tree, or .json for a pip report (Phase 1.1)
        ├── requirements-resolved.txt         # Flat pinned list the probe ran on (Phase 1.3)
        ├── wheel-availability.txt            # Probe output, one verdict line per pin (Phase 1.3)
        └── site-packages-so-scan.txt         # every ELF file found by content, with its architecture (Phase 1.2)
```

## Agent Instructions

1. **Create `graviton-validation/` and `graviton-validation/raw/` first.** `mkdir -p graviton-validation/raw` is the first action of Phase 1.
2. **Use exactly these filenames.** Do not rename, renumber or add top-level files. Additional machine output goes under `raw/` with a descriptive name.
3. **Write progressively.** Each phase step writes its section as it completes; do not batch everything at the end.
4. **Every verdict cites its evidence.** A dependency row without a probe command and a wheel filename (or a `from versions:` list, or a PyPI files-list observation) is incomplete. The "validated by" and "evidence" columns below are mandatory.
5. **Three labels, kept apart.** Findings are MUST UPGRADE, RECOMMENDED UPGRADE or COMPATIBLE (plus OUT OF SCOPE notes). Never list a recommendation among required changes, and never apply one. A finding that waits for a user decision, or for evidence Phase 1 cannot produce (a CHECK line of the Phase 1.3 loop), is CHECK until it gets one of the three labels: list user decisions under User Decisions Pending with the label each option leads to.
6. **Empty sections stay, with "No findings".** Omitting a section is ambiguous (not checked, or nothing found?). Write the heading and an explicit statement.
7. **`00-summary.md` is written last** and references the detail files rather than repeating them.
8. **Nothing outside `graviton-validation/`.** No other documentation files are created by the transformation.

## File Specifications

### `00-summary.md` — Transformation Summary

**Created:** end of Phase 3.
**Purpose:** one page a reviewer reads first; maps to the exit criteria in SKILL.md.

```markdown
# ARM64 Compatibility Validation — Summary

## Project Overview
- **Project:** <name>
- **Deployment type:** Containerized | Host-based | Lambda | Both
- **Package manager(s):** <pip (requirements.txt) | pip-tools | setuptools/PEP 621 | uv | Poetry | conda | mapped: Pipenv/PDM/Hatch/vendored> (authoritative one marked)
- **Interpreter:** <3.X.Y, source of the decision>
- **Target OS / glibc:** <image or AMI, glibc version>
- **Skill config applied:** none | <fields>
- **Date:** <ISO 8601>

## Exit Criteria Checklist
| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Dependencies install on ARM64 from wheels or documented source builds | ✅ PASS / ❌ FAIL | |
| 2 | Native extensions and vendored binaries build or load on ARM64 (or documented fallbacks function) | ✅ PASS / ❌ FAIL / N/A / NOT RUN | |
| 3 | Blocking dependency updates applied, or documented as user decisions | ✅ PASS / ❌ FAIL | |
| 4 | No ARM64-specific runtime errors; every native package imports | ✅ PASS / ❌ FAIL | |
| 5 | Container image builds for linux/arm64 | ✅ PASS / ❌ FAIL / N/A / NOT RUN | |
| 6 | Test suite executes on ARM64 | ✅ PASS / ❌ FAIL | |
| 7 | Failures classified as INFRA / ARM64 / PRE-EXISTING | ✅ PASS / ❌ FAIL | |
| 8 | No ARM64-related test failures | ✅ PASS / ❌ FAIL | |
| 9 | Application starts on ARM64 (`platform.machine()` reports aarch64) | ✅ PASS / ❌ FAIL | |
| 10 | Python version unchanged, or changed only through an approved `python.interpreter_bump` | ✅ PASS / ❌ FAIL | |
| 11 | All files in `graviton-validation/` use the canonical names | ✅ PASS / ❌ FAIL | |

NOT RUN is only for a check that needs ARM64 hardware the run did not have (for example an image build that does not finish under emulation); give the reason in Notes and list the check under Remaining Concerns.

## Changes Made
<Short list; link to 02, 03, 04 for detail>

## Recommendations Recorded (Not Applied)
<Count and link to 05>

## Remaining Concerns
<Unresolved items, substitutions awaiting confirmation, glibc/OS decisions, interpreter blockers>
```

### `01-project-assessment.md` — Project & Environment Assessment

**Created:** Phase 1.1 and 1.5.

```markdown
# Project Assessment

## Deployment Type
<Containerized | Host-based | Lambda | Both>, with evidence (Dockerfile path, systemd unit, SAM template, Procfile)

## Project Structure
| Manager | Marker files | Lock file | Authoritative for deployment? | Export command used |
|---|---|---|---|---|
| pip | requirements.txt, requirements-locked.txt | requirements-locked.txt (hashed) | Yes (Dockerfile RUN pip install) | n/a (already flat) |

Monorepo / multiple packages: <No | Yes, list each package and its manager>

## Python Environment
- **Version:** <3.X.Y>
- **Decided from:** <Dockerfile FROM python:3.11-slim | .python-version | requires-python | Pipfile | environment.yml | CI>
- **Origin and pip:** <official image | distribution package | uv / pyenv / mise / asdf | conda>, pip <version>
- **Support status:** <bugfix | security | end-of-life on YYYY-MM-DD, from https://devguide.python.org/versions/ fetched YYYY-MM-DD>
- **Policy applied:** `python.interpreter_bump` = never | ask | approved=<3.X>; outcome: unchanged | bump approved to <3.X> because <sole path to aarch64 wheel for X>; evaluated across all pins (03 report, Interpreter-ABI Blockers)

## Target OS and glibc
- **Base image / AMI:** <python:3.11-slim (Debian 13) | amazonlinux:2023 | ...>
- **libc:** <glibc 2.41 | musl 1.2>, measured by <the Phase 1.1 probe in the image | the Lambda runtime | repo table in wheel-verification.md section 7>
- **Highest wheel tag accepted:** manylinux_2_<N> | musllinux_1_<N>
- **Kernel page size on the deployment hosts:** <4KB | 64KB | unknown>, from <`getconf PAGESIZE` on <host> | the team that runs the hosts>
- **Graviton generations deployed:** <e.g. Graviton2 and Graviton4 | unknown>; oldest: <generation>
- **pip on target:** <version>; >= 20.3 required for current aarch64 wheels, which carry `manylinux_2_N` tags (19.3 sees only `manylinux2014`) (upgrade recorded if applied)

## Private Index / Mirror
<none | URL (from skill-config python.index_url or pip.conf); aarch64 coverage checked: yes/no>

## Skill Configuration Overrides Applied
<none | field: value, effect>

## Component Risk Categorization
| Component | Risk | Rationale |
|---|---|---|
| vendor/*.so | CRITICAL | committed x86-64 binaries |
| numpy/pandas/pillow | LOW | aarch64 wheels verified |
```

### `02-native-library-report.md` — Native Library Analysis & Resolution

**Created:** Phase 1.2, updated in Phase 2.1.

```markdown
# Native Library Report

## Statically Bundled Libraries
| Library | Location | Architecture (ELF header) | aarch64 build present (confirmed by the scan) | Verdict | Resolution |
|---|---|---|---|---|---|
| libfastsum-x86_64.so | vendor/ | e_machine 62 (x86-64) | No | WARN (source in native/) | rebuilt from native/fastsum.c for aarch64 |
| <name>.so | Lambda layer or vendored site-packages (<package>==<version>) | <architecture> | <yes/no> | <verdict> | <resolution> |

## Runtime-Extracted Libraries
| Source | Artifact | Downloads or unpacks native code | aarch64 support in current version | Verdict | Resolution |
|---|---|---|---|---|---|
| scripts_deploy.sh:5 | tool-linux-amd64 | Yes (curl at deploy time) | not confirmed | WARN | arm64 asset not confirmed (user decision) |

## In-Repo Extension Modules
| Build definition | Module | Language / tool | x86-only flags or headers | Verdict | Resolution |
|---|---|---|---|---|---|
| setup.py | _fixture_ext | C via setuptools | -mavx2, -march=haswell; immintrin.h (guarded) | WARN (source present) | flags arch-guarded (Phase 2.4); rebuilt on aarch64 hardware |

## Resolution Details
<For each FAIL or WARN, describe the resolution approach.> FAIL: x86-only binary with no aarch64 build path and no source. WARN: source available or pure-Python fallback exists. PASS: aarch64 binary present or built.

## Pure Python Fallbacks Documented
<List any library where a pure-Python fallback path was chosen instead of native resolution, for example the fixture's `fast_sum`, which falls back to `sum()` when the native load fails; record that the fallback is slower.>

## No Findings
<If nothing was found:> No bundled or runtime-extracted native libraries, in-repo extensions or layers detected. All native code arrives through PyPI wheels (see 03).
```

### `03-dependency-compatibility-report.md` — Dependency ARM64 Compatibility

**Created:** Phase 1.3, updated in Phase 2.2. The primary report.

```markdown
# Dependency ARM64 Compatibility Report

Interpreter probed: cp3XY. Target libc: <glibc 2.NN | musl 1.N> (every manylinux or musllinux tag up to it offered). Index: PyPI | <mirror>. Probe date: YYYY-MM-DD.

## MUST UPGRADE (Blocking)
| Dependency | Direct / via | Pinned | Issue | Evidence | Minimum aarch64 version (this cp tag) | Applied | Mechanism |
|---|---|---|---|---|---|---|---|
| blosc2 | direct | 0.6.3 | no cp311 aarch64 wheel; x86_64 wheel exists | probe -> `from versions: 0.6.4, ...`; `blosc2-0.6.3-cp311-...x86_64.whl` | 0.6.4 (`blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`) | 0.6.4 | requirements.txt pin |
| mkl | direct | 2026.1.0 | x86-only by nature (no aarch64 file in any release) | PyPI files list | none | removed (user confirmed) | requirements.txt |
| requirements-locked.txt | lock | charset-normalizer 3.4.0, MarkupSafe 2.1.5 | x86_64 hashes only | `--require-hashes` dry run: Expected sha256 ... Got ... | n/a | aarch64 hashes added | pip hash |

## User Decisions Pending
| Dependency | Pinned | Options | Recommendation |
|---|---|---|---|
| pygeos | 0.14 | (a) build the sdist on Graviton with `libgeos-dev`, `setuptools<82` as a build constraint and, with gcc 14, `CFLAGS=-Wno-error=incompatible-pointer-types`; (b) move to `shapely>=2.0` (API change, out of scope to apply) | (a), the smaller change; (b) if the team plans the Shapely 2 migration anyway |

## RECOMMENDED UPGRADE (Non-Blocking)
| Dependency | Pinned | Recommended version | Reason | Evidence level | Action taken |
|---|---|---|---|---|---|
| <dep> | <ver> | <ver> | documented Graviton improvement (source) | A or B | Documented for user |

## COMPATIBLE (No Action Needed)
| Dependency | Direct / via | Pinned | Basis (wheel filename or pure-Python evidence) |
|---|---|---|---|
| numpy | direct | 1.26.4 | `numpy-1.26.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`; >= 1.21.1 correctness floor |
| six | direct | 1.11.0 | `six-1.11.0-py2.py3-none-any.whl`; modernisation out of scope |
| docopt | direct | 0.6.2 | sdist only, no compiled sources |

## Transitive Dependency Resolutions
| Transitive | Pulled in by | Issue | Mechanism used |
|---|---|---|---|
| intel-openmp, tbb | mkl | x86-only | removed with mkl |

## Interpreter-ABI Blockers (Not Architecture)
| Dependency | Pinned | aarch64 wheels exist for | Project interpreter | Handling per interpreter_bump |
|---|---|---|---|---|

Interpreter decision, one for the whole dependency set (Phase 1.5), one row per interpreter evaluated:
| Interpreter | Pins probed | Not COMPATIBLE at this interpreter | Lowest fixing versions | Chosen |
|---|---|---|---|---|
| 3.11 (declared) | 18 | none after the Phase 2 fixes | n/a | yes |
| 3.12 | 18 | blosc2==0.6.4, shapely==2.0.0 (no cp312 wheel) | blosc2 2.2.8, shapely 2.0.2 | no |
```

### `04-code-scan-findings.md` — Architecture-Specific Code Detection

**Created:** Phase 1.4, updated in Phase 2.3 and 2.4.

```markdown
# Architecture-Specific Code Scan

## Architecture Detection Patterns Found
| File:line | Pattern | aarch64 handling present | Action |
|---|---|---|---|
| app/service.py:19 | platform.machine() == "x86_64" | No | aarch64 branch added |

## ctypes / cffi Usage
| File:line | Call | Library | aarch64 validated | Action |
|---|---|---|---|---|
| app/service.py:29 | ctypes.CDLL(path) | libfastsum | No (path chosen by an x86-only check) | aarch64 branch added; libfastsum-aarch64.so loaded in Phase 3 |

## Shell Scripts, Makefiles, CI
| File:line | Pattern | Action |
|---|---|---|
| scripts_deploy.sh:4 | uname -m != x86_64 exits | arm64 branch added; arm64 asset not confirmed (user decision) |

## Build Flags and Intrinsics
| File:line | Flag / header | Guarded | Action |
|---|---|---|---|
| setup.py:8 | -mavx2, -march=haswell | No | applied only when platform.machine() is x86_64 |

## Dockerfile and Deployment Descriptors
| File:line | Issue | Action |
|---|---|---|
| Dockerfile:6 | pip install in --platform=$BUILDPLATFORM stage copied into runtime | install moved to a $TARGETPLATFORM stage |
| Dockerfile:12 | FROM --platform=linux/amd64 | pin removed; build driven by --platform linux/arm64 |

## Changes Applied
<Summary of Phase 2.3 / 2.4 edits with file paths>

## No Findings
<If nothing was found:> No architecture-specific code, ctypes or cffi loads, build flags or platform pins detected.
```

### `05-runtime-configuration.md` — Graviton Runtime Optimization

**Created:** Phase 2.5. Nothing in this file is applied by the skill.

```markdown
# Graviton Runtime Configuration

## Target Python Version
| Current | Status (devguide, fetched YYYY-MM-DD) | Recommendation | Evidence level | Source |
|---|---|---|---|---|
| 3.11 | security fixes until 2027-10 | meets python.md >= 3.11 guidance; no action | A | python.md section 1.2 |

## Numerical Libraries (BLAS / OpenMP)
| Setting | Applies when | Recommendation | Evidence level | Source |
|---|---|---|---|---|
| OMP_NUM_THREADS / BLIS_NUM_THREADS | the project builds OpenBLAS with `USE_OPENMP=1` or BLIS with `--enable-threading=openmp` | set the maximum thread count; both default to one thread | A | python.md section 2.6 |

## ML Frameworks Present
| Framework | Version | Setting | Evidence level | Source |
|---|---|---|---|---|
| torch | 2.x | DNNL_DEFAULT_FPMATH_MODE=BF16 (only if `grep -q bf16 /proc/cpuinfo`), LRU_CACHE_CAPACITY=1024, THP_MEM_ALLOC_ENABLE=1, OMP formula; torch.compile | A | machinelearning/pytorch.md |

## Compiler Flags for In-Repo Extensions
| Extension | Recommendation | Evidence level | Source |
|---|---|---|---|

## Measure Before Adopting (Level B)
| Item | Source |
|---|---|

## Not Applicable
<Frameworks or libraries from the A-level list that the project does not use>
```

### `06-build-test-results.md` — Build & Test Validation Results

**Created:** Phase 3.

```markdown
# Build & Test Validation Results

## Build Environment
- **Architecture:** <uname -m; must be aarch64>
- **How:** Graviton host | linux/arm64 container on <host arch> (emulated: yes/no)
- **Host kernel page size and Graviton generation:** <getconf PAGESIZE>, <lscpu "BIOS Model name">; must match the production page size and the oldest deployed generation, or say why not
- **Interpreter:** <python3 --version>, pip <version>
- **Session-scoped interpreter alignment:** none | <tool and version used, why>
- **Build prerequisites installed for sdist fallbacks:** none | <packages>

## Build Attempts
| # | Command | Result | Packages from wheels / from source | Notes |
|---|---|---|---|---|
| 1 | pip install --require-hashes -r requirements-locked.txt | FAIL | | hash mismatch: the lock lists only x86_64 hashes |
| 2 | pip install -r requirements.txt | PASS | 11 wheels / 1 sdist (docopt) | |

## Import Smoke Test
| Package | Import | Native module loaded | Notes |
|---|---|---|---|
| numpy | OK | `_multiarray_umath.cpython-311-aarch64-linux-gnu.so`; np.__config__.show(): openblas | |

## Test Execution
| Command | Result | Passed / failed / skipped |
|---|---|---|

## Test Failure Classification
| Test | Type (INFRA / ARM64 / PRE-EXISTING) | Root cause | Blocking |
|---|---|---|---|

## Final Build (Scoring Basis)
- **Command:** <...>
- **Result:** PASS / FAIL
- **Rationale:** <why this is the scoring run>

## Container Validation (if applicable)
- **Build:** `<runtime> build --platform linux/arm64 -t app:arm64 .` -> PASS / FAIL
- **Architecture inside image:** `python -c 'import platform; print(platform.machine())'` -> aarch64
- **Base image unchanged:** yes

## Startup Validation
- **Starts without error:** yes / no
- **`platform.machine()` at runtime:** aarch64
- **Architecture-gated paths exercised:** <ctypes load succeeded | fell back; which>
- **Crashes / ImportError / GLIBC errors:** none | <text>
```

### `raw/dependency-tree-full.txt`

**Created:** Phase 1.1 (Generate Dependency Tree)
**Purpose:** Raw output from `uv tree`, `poetry show --tree` or `conda list`, or pip's `--dry-run --report` JSON saved as `dependency-tree-full.json`; a separately installed hashed file gets its own report (`dependency-tree-locked.json`). Kept for traceability; not hand-edited.

---

### `raw/wheel-availability.txt`

**Created:** Phase 1.3 (Generate Filtered Tree)
**Purpose:** Probe output, one line per pin: verdict, pin, and the wheel filename or the `from versions:` list. The Python counterpart of a native-artifact-only tree. Kept for traceability; not hand-edited.

---

### `raw/requirements-resolved.txt`

**Created:** Phase 1.1 (Generate Dependency Tree)
**Purpose:** The flat `name==version` list fed to the probe (export per [package-manager-mapping.md](package-manager-mapping.md)). Kept for traceability; not hand-edited.

---

### `raw/site-packages-so-scan.txt`

**Created:** Phase 1.2.1
**Purpose:** `native_scan` output: every ELF file in the project tree, including members of layer zips and vendored wheels, with its architecture, and the `not aarch64:` list. Kept for traceability; not hand-edited.

---

### `raw/wheel-availability-phase1.txt`, `raw/requirements-resolved-phase1.txt`

**Created:** Phase 2.2
**Purpose:** Copies of the Phase 1 files, kept before the post-fix re-run overwrites them. Kept for traceability; not hand-edited.

---

## Mapping: Transformation Steps → Output Files

| Step | What is produced | Output file |
|---|---|---|
| 1.1 deployment type, managers, monorepo | assessment sections | `01-project-assessment.md` |
| 1.1 dependency tree | raw tree / report | `raw/dependency-tree-full.txt` or `.json` |
| 1.1 target OS/glibc, pip version, index | assessment sections | `01-project-assessment.md` |
| 1.2 extension and binary scan | `native_scan` output | `raw/site-packages-so-scan.txt` |
| 1.2 verdicts (FAIL/WARN/PASS) | tables | `02-native-library-report.md` |
| 1.3 flat pins | export | `raw/requirements-resolved.txt` |
| 1.3 probe | verdict lines | `raw/wheel-availability.txt` |
| 1.3 classification, transitives, hash-lock, ABI blockers | tables | `03-dependency-compatibility-report.md` |
| 1.4 code, ctypes/cffi loads, scripts, flags, Dockerfile scan | tables | `04-code-scan-findings.md` |
| 1.5 interpreter version, EOL, bump policy | interpreter section | `01-project-assessment.md` |
| 2.1 extension and binary resolution | resolution columns | `02-native-library-report.md` |
| 2.2 dependency changes, lock regeneration, substitutions | applied / mechanism columns | `03-dependency-compatibility-report.md` |
| 2.3 architecture code changes | changes applied | `04-code-scan-findings.md` |
| 2.4 Dockerfile, Lambda, manifests | changes applied | `04-code-scan-findings.md` |
| 2.5 improvements | all tables | `05-runtime-configuration.md` |
| 3.0 environment and alignment | environment | `06-build-test-results.md` |
| 3.1 install validation | install attempts, import smoke test | `06-build-test-results.md` |
| 3.2 tests and classification | test tables, final build | `06-build-test-results.md` |
| 3.3 container and startup | container, startup sections | `06-build-test-results.md` |
| End | summary and exit criteria | `00-summary.md` |
