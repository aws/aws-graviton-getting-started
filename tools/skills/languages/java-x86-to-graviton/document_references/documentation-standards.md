# ARM64 Transformation — Documentation Standards

## Purpose
This document defines the standard output folder structure, canonical filenames, and content requirements for all documentation produced during an ARM64 Graviton compatibility transformation. Adherence to this standard ensures consistency across transformation runs regardless of which agent executes the work.

## Output Folder Structure

All transformation output documents MUST be written to a single folder named `graviton-validation/` in the project root. The agent MUST create this folder and its `raw/` subfolder at the start of Phase 1 before any analysis begins.

```
<project-root>/
└── graviton-validation/
    ├── 00-summary.md                        # Final roll-up of all findings and exit criteria
    ├── 01-project-assessment.md             # Project structure, deployment type, Java environment
    ├── 02-native-library-report.md          # All .so / native library findings and resolutions
    ├── 03-dependency-compatibility-report.md # Per-dependency ARM64 compatibility verdicts
    ├── 04-code-scan-findings.md             # Architecture-specific code patterns detected
    ├── 05-jvm-configuration.md              # Graviton-optimized JVM flags and profiles
    ├── 06-build-test-results.md             # Build validation, test results, failure classification
    └── raw/                                 # Machine-generated artifacts (not hand-authored)
        ├── dependency-tree-full.txt         # Full dependency tree output
        └── dependency-tree-native.txt       # Filtered tree (native-code artifacts only)
```

## Agent Instructions

1. **Create `graviton-validation/` and `graviton-validation/raw/` at the start of Phase 1.** This is the first action before any analysis.
2. **Use EXACTLY these filenames.** Do not rename, renumber, or create additional top-level files.
3. **Write to each file progressively** as the corresponding phase completes. Do not wait until the end to produce all documentation.
4. **Raw files go in `raw/`.** Only machine-generated command output belongs in `raw/`. Do not put authored content there.
5. **`00-summary.md` is written last**, after all other files are complete. It references (not duplicates) the detail in files 01–06.
6. **If a section has no findings**, include the section header with an explicit "No findings" statement. Do not omit empty sections — their absence is ambiguous.
7. **Do not create documentation files outside `graviton-validation/`.** All transformation documentation lives in this single folder.

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
| 9 | JVM flags accepted without errors | ✅ PASS / ❌ FAIL | |

## Changes Made
<Brief summary of dependency updates, native library resolutions, code changes.
Reference detail files: 02-native-library-report.md, 03-dependency-compatibility-report.md, 04-code-scan-findings.md>

## Remaining Concerns
<Any unresolved issues, user-responsibility items, or known limitations>
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
| Library | Source JAR/Location | Architecture | Verdict | Resolution |
|---------|-------------------|--------------|---------|------------|
| libfoo.so | commons-crypto-1.1.0.jar | x86_64 only | FAIL | Upgraded to 1.2.0 (includes aarch64) |
| libbar.so | app-native/lib/ | ARM aarch64 | PASS | No action needed |

## Runtime-Extracted Libraries
| Dependency | Artifact | Extracts Native Code | ARM64 Support in Current Version | Verdict | Resolution |
|------------|----------|---------------------|----------------------------------|---------|------------|
| netty-transport-native-epoll | 4.1.68.Final | Yes | Yes (linux-aarch_64 classifier) | PASS | No action needed |
| snappy-java | 1.1.1.7 | Yes | No (JAR has no Linux/aarch64/libsnappyjava.so) | FAIL | Upgraded to 1.1.4 |

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
| Dependency | Current Version | Minimum ARM64 Version | Applied Version | ARM64 Issue | Evidence |
|------------|----------------|----------------------|-----------------|-------------|----------|
| org.xerial.snappy:snappy-java | 1.1.1.7 | 1.1.4 | 1.1.4 | JAR has no Linux/aarch64/libsnappyjava.so | `unzip -l ... \| grep aarch64` empty; UnsatisfiedLinkError on aarch64 |

## RECOMMENDED UPGRADE (Non-Blocking)
| Dependency | Current Version | Recommended Version | Reason | Action Taken |
|------------|----------------|--------------------|---------|----|
| <dep> | <ver> | <ver> | ARM64 perf improvement | Documented for user |

## COMPATIBLE (No Action Needed)
| Dependency | Version | Basis |
|------------|---------|-------|
| junit:junit | 3.8.1 | Pure Java — no native code |
| com.google.guava:guava | 31.1-jre | Pure Java — no native code |

## Transitive Dependency Resolutions
| Transitive Dependency | Pulled In By | Issue | Resolution Method |
|-----------------------|-------------|-------|-------------------|
| org.xerial.snappy:snappy-java 1.1.1.7 | kafka-clients 2.7.0 | JAR has no Linux/aarch64 binary | dependencyManagement override to 1.1.4 |
```

---

### `04-code-scan-findings.md` — Architecture-Specific Code Detection

**Created:** Phase 1.4, updated in Phase 2.3 (resolution)
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

## Changes Applied
<Summary of code changes made in Phase 2.3 to add ARM64 handling>

## No Findings
<If no architecture-specific code was detected, state explicitly:>
No architecture-specific code patterns, JNI, or JNA usage detected. All code is pure Java.
```

---

### `05-jvm-configuration.md` — Graviton JVM Optimization

**Created:** Phase 2.5
**Purpose:** Records the JVM flags applied, version-gated rationale, and validation results.

**Required sections:**
```markdown
# Graviton JVM Configuration

## Target Java Version
<JDK version used for flag selection, e.g., JDK 17>

## Applied JVM Flags
| Flag | Applicable JDK Versions | Workload Type | Expected Impact |
|------|------------------------|---------------|-----------------|
| -XX:-TieredCompilation | 11, 17, 21+ | Moderate lock contention | Reduced compilation overhead |

## Flags NOT Applied (Version-Gated)
| Flag | Reason Not Applied |
|------|--------------------|
| -XX:CompilationMode=high-only | Removed in JDK 21+; project uses JDK 21 |

## Flag Validation
<Output of: java <flags> -version>
<Confirm all flags accepted without errors>

## Configuration Profiles
<If multiple profiles were created for different workload types, list them here>
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
- **JVM flags accepted:** ✅ Yes | ❌ No
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

## Mapping: Transformation Steps → Output Files

| # | Transformation Step | What Is Produced | Output File |
|---|---|---|---|
| 1 | 1.1 step 1 — Deployment type | Containerized vs host-based | `01-project-assessment.md` |
| 2 | 1.1 step 2 — Dependency tree generation | Raw tree output | `raw/dependency-tree-full.txt` |
| 3 | 1.1 step 4 — Component risk categorization | CRITICAL/HIGH/MEDIUM/LOW table | `01-project-assessment.md` |
| 4 | 1.2.1 — Statically bundled .so scan | Architecture per .so file | `02-native-library-report.md` |
| 5 | 1.2.2 — Runtime-extracted native detection | Libraries extracting native code | `02-native-library-report.md` |
| 6 | 1.2.3 — Tiered validation verdicts | FAIL/WARN/PASS per library | `02-native-library-report.md` |
| 7 | 1.2.3 step 3 — Recompilation requirements | Resolution notes | `02-native-library-report.md` |
| 8 | 1.3 step 1 — Filtered transitive tree | Native-artifact-only tree | `raw/dependency-tree-native.txt` |
| 9 | 1.3 step 3 — Compatibility report | MUST UPGRADE / RECOMMENDED / COMPATIBLE | `03-dependency-compatibility-report.md` |
| 10 | 1.3 step 4 — Per-dependency findings | Detailed blocks per dependency | `03-dependency-compatibility-report.md` |
| 11 | 1.4 — Code scan | Architecture patterns, JNI/JNA usage | `04-code-scan-findings.md` |
| 12 | 1.5 — Java version & distribution | Version and distro record | `01-project-assessment.md` |
| 13 | 2.1 — Native library resolution | Resolution per .so, fallback decisions | `02-native-library-report.md` |
| 14 | 2.5 step 2 — JVM flag documentation | Flags, rationale, impact | `05-jvm-configuration.md` |
| 15 | 2.5 step 3 — Config profiles | Workload-specific flag sets | `05-jvm-configuration.md` |
| 16 | 3.0 — Annotation processor notes | Processor/version requiring alignment | `06-build-test-results.md` |
| 17 | 3.0 — Blocker: no compatible JDK | Requirement documentation | `06-build-test-results.md` |
| 18 | 3.1 — Build test classification | INFRA/ARM64/PRE-EXISTING per failure | `06-build-test-results.md` |
| 19 | 3.2 — Functional test results | All test results, classification | `06-build-test-results.md` |
| 20 | 3.3 — Startup validation | Start/flags/crash checks | `06-build-test-results.md` |
| 21 | Exit — Summary | Roll-up of all findings and exit criteria | `00-summary.md` |
