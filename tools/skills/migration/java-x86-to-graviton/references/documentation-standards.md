# ARM64 Transformation — Documentation Standards

## Contents

- Purpose
- Output Folder Structure
- Agent Instructions
- File Specifications: `00-summary.md`; `01-project-assessment.md`; `02-native-library-report.md`; `03-dependency-compatibility-report.md`; `04-code-scan-findings.md`; `05-jvm-configuration.md`; `06-build-test-results.md`; `raw/dependency-tree-full.txt`; `raw/dependency-tree-native.txt`

## Purpose
This document defines the standard output folder structure, canonical filenames, and content requirements for all documentation produced during an ARM64 Graviton compatibility transformation.

## Output Folder Structure

All transformation output documents MUST be written to a single folder named `graviton-validation/java-x86-to-graviton/` in the project root (Agent Instructions 1). Each skill has its own folder under `graviton-validation/`, so two skills run on one repository (for example a Java service and a Python Lambda function) keep their own reports and their own `raw/target-roots.txt`.

```
<project-root>/
└── graviton-validation/java-x86-to-graviton/
    ├── 00-summary.md                        # Final roll-up of all findings and exit criteria
    ├── 01-project-assessment.md             # Project structure, deployment type, Java environment
    ├── 02-native-library-report.md          # All .so / native library findings and resolutions
    ├── 03-dependency-compatibility-report.md # Per-dependency ARM64 compatibility verdicts
    ├── 04-code-scan-findings.md             # Architecture-specific code patterns detected
    ├── 05-jvm-configuration.md              # Graviton JVM flag recommendations (not applied)
    ├── 06-build-test-results.md             # Build validation, test results, failure classification
    └── raw/                                 # Machine-generated artifacts (not hand-authored)
        ├── dependency-tree-full.txt         # Full dependency tree output
        ├── dependency-tree-native.txt       # Filtered tree (native-code artifacts only)
        ├── native-check-<target>.txt        # Native files judged by content, one file per target (Phase 1.2.1)
        ├── native-check-<target>-phase1.txt # The Phase 1 output, kept before Phase 2.2 re-runs the check
        └── target-roots.txt                 # Each target's name and its image's folder, or glibc=VERSION with no image (Phase 1.1)
```

## Agent Instructions

1. **Create `graviton-validation/java-x86-to-graviton/` and `graviton-validation/java-x86-to-graviton/raw/` at the start of Phase 1.** This is the first action before any analysis.
2. **Use EXACTLY these filenames.** Do not rename, renumber, or create additional top-level files.
3. **Write to each file progressively** as the corresponding phase completes. Do not wait until the end to produce all documentation.
4. **Raw files go in `raw/`.** Only machine-generated command output belongs in `raw/`. Do not put authored content there.
5. **`00-summary.md` is written last**, after all other files are complete. It references (not duplicates) the detail in files 01–06.
6. **If a section has no findings**, include the section header with an explicit "No findings" statement. Do not omit empty sections — their absence is ambiguous.
7. **Do not create documentation files outside `graviton-validation/java-x86-to-graviton/`.** All transformation documentation lives in this single folder.
8. **Three labels, kept apart.** Findings are MUST UPGRADE, RECOMMENDED UPGRADE or COMPATIBLE (plus OUT OF SCOPE notes). Never list a recommendation among required changes, and never apply one. A finding that waits for a user decision, or for evidence Phase 1 cannot produce, is CHECK until it gets one of the three labels: list user decisions under User Decisions Pending with the recommended option, the smallest change the evidence supports (an unattended run applies it and says how to reverse it), and the rest under CHECK Items with the step that settles each.
9. **Every verdict cites its evidence and says where it was established.** A dependency row without the Phase 1.2.1 check's line (`OK`, `FINDING`, `CHECK`) is incomplete; a code finding without file:line is incomplete. The `Established` column says where the verdict comes from: `predicted` (read from files on any host, as the check does), `emulated` (observed in a `linux/arm64` environment under emulation), `other arm64` (observed on arm64 hardware that is not Graviton, such as an Apple Silicon Mac), `graviton` (observed on a Graviton host that is not the target), or `target` (observed on the target: its Graviton generation, OS image and page size, or the arm64 Lambda function). Phase 3 updates the column when it observes a verdict; only `graviton` and `target` observations pass a check or settle a CHECK. A `predicted` finding stays a finding when a Phase 3 run passes, because a run shows only the code paths it exercised.

---

## File Specifications

### `00-summary.md` — Transformation Summary

**Created:** End of transformation (Phase 3 complete)
**Purpose:** Single-page executive summary mapping to all exit criteria. This is the first file a reviewer reads.

**Required sections:**
```markdown
# ARM64 Compatibility Validation — Summary

## Project Overview
- **Project Name:** <n>
- **Deployment Type:** Containerized | Host-based | Both
- **Java Version:** <version>
- **JDK Distribution:** <distribution>
- **Build Tool:** Maven <version> | Gradle <version>
- **Multi-Module:** Yes (N modules) | No
- **Target OS / libc:** <image, AMI or Lambda runtime; glibc 2.NN or musl 1.N>
- **Date:** <ISO 8601>

## Exit Criteria Checklist
| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Compiles on ARM64 without errors | ✅ PASS / ❌ FAIL | |
| 2 | Native libraries load on ARM64 | ✅ PASS / ❌ FAIL | |
| 3 | Blocking dependency updates applied | ✅ PASS / ❌ FAIL | |
| 4 | No ARM64-specific runtime errors | ✅ PASS / ❌ FAIL | |
| 5 | Container image builds on ARM64 | ✅ PASS / ❌ FAIL / N/A | |
| 6 | Test suite executes on ARM64 | ✅ PASS / ❌ FAIL | |
| 7 | No ARM64-related test failures | ✅ PASS / ❌ FAIL | |
| 8 | Application starts on ARM64 | ✅ PASS / ❌ FAIL | |
| 9 | The project's existing JVM options accepted on ARM64 | ✅ PASS / ❌ FAIL | |

A criterion that runs on ARM64 passes only on a Graviton host or the target (Phase 3, "Match the production hosts"); otherwise its status is NOT RUN, with where it did run in Notes.

## Changes Made
<Brief summary of dependency updates, native library resolutions, code changes.
Reference detail files: 02-native-library-report.md, 03-dependency-compatibility-report.md, 04-code-scan-findings.md>

## Remaining Concerns
<Any unresolved issues, user decisions pending, CHECK items not settled, user-responsibility items, or known limitations>
```

---

### `01-project-assessment.md` — Project & Environment Assessment

**Created:** Phase 1.1 and Phase 1.5
**Purpose:** Records the baseline project state before any changes.

**Required sections:**
```markdown
# Project Assessment

## Deployment Type
<Containerized | Host-based | Both>
<Evidence: e.g., "Dockerfile found at ./Dockerfile", "systemd unit at ./deploy/app.service">

## Project Structure
- **Build Tool:** Maven | Gradle
- **Multi-Module:** Yes | No
- **Submodules:** <list if applicable>

## Java Environment
- **Java Version:** <exact version, e.g., 17.0.8>
- **JDK Distribution:** <e.g., Eclipse Temurin, Amazon Corretto, OpenJDK>
- **ARM64 Support Status:** Supported | Supported with limitations
- **Known Graviton Issues:** None | <description>

## Target OS and libc
- **Targets:** <image | AMI | Lambda runtime>, each with its OS (os-release name), C library and version, and highest `GLIBCXX_`, read from <the image's files (the Phase 1.1 block) | the Lambda runtime table | `ldd --version` on the host>
- **Deployment hosts:** <host>: page size <4KB | 64KB | unknown>, kernel <release | unknown>, from <`getconf PAGESIZE` and `uname -r` there | `page=` and `kernel=` in `target.hosts` | the team that runs the hosts>
- **Graviton generations deployed:** <e.g. Graviton2 and Graviton4 | unknown>; oldest: <generation>
- **Check options:** <the target of each Phase 1.2.1 run: `--target-root` and its folder, or `--libc glibc --glibc VERSION` for a target with no image>
- **From skill-config:** <none | the `target.hosts` and `target.images` entries used, and each value a target's files or a host measurement overruled>

## Skill Configuration Overrides Applied
<none | field: value, effect>

## Component Risk Categorization
| Component | Risk Level | Rationale |
|-----------|-----------|-----------|
| <component> | CRITICAL / HIGH / MEDIUM / LOW | <why> |
```

---

### `02-native-library-report.md` — Native Library Analysis & Resolution

**Created:** Phase 1.2 (analysis), updated in Phase 2.1 (resolution)
**Purpose:** Documents every native library found — bundled and runtime-extracted — its architecture, and how it was resolved.

**Required sections:**
```markdown
# Native Library Report

## Statically Bundled Libraries
| Library | Source JAR/Location | Architecture (by content) | aarch64 build present | Verdict | Established | Resolution |
|---|---|---|---|---|---|---|
| libfoo.so | commons-crypto-1.1.0.jar | `FINDING ...: is x86-64; no aarch64 Linux build of this library` | No | FAIL | predicted | Upgraded to 1.2.0 (includes aarch64) |
| libbar.so | app-native/lib/ | `OK ...: ELF aarch64 shared library, glibc, GLIBC_2.17` | Yes | PASS | predicted | No action needed |

## Runtime-Extracted Libraries
| Dependency | Artifact | Extracts Native Code | ARM64 Support in Current Version | Verdict | Established | Resolution |
|---|---|---|---|---|---|---|
| netty-transport-native-epoll | 4.1.68.Final | Yes | Yes (linux-aarch_64 classifier) | PASS | predicted | No action needed |
| snappy-java | 1.1.1.7 | Yes | No (JAR has no Linux/aarch64/libsnappyjava.so) | FAIL | predicted | Upgraded to 1.1.2.2 |

## Resolution Details
<For each FAIL or WARN, describe the resolution approach>

## Pure Java Fallbacks Documented
<List any libraries where a pure Java fallback path was chosen instead of native resolution>

## No Findings
<If no native libraries were detected, state explicitly:>
No native libraries (bundled or runtime-extracted) detected. All dependencies are pure Java.
```

---

### `03-dependency-compatibility-report.md` — Dependency ARM64 Compatibility

**Created:** Phase 1.3 (analysis), updated in Phase 2.2 (resolution)
**Purpose:** The primary dependency-by-dependency compatibility assessment.

**Required sections:**
```markdown
# Dependency ARM64 Compatibility Report

## MUST UPGRADE (Blocking)
| Dependency | Current Version | Minimum ARM64 Version | Applied Version | ARM64 Issue | Evidence | Established |
|---|---|---|---|---|---|---|
| org.xerial.snappy:snappy-java | 1.1.1.7 | 1.1.2.2 | 1.1.2.2 | JAR has no Linux/aarch64/libsnappyjava.so | Phase 1.2.1 check: `FINDING ...Linux/x86_64/libsnappyjava.so: is x86-64; no aarch64 Linux build of this library` | predicted |

## User Decisions Pending
| Item | Current | Options | Recommendation | Applied |
|---|---|---|---|---|
| <dependency or file> | <version> | (a) <option, and the label it leads to>; (b) <option> | <the smallest change the evidence supports> | <no (the user chooses), or yes (unattended run) and how to reverse it> |

## CHECK Items
| Item | Via | Why it is not settled | Settled by | Result |
|---|---|---|---|---|
| <dependency or file> | <direct or the dependency that pulls it in> | <for example: a native library extracted or downloaded at run time> | <the Phase 3 step on ARM64> | <the label it got, or still CHECK with the reason> |

A library whose `NOTE` names the build for the target is not a CHECK item: list its Phase 3 confirmation with the Phase 3 steps.

## RECOMMENDED UPGRADE (Non-Blocking)
| Dependency | Current Version | Recommended Version | Reason | Action Taken |
|------------|----------------|--------------------|---------|----|
| <dep> | <ver> | <ver> | ARM64 perf improvement | Documented for user |

## COMPATIBLE (No Action Needed)
| Dependency | Version | Basis | Established |
|---|---|---|---|
| junit:junit | 3.8.1 | Pure Java: no native code | predicted |
| com.google.guava:guava | 31.1-jre | Pure Java: no native code | predicted |

## Transitive Dependency Resolutions
| Transitive Dependency | Pulled In By | Issue | Resolution Method |
|-----------------------|-------------|-------|-------------------|
| org.xerial.snappy:snappy-java 1.1.1.7 | kafka-clients 2.7.0 | JAR has no Linux/aarch64 binary | dependencyManagement override to 1.1.2.2 |
```

---

### `04-code-scan-findings.md` — Architecture-Specific Code Detection

**Created:** Phase 1.4, updated in Phase 2.3 and 2.4 (resolution)
**Purpose:** Records all source code locations with architecture-sensitive patterns and changes applied.

**Required sections:**
```markdown
# Architecture-Specific Code Scan

## Architecture Detection Patterns Found
| File | Line(s) | Pattern | ARM64 Handling Present | Action Required |
|------|---------|---------|----------------------|-----------------|
| src/.../NativeLoader.java | 42-48 | System.getProperty("os.arch") | No — only checks "amd64" | Add "aarch64" branch |

## JNI/JNA Usage
| File | Line(s) | Type | Library | ARM64 Validated |
|------|---------|------|---------|-----------------|
| src/.../Bridge.java | 23 | JNA Native.load() | libbridge.so | Yes — aarch64 binary present |

## JVM Options and Deployment Settings
| File | Line(s) | Setting | Action |
|------|---------|---------|--------|
| Dockerfile | 9 | `JAVA_TOOL_OPTIONS=-XX:UseAVX=2`: x86-only, an ARM64 JVM does not start | removed for arm64 (Phase 2.4) |
| template.yaml | 14 | Lambda function with no `Architectures`, so it runs on x86_64 | `Architectures: [arm64]` (Phase 2.4) |

## Dockerfile and Deployment Descriptors
| File:line | Issue | Action |
|---|---|---|
| Dockerfile:1 | FROM --platform=linux/amd64 for the build stage | pin removed; build driven by --platform linux/arm64 |

## Shell Scripts and CI
| File:line | Pattern | Action |
|---|---|---|
| deploy/deploy.sh:5 | uname -m gate for x86_64 only | case on x86_64 and aarch64 |
| .github/workflows/ci.yml:14 | `docker build` without `--platform` | architecture-only change applied (Phase 2.4 "CI pipelines"): `--platform linux/amd64,linux/arm64` |

## Changes Applied
<Summary of code changes made in Phase 2.3 to add ARM64 handling>

## No Findings
<If no architecture-specific code was detected, state explicitly:>
No architecture-specific code patterns, JNI, or JNA usage detected. All code is pure Java.
```

---

### `05-jvm-configuration.md` — Graviton JVM Optimization

**Created:** Phase 2.5
**Purpose:** Records the JVM flag recommendations, their version-gated rationale, and the check that the target JVM accepts them. Nothing in this file is applied by the skill.

**Required sections:**
```markdown
# Graviton JVM Configuration

## Target Java Version
<JDK version used for flag selection, e.g., JDK 17>

## Recommended JVM Flags (Not Applied)
| Flag | Applicable JDK Versions | Workload Type | Expected Impact |
|------|------------------------|---------------|-----------------|
| -XX:-TieredCompilation | 11, 17 | Long-running services (not latency-sensitive startup) | Trades startup time for steady-state throughput |

## Flags Not Recommended (Version-Gated)
| Flag | Reason Not Recommended |
|------|------------------------|
| -XX:+UnlockDiagnosticVMOptions -XX:+UseAESCTRIntrinsics | On by default on JDK 11 and later (`-XX:+UnlockDiagnosticVMOptions -XX:+PrintFlagsFinal` shows `UseAESCTRIntrinsics = true {diagnostic} {default}`); JDK 8 has no such option and stops with `Unrecognized VM option` |

## Flag Validation
<Output of: java <recommended flags> -version on ARM64, to confirm the target JVM accepts them; nothing is written to the project>

## Configuration Profiles
<If the recommendations differ by workload type, list each set here>
```

---

### `06-build-test-results.md` — Build & Test Validation Results

**Created:** Phase 3.1, 3.2, 3.3
**Purpose:** Records all build attempts, test execution results, failure classifications, and startup checks.

**Required sections:**
```markdown
# Build & Test Validation Results

## Build Environment
- **Architecture:** <output of `uname -m`, should be aarch64>
- **Where:** Graviton host (<instance type>) | the target | linux/arm64 container on <host arch> (emulated: yes/no) | another arm64 machine (<which>); only a Graviton host or the target passes a check
- **Java Runtime:** <output of `java -version`>
- **Build Tool:** <Maven/Gradle version>
- **Build Environment Notes:** <any Java runtime alignment applied per Phase 3.0>

## Build Attempts
| # | Command | Result | Notes |
|---|---------|--------|-------|
| 1 | `./gradlew clean build` | ❌ FAIL | 3 test failures — see classification below |
| 2 | `./gradlew clean build -x test` | ✅ PASS | Compilation successful |

## Test Failure Classification
| Test | Class | Failure Type | Root Cause | Blocking |
|------|-------|-------------|------------|----------|
| testDbConnection | IntegrationTest | INFRA | PostgreSQL not available | No |
| testNativeAccel | CryptoTest | ARM64 | UnsatisfiedLinkError | Yes |

## Final Build (Scoring Basis)
- **Command:** <the final build command>
- **Result:** ✅ PASS / ❌ FAIL
- **Rationale:** <why this is the scoring build>

## Container Validation (if applicable)
- **Build Command:** `docker build -t app:arm64 .`
- **Result:** ✅ PASS / ❌ FAIL
- **Architecture Verified:** `os.arch = aarch64`
- **JDK Verified:** <matches original distribution and version>

## Startup Validation
- **Application starts without errors:** ✅ Yes | ❌ No
- **Existing JVM options accepted on ARM64:** ✅ Yes | ❌ No
- **Native libraries loaded (loaded check), ARM64 and the x86 baseline:** <both lists, or "the same">
- **Runtime crashes:** None | <description>
```

---

### `raw/dependency-tree-full.txt`

**Created:** Phase 1.1 step 2
**Purpose:** Raw output from `mvn dependency:tree` or `./gradlew dependencies`. Kept for traceability; not hand-edited.

---

### `raw/dependency-tree-native.txt`

**Created:** Phase 1.3 step 1
**Purpose:** Filtered dependency tree showing only known native-code artifacts. Kept for traceability; not hand-edited.

---

### `raw/native-check-<target>.txt`

**Created:** Phase 1.2.1, re-run in Phase 2.2
**Purpose:** The Phase 1.2.1 check's output for one target (`<target>` is its name in `raw/target-roots.txt`), one run per module output and one for the repository's own files. Kept for traceability; not hand-edited.
