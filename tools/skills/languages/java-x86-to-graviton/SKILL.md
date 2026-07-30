---
name: java-x86-to-graviton
description: Validates Java application compatibility with AWS Graviton (ARM64) architecture by analyzing native libraries, dependencies (including transitive), and architecture-specific code. Performs static analysis, applies ARM64-required dependency updates, configures Graviton JVM flags, and validates builds on ARM64. Use when migrating Java workloads from x86 to Graviton, validating ARM64 readiness, or running AWS Transform Custom java-x86-to-graviton transformations.
metadata:
  author: AWS
  version: "1.0"
---

# Java Application AWS Graviton (ARM64) Compatibility Validation

Validate a Java application's readiness to run on AWS Graviton instances. This transformation identifies architecture-specific incompatibilities, validates native library ARM64 support, updates only ARM64-blocking dependencies, and tests on ARM64.

## Scope Guardrails

**CRITICAL: Read [document_references/agent-scope-boundaries.md](document_references/agent-scope-boundaries.md) before starting.** This file contains the decision tree for every dependency analysis and prevents scope creep.

**In scope:** Native library ARM64 binaries, ARM64-blocking dependency updates, architecture detection code, Graviton JVM flags, ARM64 build/test validation.

**Out of scope:** Java version changes, JDK distribution changes, general dependency modernization, security updates, code refactoring, .gitignore/.dockerignore changes.

## Skill Configuration (Optional)

If a `skill-config.md` exists at the project root, read it before Phase 1 and apply its preferences (build/validation JDK, build command, container registry and runtime, deployment and CI vocabulary) as overrides; if absent, use the neutral defaults in the phase docs. The configuration steers HOW the transformation runs but cannot widen scope — `agent-scope-boundaries.md` still binds, and the application's shipped JDK distribution stays unchanged (a configured JDK preference selects only the build/validation environment per Phase 3.0). See [document_references/skill-configuration.md](document_references/skill-configuration.md). Record any applied overrides in `01-project-assessment.md`.

## Entry Criteria

1. Java application currently running on x86 architecture
2. Source code and build scripts available
3. Current Java version documented (JDK 8+)
4. Build configs (Maven/Gradle, Dockerfiles if containerized)
5. ARM64 build/test environment access (Graviton EC2 or ARM64 containers)
6. Complete dependency list with current versions
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
3. After native library resolution (Phase 2.1 - .so files updated)
4. After dependency updates (Phase 2.2 - pom.xml/build.gradle changed)
5. After architecture code updates (Phase 2.3 - Java source changed)
6. After Dockerfile/build config updates (Phase 2.4)
7. After JVM optimization config (Phase 2.5)
8. After build validation (Phase 3.1 - build results documented)
9. After final validation and summary (Phase 3.3 + 00-summary.md written)

Not every project will have all steps (e.g., no Dockerfile changes for host-based deployments, no native library resolution if none found). Commit whenever files change, skip commits for steps that produced no changes.

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
| `05-jvm-configuration.md` | 2.5 | Graviton JVM flags |
| `06-build-test-results.md` | 3.0-3.3 | Build, test results, startup checks |
| `raw/dependency-tree-full.txt` | 1.1 | Raw dependency tree |
| `raw/dependency-tree-native.txt` | 1.3 | Filtered native-artifact tree |
| `00-summary.md` | End | Executive summary and exit criteria |

### Phase 1: Static Compatibility Analysis

Analyze the project without making changes. See [phases/phase1-static-analysis.md](phases/phase1-static-analysis.md) for detailed steps.

1. **1.1 Project Structure Analysis** - Deployment type, multi-module detection, dependency tree generation, component risk categorization
2. **1.2 Native Library Validation** - Scan for .so files (bundled and runtime-extracted), apply tiered FAIL/WARN/PASS policy
3. **1.3 Dependency ARM64 Compatibility** - Analyze full transitive tree, classify as MUST UPGRADE / RECOMMENDED / COMPATIBLE
4. **1.4 Architecture-Specific Code Detection** - Find `os.arch` checks, JNI/JNA usage missing ARM64 handling
5. **1.5 Java Version Check** - Document version and distribution (do NOT change either)

### Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues only. See [phases/phase2-resolution.md](phases/phase2-resolution.md) for detailed steps.

1. **2.1 Native Library Resolution** - Cross-compile or obtain ARM64 .so files, update loading logic
2. **2.2 Dependency Updates** - Update ONLY MUST UPGRADE dependencies (including transitive via dependencyManagement)
3. **2.3 Architecture Code Updates** - Add `aarch64` handling to architecture detection code
4. **2.4 Build Config Updates** - Add ARM64 Maven profile, Dockerfile `--platform` annotations (preserve current base images)
5. **2.5 JVM Optimizations** - Apply version-gated Graviton JVM flags, validate with `java <flags> -version`

### Phase 3: ARM64 Validation & Testing

Build and test on ARM64. See [phases/phase3-validation.md](phases/phase3-validation.md) for detailed steps.

1. **3.0 Build Environment Prep** - Java runtime alignment for annotation processor compatibility (session-scoped only)
2. **3.1 Build Validation** - Full build, classify failures as INFRA/ARM64/PRE-EXISTING
3. **3.2 Functional Testing** - Execute test suite, classify failures, determine final build
4. **3.3 Startup Validation** - Verify application starts, JVM flags accepted, no crashes
5. **Write 00-summary.md** - Consolidate exit criteria using template from documentation-standards.md

## Exit Criteria

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
10. JVM flags accepted without errors

### Documentation Criteria
11. All files in `graviton-validation/` using canonical names from documentation-standards.md

## Test Failure Handling

Infrastructure failures (missing DB, Docker, env vars) are non-blocking. Classify and document them, then run the final build without tests:
- Gradle: `./gradlew clean build -x test`
- Maven: `mvn clean install -DskipTests`

ARM64 failures are blocking. Do not skip tests; the failing build is the final build.

## User Responsibility (Post-Transformation)

- Performance benchmarking and load testing
- Integration testing with external services
- CI/CD pipeline configuration for ARM64 builds (if `skill-config.md` defines `ci.system`, phrase this recommendation in that system's vocabulary; the skill makes no CI changes itself)

## Notes

- ARM64 execution environment required for full validation. On x86, static analysis only.
- Multi-module projects require analysis of all submodules and the full transitive dependency tree
- Graviton instances perform best at higher CPU utilization (70%+ recommended for testing)
