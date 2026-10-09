# ARM64 Transformation — Documentation Standards

## Purpose

This document defines the output folder, canonical filenames and required content for every report produced during a .NET Graviton compatibility transformation, so that two runs by different agents produce comparable results and a reviewer can audit each verdict back to its evidence.

## Output Folder Structure

All output goes into one folder, `graviton-validation/`, at the project root. Create it and its `raw/` subfolder before any analysis.

```
<project-root>/
└── graviton-validation/
    ├── 00-summary.md                         # Roll-up of findings and exit criteria (written last)
    ├── 01-project-assessment.md              # Deployment type, starting point, target frameworks, SDK, target OS and libc, config overrides
    ├── 02-native-library-report.md           # Native files from packages, committed files, P/Invoke loads, downloads, OS packages
    ├── 03-dependency-compatibility-report.md # Per-package verdicts with per-RID evidence, user decisions, target framework decision
    ├── 04-code-scan-findings.md              # Architecture checks, intrinsics, project settings, Windows-only APIs, descriptors
    ├── 05-runtime-configuration.md           # Graviton recommendations (document-only), each with its evidence level
    ├── 06-build-test-results.md              # Builds, publishes and output scans, tests, container and startup checks
    └── raw/                                  # Machine-generated artefacts, never hand-edited
        ├── project-properties.txt            # Evaluated properties of every project (Phase 1.1)
        ├── dependency-tree.json              # Every resolved package with its reference chain (Phase 1.1)
        ├── native-assets.txt                 # Per-RID native report (Phase 1.1, re-run in Phase 2.2)
        ├── dependency-tree-native.txt        # The FINDING, CHECK and OK lines with their chains (Phase 1.3)
        ├── repo-native-scan.txt              # Committed native files and assemblies by content (Phase 1.2)
        ├── ca1416.txt                        # Windows-only API call sites (Phase 1.4, Windows starting points)
        └── output-scan.txt                   # Publish outputs by content (Phase 3.1)
```

`raw/native-assets-packages-config.txt` (Phase 1.1, `packages.config` projects) and the Phase 2.2 copies `raw/native-assets-phase1.txt` and `raw/dependency-tree-phase1.json` are added when they apply.

## Agent Instructions

1. **Create `graviton-validation/` and `graviton-validation/raw/` first.** `mkdir -p graviton-validation/raw` is the first action of Phase 1.
2. **Use exactly these filenames.** Do not rename, renumber or add top-level files. Additional machine output goes under `raw/` with a descriptive name.
3. **Write progressively.** Each phase step writes its section as it completes; do not batch everything at the end.
4. **Every verdict cites its evidence.** A package row without the per-RID line (`OK`, `FINDING`, `CHECK`) or a `probe` result is incomplete; a code finding without file:line is incomplete. The "evidence" columns below are mandatory.
5. **Three labels, kept apart.** Findings are MUST UPGRADE, RECOMMENDED UPGRADE or COMPATIBLE (plus OUT OF SCOPE notes and BLOCKER items). Never list a recommendation among required changes, and never apply one.
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
- **Deployment type:** Containerized | Host-based | Lambda | Windows host (moved to Linux) | Both
- **Starting point:** modern .NET on Linux | modern .NET on Windows | .NET Framework
- **Target frameworks:** <net8.0, ...> (changed: no | yes, approved: <tfm>)
- **Target OS / libc:** <image, AMI or Lambda runtime; glibc 2.NN or musl 1.N>; target RIDs <linux-arm64[, linux-musl-arm64]>
- **Skill config applied:** none | <fields>
- **Date:** <ISO 8601>

## Exit Criteria Checklist
| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Every resolved package gives each target RID an aarch64 native for the target's libc and glibc, or is managed only, or is a documented user decision | ✅ PASS / ❌ FAIL | |
| 2 | Committed native files and assemblies run on ARM64 (aarch64 builds, AnyCPU), or documented fallbacks function | ✅ PASS / ❌ FAIL / N/A | |
| 3 | All MUST UPGRADE items applied, or documented as user decisions | ✅ PASS / ❌ FAIL | |
| 4 | Every project that moves to Linux publishes for each target RID, and every output scans without findings | ✅ PASS / ❌ FAIL / NOT RUN | |
| 5 | Container images build for linux/arm64 and their contents scan without findings | ✅ PASS / ❌ FAIL / N/A / NOT RUN | |
| 6 | Test suite executes on ARM64 | ✅ PASS / ❌ FAIL | |
| 7 | Failures classified as INFRA / ARM64 / PRE-EXISTING | ✅ PASS / ❌ FAIL | |
| 8 | No ARM64-related test failures | ✅ PASS / ❌ FAIL | |
| 9 | Application starts on ARM64 (`RuntimeInformation.ProcessArchitecture` reports Arm64) and every native library loads | ✅ PASS / ❌ FAIL | |
| 10 | Target frameworks and SDK unchanged, or changed only through an approved `dotnet.framework_bump` | ✅ PASS / ❌ FAIL | |
| 11 | All files in `graviton-validation/` use the canonical names | ✅ PASS / ❌ FAIL | |

NOT RUN is only for a check that needs ARM64 hardware the run did not have (for example a Native AOT publish on an x86 host without a cross toolchain); give the reason in Notes and list the check under Remaining Concerns.

## Changes Made
<Short list; link to 02, 03, 04 for detail>

## Recommendations Recorded (Not Applied)
<Count and link to 05; CI changes for the user>

## Remaining Concerns
<Blockers (Windows Forms, WPF, Web Forms), substitutions awaiting confirmation, target OS and glibc decisions, NOT RUN checks>
```

### `01-project-assessment.md` — Project & Environment Assessment

**Created:** Phase 1.1 and 1.5.

```markdown
# Project Assessment

## Deployment Type
<Containerized | Host-based | Lambda | Windows host | Both>, with evidence (Dockerfile path, systemd unit, SAM template, aws-lambda-tools-defaults.json, web.config, install script)

## Project Structure
| Solution or project | Projects | Package management | Lock files | Notes |
|---|---|---|---|---|
| Fixture.sln | 9 | central (Directory.Packages.props) | yes (9) | RuntimeIdentifiers from Directory.Build.props |

Projects no solution lists: <none | list>

## Starting Point
<modern .NET on Linux | modern .NET on Windows | .NET Framework>, from raw/project-properties.txt (TargetFramework, UsingMicrosoftNETSdk, UseWindowsForms/UseWPF, RuntimeIdentifier) and the hosting markers. Blockers: <none | Windows Forms, WPF, Web Forms projects>

## .NET Environment
- **Target frameworks:** <net8.0 (7), netstandard2.0 (1), netcoreapp3.1 (1)>
- **SDK:** global.json <version, rollForward> -> selected <8.0.425>
- **Runtime on the targets:** <image tags, Lambda runtimes, host packages>
- **Support status:** <from the release metadata (Phase 1.5)>
- **Policy applied:** `dotnet.framework_bump` = ask | approved=<tfm> | never; outcome: unchanged | <change and why>

## Target OS and libc
- **Targets:** <image | AMI | Lambda runtime>, each with its libc and version, measured by <the Phase 1.1 or nuget-native-assets.md §6 block | the Lambda runtime table>
- **Target RIDs:** <linux-arm64[, linux-musl-arm64]>; lowest glibc: <2.NN>; page size: <4KB | 64KB>
- **Globalization:** <InvariantGlobalization, ICU and tzdata in the target images (windows-to-linux.md §5)>

## Feeds
<nuget.org | the sources and package source mapping in NuGet.config; versions missing from a feed: INFRA items>

## Skill Configuration Overrides Applied
<none | field: value, effect>

## Component Risk Categorization
| Component | Risk | Rationale |
|---|---|---|
| src/Fixture.Core/native/x64/libfastsum.so | CRITICAL | committed x86-64 binary |
| Dapper, Newtonsoft.Json | LOW | managed only (per-RID check) |
```

### `02-native-library-report.md` — Native Library Analysis & Resolution

**Created:** Phase 1.2, updated in Phase 2.1.

```markdown
# Native Library Report

## Package Native Files
Summary of raw/native-assets.txt: <N> packages, <M> with native files for these RIDs, <F> findings, <C> checks (detail per package in 03).

## Statically Bundled Libraries
| File | Location | Architecture (by content) | aarch64 build present | Verdict | Resolution |
|---|---|---|---|---|---|
| libfastsum.so | src/Fixture.Core/native/x64/ | ELF x86-64, GLIBC_2.2.5 | No | WARN (source in native/fastsum.c) | cross-compiled to native/arm64/libfastsum.so (aarch64) |

## Runtime-Extracted Libraries
| Source | Artifact | Loaded, run or downloaded at run time | aarch64 support | Verdict | Resolution |
|---|---|---|---|---|---|
| src/Fixture.Core/Native.cs:26 | NativeLibrary.Load of native/<arch>/libfastsum.so | loaded | resolver knew only X64 | FAIL until fixed | Arm64 branch (Phase 2.1) |
| deploy/deploy.sh:10 | awscli-exe-linux-x86_64.zip | downloaded | aarch64 asset answers HTTP 200 | WARN | ${ARCH} in the URL (Phase 2.3) |
| Dockerfile | libfontconfig1 (apt) | installed | arm64 build in Debian 12 | PASS | none |

## Resolution Details
<For each FAIL or WARN, describe the resolution approach.> FAIL: x86-only native with no aarch64 build path and no source. WARN: source available, a managed fallback exists, or the file is used only by tools and tests (CHECK). PASS: aarch64 build present or built.

## Managed Fallbacks Documented
<Any native library replaced by a managed code path, with the note that the fallback is slower>

## No Findings
<If nothing was found:> No committed native files, P/Invoke loads, downloads or OS packages with an architecture issue. All native code arrives through NuGet packages (see 03).
```

### `03-dependency-compatibility-report.md` — Dependency ARM64 Compatibility

**Created:** Phase 1.3, updated in Phase 2.2. The primary report.

```markdown
# Dependency ARM64 Compatibility Report

Source RID: linux-x64 | win-x64. Target RIDs: <linux-arm64[, linux-musl-arm64]>. Target glibc: <2.NN>. Feeds: <nuget.org | NuGet.config sources>. Check date: YYYY-MM-DD.

## MUST UPGRADE (Blocking)
| Package | Direct / via | Version | Issue | Evidence (per-RID line) | Minimum ARM64 version | Applied | Where written |
|---|---|---|---|---|---|---|---|
| SkiaSharp.NativeAssets.Linux | direct (src/Fixture.Core) | 1.68.3 | no linux-arm64 native | `FINDING no linux-arm64 native: SkiaSharp.NativeAssets.Linux/1.68.3 (linux-x64 has 1; runtimes/ folders: linux-x64)` | 2.80.0 with SkiaSharp 2.80.0 (probe: `OK ... linux-arm64: runtimes/linux-arm64/native/libSkiaSharp.so (glibc GLIBC_2.17 ...)`) | pending (user decision below) | |
| AWSSDK.Core | via AWSSDK.S3 3.3.107.1 | 3.3.103.65 | no IMDSv2 support; the target AMI requires IMDSv2 | Phase 1.3 SDK check | 3.3.103.66 (AWSSDK.S3 3.3.107.2) | 3.3.107.2 | Directory.Packages.props |

## User Decisions Pending
| Item | Current | Options | Recommendation |
|---|---|---|---|
| SkiaSharp and SkiaSharp.NativeAssets.Linux | 1.68.3 | (a) 2.80.0, the arm64 floor, which restore flags with NU1903 (GHSA-j7hp-h8jx-5ppr); (b) 2.88.6, the lowest release without it | ask once; not the latest release (3.119.0 needs GLIBC_2.27) |
| System.Data.SQLite.Core (its Stub.System.Data.SQLite.Core.NetStandard) | 1.0.119 | no linux-arm64 file in any release: substitute Microsoft.Data.Sqlite (a code change) | substitute, after confirmation |

## RECOMMENDED UPGRADE (Non-Blocking)
| Package | Version | Recommended version | Reason | Evidence level | Action taken |
|---|---|---|---|---|---|
| <package> | <ver> | <ver> | documented Graviton improvement (source) | A or B | Documented for user |

## COMPATIBLE (No Action Needed)
| Package | Direct / via | Version | Basis |
|---|---|---|---|
| Newtonsoft.Json | direct | 12.0.3 | managed only; NU1903 is out of scope |
| SQLitePCLRaw.lib.e_sqlite3 | via Microsoft.Data.Sqlite 8.0.31 | 2.1.12 | `OK linux-arm64 ... (glibc GLIBC_2.34 align 0x10000)` |

## CHECK Items (Tools and Tests)
| Package | Via | Files | Where they run | Result |
|---|---|---|---|---|
| Microsoft.CodeCoverage | Microsoft.NET.Test.Sdk 17.11.1 | x86-64 instrumentation libraries in build/ | coverage collection | <collected on arm64 hardware (Phase 3.2), or NOT RUN with the reason> |

## Transitive Dependency Resolutions
| Transitive | Pulled in by | Issue | Mechanism used |
|---|---|---|---|
| librdkafka.redist | Confluent.Kafka 1.5.3 | no linux-arm64 native | Confluent.Kafka 1.6.1 |

## Target Framework Decision
| Project | Current | Reason a change is needed | Options (support dates, glibc) | Decision |
|---|---|---|---|---|
| src/Fixture.Lambda | netcoreapp3.1, Lambda dotnetcore3.1 | updates blocked since May 3, 2023 | net8.0 / dotnet8 (until Nov 10, 2026); net10.0 / dotnet10 (until Nov 14, 2028) | approved net10.0 (with the SDK pin in `global.json` moved to 10.0.100) |
```

### `04-code-scan-findings.md` — Architecture-Specific Code Detection

**Created:** Phase 1.4, updated in Phase 2.3 and 2.4.

```markdown
# Architecture-Specific Code Scan

## Architecture Detection Patterns Found
| File:line | Pattern | Arm64 handling present | Action |
|---|---|---|---|
| src/Fixture.Core/Native.cs:21 | RuntimeInformation.ProcessArchitecture switch with only X64 | No | Arm64 branch added |
| tests/Fixture.Tests/CoreTests.cs:37 | Assert.Equal("linux-x64", RuntimeInformation.RuntimeIdentifier) | No | test accepts linux-arm64 |

## P/Invoke and NativeLibrary Usage
| File:line | Call | Library | Arm64 validated | Action |
|---|---|---|---|---|

## Hardware Intrinsics and Vector Width
| File:line | Call or type | IsSupported check | Arm64 or portable path | Action |
|---|---|---|---|---|
| src/Fixture.Core/Native.cs:44 | Avx2.Add | No | No | IsSupported check and a Vector128 path |

## Project Settings
| Project | Setting | Action |
|---|---|---|
| src/Fixture.Legacy | PlatformTarget=x64 | removed (AnyCPU) |
| Directory.Build.props | RuntimeIdentifiers=linux-x64 | linux-arm64 added; lock files regenerated |

## Windows-Only APIs and .NET Framework Technologies
| File:line | API or technology | Linux replacement (windows-to-linux.md) | Decision |
|---|---|---|---|

## Dockerfile and Deployment Descriptors
| File:line | Issue | Action |
|---|---|---|
| Dockerfile:2, 5 | FROM --platform=linux/amd64 for the SDK stage; -r linux-x64 | $BUILDPLATFORM with -a $TARGETARCH |

## Shell Scripts and CI
| File:line | Pattern | Action |
|---|---|---|
| deploy/deploy.sh:5 | uname -m gate for x86_64 only | case on x86_64 and aarch64 |
| .github/workflows/ci.yml:14, 15 | linux-x64 Native AOT publish; `docker build` without `--platform` | recommendation for the user (CI) |

## Changes Applied
<Summary of Phase 2.3 / 2.4 edits with file paths>

## No Findings
<If nothing was found:> No architecture-specific code, P/Invoke, intrinsics, project settings, Windows-only APIs or descriptor pins detected.
```

### `05-runtime-configuration.md` — Graviton Runtime Optimization

**Created:** Phase 2.5. Nothing in this file is applied by the skill.

```markdown
# Graviton Runtime Configuration

## Target Framework
| Current | Support status (release metadata) | Recommendation | Evidence level | Source |
|---|---|---|---|---|
| net8.0 | maintenance, end of support 2026-11-10 | .NET 10 (LTS) for new Graviton workloads; changes only through dotnet.framework_bump | A | dotnet.md "Recommended versions" |

## Vectorization
| Code | Recommendation | Evidence level | Source |
|---|---|---|---|
| src/Fixture.Core/Native.cs Statistics.Total (AVX2 or scalar) | add a Vector128 path; measure before adopting | B | Microsoft Learn: SIMD |

## Not Applicable
<Rows from phase2 §2.5 that do not apply to the project>
```

### `06-build-test-results.md` — Build & Test Validation Results

**Created:** Phase 3.

```markdown
# Build & Test Validation Results

## Build Environment
- **Host:** <uname -m>, <OS>; container runtime <docker | finch | none>; emulated runs: yes/no
- **Host kernel page size and Graviton generation:** <getconf PAGESIZE>, <instance type>; must match production, or say why not
- **SDK:** <dotnet --version>; session-scoped switch: none | <how, why>
- **Runtime used for arm64 runs:** <image and tag, or host package>

## Build Attempts
| # | Command | Result | Notes |
|---|---|---|---|
| 1 | dotnet restore Fixture.sln --locked-mode | PASS | |
| 2 | dotnet build Fixture.sln -c Release --no-restore | PASS | |

## Output Scans
| Project | RID | Publish | Findings | Notes |
|---|---|---|---|---|
| Fixture.Api | linux-arm64 | exit 0 | 0 | NOTE: x64 libfastsum.so beside its aarch64 build |
| Fixture.Agent | linux-arm64 | NOT RUN | | Native AOT: cross-publish from x64 failed (`unrecognized command-line option`); publish on arm64 (Phase 2.4) |

## Test Execution
| Command | Where | Result | Passed / failed / skipped |
|---|---|---|---|

## Test Failure Classification
| Test | Type (INFRA / ARM64 / PRE-EXISTING) | Root cause | Blocking |
|---|---|---|---|

## Final Build (Scoring Basis)
- **Command:** <...>
- **Result:** PASS / FAIL
- **Rationale:** <why this is the scoring run>

## Container Validation (if applicable)
- **Build:** `<runtime> build --platform linux/arm64 -t app:arm64 .` -> PASS / FAIL
- **Inside the image:** `dotnet --info` -> Architecture arm64, RID linux-arm64; scan of the application folder -> <findings>
- **Base image unchanged:** yes

## Startup Validation
- **Starts without error:** yes / no
- **`RuntimeInformation.ProcessArchitecture` at run time:** Arm64
- **Native libraries loaded:** <list, and which build was loaded where both architectures ship>
- **IMDSv2 credentials / Lambda invocation:** PASS / NOT RUN (<reason>)
- **Crashes, DllNotFoundException, PlatformNotSupportedException:** none | <text>
```

### `raw/project-properties.txt`

**Created:** Phase 1.1 (Determine Starting Point)
**Purpose:** One line per project file with its evaluated properties (`dotnet msbuild -getProperty`). Kept for traceability; not hand-edited.

---

### `raw/dependency-tree.json`

**Created:** Phase 1.1 (Generate Dependency Tree)
**Purpose:** Every resolved package per project and target framework, with the reference chain from the project (`assets --tree`). Kept for traceability; not hand-edited.

---

### `raw/native-assets.txt`

**Created:** Phase 1.1 (Generate Dependency Tree), re-run in Phase 2.2
**Purpose:** The per-RID native report: `OK`, `FINDING`, `CHECK` and `NOTE` lines with `via` chains, and the summary line. Kept for traceability; not hand-edited.

---

### `raw/dependency-tree-native.txt`

**Created:** Phase 1.3 (Generate Filtered Tree)
**Purpose:** The `FINDING`, `CHECK` and `OK` lines of `native-assets.txt` with their chains: the packages with native files. Kept for traceability; not hand-edited.

---

### `raw/repo-native-scan.txt`

**Created:** Phase 1.2.1
**Purpose:** `scan --source-tree` output: every ELF, PE and Mach-O file committed to the repository, with its architecture. Kept for traceability; not hand-edited.

---

### `raw/ca1416.txt`

**Created:** Phase 1.4 (Windows starting points)
**Purpose:** The CA1416 call sites from a Linux build of a scratch copy. Kept for traceability; not hand-edited.

---

### `raw/output-scan.txt`

**Created:** Phase 3.1
**Purpose:** The publish result and `scan` output of every executable project for each target RID. Kept for traceability; not hand-edited.

---

### `raw/native-assets-phase1.txt`, `raw/dependency-tree-phase1.json`

**Created:** Phase 2.2
**Purpose:** Copies of the Phase 1 files, kept before the post-fix re-run overwrites them. Kept for traceability; not hand-edited.

---

## Mapping: Transformation Steps → Output Files

| Step | What is produced | Output file |
|---|---|---|
| 1.1 deployment type, structure, starting point | assessment sections | `01-project-assessment.md`, `raw/project-properties.txt` |
| 1.1 target OS and libc | assessment section | `01-project-assessment.md` |
| 1.1 dependency tree and per-RID check | raw tree and report | `raw/dependency-tree.json`, `raw/native-assets.txt` |
| 1.2 committed native files | scan output | `raw/repo-native-scan.txt` |
| 1.2 verdicts (FAIL/WARN/PASS), runtime loads, OS packages | tables | `02-native-library-report.md` |
| 1.3 filtered tree | per-RID lines with chains | `raw/dependency-tree-native.txt` |
| 1.3 classification, transitives, AWS SDK, build tools | tables | `03-dependency-compatibility-report.md` |
| 1.4 code, intrinsics, settings, Windows-only APIs, descriptors | tables | `04-code-scan-findings.md`, `raw/ca1416.txt` |
| 1.5 target frameworks, SDK, support, Lambda runtimes | environment section | `01-project-assessment.md`, `03` (target framework decision) |
| 2.1 native file resolution | resolution columns | `02-native-library-report.md` |
| 2.2 package changes, lock files, substitutions, target framework | applied / where-written columns | `03-dependency-compatibility-report.md` |
| 2.3 architecture code changes | changes applied | `04-code-scan-findings.md` |
| 2.4 project settings, Dockerfile, Lambda, manifests | changes applied | `04-code-scan-findings.md` |
| 2.5 recommendations | all tables | `05-runtime-configuration.md` |
| 3.0 environment and SDK alignment | environment | `06-build-test-results.md` |
| 3.1 builds, publishes and output scans | build attempts, output scans | `06-build-test-results.md`, `raw/output-scan.txt` |
| 3.2 tests and classification | test tables, final build | `06-build-test-results.md` |
| 3.3 container and startup | container, startup sections | `06-build-test-results.md` |
| End | summary and exit criteria | `00-summary.md` |
