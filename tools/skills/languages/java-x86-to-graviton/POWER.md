---
name: java-x86-to-graviton
displayName: "Java x86 to Graviton Migration"
description: "Validates Java application compatibility with AWS Graviton (ARM64) architecture by analyzing native libraries, dependencies (including transitive), and architecture-specific code. Performs static analysis, applies ARM64-required dependency updates, documents Graviton JVM flag recommendations, and validates builds on ARM64."
keywords: ["java", "graviton", "arm64", "aarch64", "migration", "jvm", "native libraries", "dependencies"]
author: "AWS"
---

# Java Application AWS Graviton (ARM64) Compatibility Validation

Validate a Java application's readiness to run on AWS Graviton instances. This transformation identifies architecture-specific incompatibilities, validates native library ARM64 support, updates only ARM64-blocking dependencies, and tests on ARM64.

[summaries.md](summaries.md) indexes every file in this skill and when to read it — consult it for the full file map, or if you entered mid-skill without reading this file top to bottom.

## Scope Guardrails

**CRITICAL: Read [document_references/agent-scope-boundaries.md](document_references/agent-scope-boundaries.md) before starting.** This file contains the decision tree for every dependency analysis and prevents scope creep.

**In scope:** Native library ARM64 binaries, ARM64-blocking dependency updates, architecture detection code, x86-only JVM options that stop an ARM64 JVM, Graviton JVM flag recommendations (documented, not applied), CI changes that only add or switch an architecture, ARM64 build/test validation.

**Out of scope:** Java version changes, JDK distribution changes, general dependency modernization, security updates, code refactoring, .gitignore/.dockerignore changes.

## Skill Configuration (Optional)

If a `skill-config.md` exists at the project root, read it before Phase 1 and apply its preferences (build/validation JDK, build command, container registry and runtime, deployment and CI vocabulary) as overrides; if absent, use the neutral defaults in the phase docs. The configuration steers HOW the transformation runs but cannot widen scope: `agent-scope-boundaries.md` still binds, and the application's shipped JDK distribution stays unchanged (a configured JDK preference selects only the build/validation environment per Phase 3.0). See [document_references/skill-configuration.md](document_references/skill-configuration.md) for the fields, and [document_references/skill-config.template.md](document_references/skill-config.template.md) for a file to start from. Record any applied overrides in `01-project-assessment.md`.

## Entry Criteria

1. Java application currently running on x86 architecture
2. Source code and build scripts available
3. Current Java version documented (JDK 8+)
4. Build configs (Maven/Gradle, Dockerfiles if containerized)
5. ARM64 build/test environment access (Graviton EC2 or ARM64 containers)
6. Complete dependency list with current versions
7. Existing test suite
8. Tools the commands call: git, curl, `unzip`, `file` and `readelf`, the project's Maven or Gradle build, and a container runtime (Phase 3); the image check (Phase 1.4) uses the docker CLI

## Transformation Workflow

Copy this checklist into your response and check off each step:

```
ARM64 migration progress:
- [ ] Baseline commit; `graviton-validation/raw/` created; `skill-config.md` read if present
- [ ] 1.1 Deployment type, modules, dependency tree, risk categories (01, raw/)
- [ ] 1.2 Native files inside and outside archives, judged by content (02)
- [ ] 1.3 Each dependency: MUST UPGRADE / RECOMMENDED UPGRADE / COMPATIBLE / CHECK (03)
- [ ] 1.4 Architecture code, JVM options, images, deployment settings (04)
- [ ] 1.5 Java version and distribution recorded, not changed (01)
- [ ] 2.1 Native libraries resolved (02)
- [ ] 2.2 Only MUST UPGRADE dependencies updated, then the 1.2.1 scan re-run (03)
- [ ] 2.3 Architecture detection code updated (04)
- [ ] 2.4 Dockerfiles, build and deployment settings updated (04)
- [ ] 2.5 JVM flags documented, not applied (05)
- [ ] 3.0-3.1 ARM64 build; failures classified INFRA / ARM64 / PRE-EXISTING (06)
- [ ] 3.2 Tests on ARM64, results that change without failing (06)
- [ ] 3.3 Startup with the project's existing JVM options, and the loaded check (06)
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

**Commit after each checklist step that changes files** with `git add -A && git commit -m "<message>"`, the message naming the step; skip the commit when a step changed nothing.

### Documentation Setup

Before Phase 1, create the output structure. See [document_references/documentation-standards.md](document_references/documentation-standards.md) for required sections and templates.

```bash
mkdir -p graviton-validation/raw
```

Output files produced:

| File | Phase | Purpose |
|------|-------|---------|
| `01-project-assessment.md` | 1.1, 1.5 | Project structure, deployment type, Java env |
| `02-native-library-report.md` | 1.2, 2.1 | Native library findings and resolutions |
| `03-dependency-compatibility-report.md` | 1.3, 2.2 | Per-dependency ARM64 verdicts |
| `04-code-scan-findings.md` | 1.4, 2.3 | Architecture-specific code patterns |
| `05-jvm-configuration.md` | 2.5 | Graviton JVM flag recommendations (documented, not applied) |
| `06-build-test-results.md` | 3.0-3.3 | Build, test results, startup checks |
| `raw/dependency-tree-full.txt` | 1.1 | Raw dependency tree |
| `raw/dependency-tree-native.txt` | 1.3 | Filtered native-artifact tree |
| `00-summary.md` | End | Executive summary and exit criteria |

### Phase 1: Static Compatibility Analysis

Analyze the project without making changes. See [phases/phase1-static-analysis.md](phases/phase1-static-analysis.md) for detailed steps.

1. **1.1 Project Structure Analysis** - Deployment type, multi-module detection, dependency tree generation, component risk categorization
2. **1.2 Native Library Validation** - Scan for .so files (bundled and runtime-extracted), apply tiered FAIL/WARN/CHECK/PASS policy
3. **1.3 Dependency ARM64 Compatibility** - Analyze full transitive tree, classify as MUST UPGRADE / RECOMMENDED UPGRADE / COMPATIBLE (CHECK until the evidence decides)
4. **1.4 Architecture-Specific Code Detection** - Find `os.arch` checks, JNI/JNA usage missing ARM64 handling, x86-only JVM options, and deployment settings that pick x86, set or absent
5. **1.5 Java Version Check** - Document version and distribution (do NOT change either)

### Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues only. See [phases/phase2-resolution.md](phases/phase2-resolution.md) for detailed steps.

1. **2.1 Native Library Resolution** - Cross-compile or obtain ARM64 .so files, update loading logic
2. **2.2 Dependency Updates** - Update ONLY MUST UPGRADE dependencies (including transitive via dependencyManagement)
3. **2.3 Architecture Code Updates** - Add `aarch64` handling to architecture detection code
4. **2.4 Build Config Updates** - Dockerfile `--platform` annotations (preserve current base images); no Maven profile activated by the host's architecture
5. **2.5 JVM Recommendations** - Document version-gated Graviton JVM flags for the team to evaluate; do not apply them

### Phase 3: ARM64 Validation & Testing

Build and test on ARM64. See [phases/phase3-validation.md](phases/phase3-validation.md) for detailed steps.

1. **3.0 Build Environment Prep** - Java runtime alignment for annotation processor compatibility (session-scoped only)
2. **3.1 Build Validation** - Full build, classify failures as INFRA/ARM64/PRE-EXISTING
3. **3.2 Functional Testing** - Execute test suite, classify failures, check results that can differ by architecture, determine final build
4. **3.3 Startup Validation** - Verify application starts with its existing JVM options, no crashes
5. **Write 00-summary.md** - Consolidate exit criteria using template from documentation-standards.md

## Exit Criteria

A criterion that runs on ARM64 passes only on a Graviton host or the target, such as the arm64 Lambda function; one that ran only under emulation or on another arm64 machine is NOT RUN (Phase 3, "Match the production hosts").

### Must Pass
1. Application compiles on ARM64 without errors
2. Native libraries load on ARM64 (or fallbacks function)
3. All MUST UPGRADE dependencies updated to ARM64-compatible versions
4. No ARM64-specific runtime errors
5. Container images build on ARM64 (if containerized)

### Test Criteria
6. Test suite executes on ARM64
7. Failures classified: `INFRA` (non-blocking) / `ARM64` (blocking) / `PRE-EXISTING` (non-blocking)
8. No ARM64-related test failures

### Startup Criteria
9. Application starts on ARM64 without crashes
10. The project's existing JVM options accepted on ARM64 without errors

### Documentation Criteria
11. All files in `graviton-validation/` using canonical names from documentation-standards.md

## Test Failure Handling

Infrastructure failures (a missing database, Docker daemon, environment variable or credential, or one that fails the same way on the x86 baseline) are non-blocking: exclude only those tests with the build tool's own filter, list them under CHECK Items, and take that run as the final build (Phase 3.1, Build Strategy step 3). A build that skips every test is never the final build.

ARM64 failures are blocking. Do not skip tests; the failing build is the final build.

## User Responsibility (Post-Transformation)

- Performance benchmarking and load testing
- Integration testing with external services
- CI/CD changes beyond architecture (credentials, deployment steps, triggers, tool versions), recommended in the vocabulary of `ci.system` when `skill-config.md` defines it; changes that only add or switch an architecture are applied in Phase 2.4 unless `ci.changes` is `recommend`

## Notes

- ARM64 execution environment required for full validation. On x86, static analysis only.
- Multi-module projects require analysis of all submodules and the full transitive dependency tree
- Graviton instances perform best at higher CPU utilization (70%+ recommended for testing)
