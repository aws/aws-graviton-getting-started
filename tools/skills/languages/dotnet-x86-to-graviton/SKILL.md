---
name: dotnet-x86-to-graviton
description: Validates .NET application compatibility with AWS Graviton (ARM64) architecture by checking, by content, that every resolved NuGet package (including transitive) ships an aarch64 native file for each target runtime identifier and the target's C library, glibc, libstdc++ and page size, and by checking committed native files, P/Invoke loads, x86 intrinsics, x64 project settings, Dockerfiles, Lambda descriptors and Windows-only APIs. Performs static analysis, applies ARM64-required package, code and build fixes (including the move from Windows or .NET Framework to modern .NET on Linux, after approval), documents Graviton runtime recommendations, and validates builds, publish outputs, tests and startup on ARM64. Supports PackageReference, central package management, lock files, packages.config and Paket. Use when migrating .NET workloads from x86 to Graviton, validating ARM64 readiness, or diagnosing DllNotFoundException and other native-library failures on arm64.
metadata:
  author: AWS
  version: "1.0"
---

# .NET Application AWS Graviton (ARM64) Compatibility Validation

Validate a .NET application's readiness to run on AWS Graviton instances. This transformation verifies that every resolved NuGet package ships an aarch64 native file for each target runtime identifier (RID) where it needs one, identifies architecture-specific incompatibilities in committed native files, project settings, code and deployment descriptors, moves Windows and .NET Framework applications to modern .NET on Linux where that is the starting point, updates only ARM64-blocking dependencies, and tests on ARM64.

[summaries.md](summaries.md) indexes every file in this skill and when to read it: consult it for the full file map, or if you entered mid-skill without reading this file top to bottom.

## Scope Guardrails

**CRITICAL: Read [document_references/agent-scope-boundaries.md](document_references/agent-scope-boundaries.md) before starting.** This file contains the decision tree for every dependency analysis and prevents scope creep.

**In scope:** linux-arm64 native files (and linux-musl-arm64 for Alpine targets) for every resolved package, direct and transitive; ARM64-blocking package updates and lock file regeneration; native files committed to the repository and the code that loads them; architecture detection code and x86 intrinsics; project settings that pin x64 (`PlatformTarget`, `RuntimeIdentifier`); Dockerfile platform settings, Lambda architectures and deployment scripts; AWS SDK versions without IMDSv2 support where the target requires it; for Windows and .NET Framework starting points, the move to modern .NET on Linux (one decision for the solution, after one approval); Graviton runtime recommendations (documented, never applied); ARM64 build, publish, test and startup validation.

**Out of scope:** target framework and SDK changes other than those Graviton requires (gated by `dotnet.framework_bump`), package-management switches (central package management, lock files, Paket), base image changes, general dependency modernization, security updates (including NuGet audit warnings), code refactoring, .gitignore/.dockerignore and CI changes. Windows Forms, WPF and ASP.NET Web Forms have no Linux path: they are BLOCKERs, documented with options ([document_references/windows-to-linux.md](document_references/windows-to-linux.md)).

> **Verify the native files, never the package name or the exit code.** Whether a package runs on Graviton is a fact about the files its exact version ships for each RID, judged by content: the ELF machine, the C library, the glibc and libstdc++ versions and the other libraries they need, and the page size they were linked for. `dotnet publish -r linux-arm64` exits 0 with native files missing, and a Windows Forms project publishes for linux-arm64 too. Every verdict cites the per-RID check or the output scan; see [document_references/nuget-native-assets.md](document_references/nuget-native-assets.md).

## Skill Configuration (Optional)

If a `skill-config.md` exists at the project root, read it before Phase 1 and apply its preferences (target RIDs, validation SDK source, SDK install hint, test command, container registry and runtime, deployment and CI vocabulary) as overrides; if absent, use the neutral defaults in the phase docs. The configuration steers HOW the transformation runs but cannot widen scope: `agent-scope-boundaries.md` still binds, and the project's target frameworks stay unchanged unless `dotnet.framework_bump` approves a change Graviton requires (a configured SDK source selects only the build/validation SDK per Phase 3.0). See [document_references/skill-configuration.md](document_references/skill-configuration.md). Record any applied overrides in `01-project-assessment.md`.

## Entry Criteria

1. .NET application currently running on x86: modern .NET (.NET Core, .NET 5 and later) on Linux or Windows, or .NET Framework on Windows
2. Source code and build scripts available
3. Current target frameworks and SDK documented (Phase 1.1 reads them from the evaluated project files and `global.json`)
4. Build configs (solutions, project files, `Directory.Build.props`/`Directory.Packages.props`, `NuGet.config`, lock files, Dockerfiles if containerized, Lambda templates)
5. ARM64 build/test environment access (Graviton EC2 or ARM64 containers; an x86 host with QEMU emulation can run published output and tests built on the host, not builds, and Microsoft does not support .NET under QEMU)
6. A .NET SDK that builds the target frameworks, Python 3.6 or later for the check program, and access to the NuGet feeds the project restores from
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
3. After native library resolution (Phase 2.1 - committed native files built for aarch64, loading code updated)
4. After dependency updates (Phase 2.2 - package versions, RIDs and lock files changed)
5. After architecture code updates (Phase 2.3 - source and scripts changed)
6. After project settings, Dockerfile and deployment descriptor updates (Phase 2.4)
7. After runtime recommendations (Phase 2.5)
8. After build validation (Phase 3.1 - builds, publishes and output scans documented)
9. After final validation and summary (Phase 3.3 + 00-summary.md written)

Not every project will have all steps (e.g., no Dockerfile changes for host-based deployments, no native library resolution if none found). Commit whenever files change, skip commits for steps that produced no changes. Publish outputs and SDKs created for validation live outside the project tree (`${TMPDIR:-/tmp}`), but `dotnet restore` and `dotnet build` write `obj/` and `bin/` inside each project folder: if the repository does not ignore them, stage the changed files by name instead of `git add -A` (adding a `.gitignore` is out of scope).

### Documentation Setup

Before Phase 1, create the output structure. See [document_references/documentation-standards.md](document_references/documentation-standards.md) for required sections and templates.

```bash
mkdir -p graviton-validation/raw
```

Output files produced:

| File | Phase | Purpose |
|------|-------|---------|
| `01-project-assessment.md` | 1.1, 1.5 | Deployment type, starting point, solution structure, package management, target frameworks and SDK, target OS and libc |
| `02-native-library-report.md` | 1.2, 2.1 | Committed native files, native loads, executables and downloads, OS packages |
| `03-dependency-compatibility-report.md` | 1.3, 2.2 | Per-package verdicts with per-RID evidence |
| `04-code-scan-findings.md` | 1.4, 2.3, 2.4 | Architecture checks, intrinsics, project settings, Windows-only APIs, Dockerfile and descriptor issues |
| `05-runtime-configuration.md` | 2.5 | Graviton runtime recommendations (documented, not applied) |
| `06-build-test-results.md` | 3.0-3.3 | Builds, publishes and output scans, tests, startup checks |
| `raw/project-properties.txt` | 1.1 | Evaluated properties of every project |
| `raw/dependency-tree.json` | 1.1 | Every resolved package with its reference chain |
| `raw/native-assets.txt` | 1.1, 2.2 | Per-RID native report for every package |
| `raw/dependency-tree-native.txt` | 1.3 | Packages with native files, with their chains |
| `raw/repo-native-scan.txt` | 1.2 | Committed native files and assemblies, by content |
| `raw/ca1416.txt` | 1.4 | Windows-only API call sites (Windows starting points) |
| `raw/output-scan.txt` | 3.1 | Publish outputs, by content |
| `00-summary.md` | End | Executive summary and exit criteria |

### Phase 1: Static Compatibility Analysis

Analyze the project without making changes. See [phases/phase1-static-analysis.md](phases/phase1-static-analysis.md) for detailed steps; per-mechanism commands are in [document_references/package-management-mapping.md](document_references/package-management-mapping.md).

1. **1.1 Project Structure Analysis** - Deployment type, solution and project structure (including projects no solution lists), starting point (modern .NET on Linux or Windows, .NET Framework), target OS and libc, dependency tree with the per-RID native check, component risk categorization
2. **1.2 Native Library Validation** - Scan every committed native file and assembly by content (never by name or folder), P/Invoke and `NativeLibrary` loads, executables run and binaries downloaded at run, build or deploy time, OS packages in images, apply tiered FAIL/WARN/PASS policy
3. **1.3 Dependency ARM64 Compatibility** - Classify every resolved package (including transitives) by its per-RID native files as MUST UPGRADE / RECOMMENDED / COMPATIBLE, check AWS SDK IMDSv2 support, find build-tool packages with OS/arch RIDs
4. **1.4 Architecture-Specific Code Detection** - Find architecture checks, x86 intrinsics without `IsSupported` checks, fixed vector widths, `PlatformTarget`/`RuntimeIdentifier` pins, Windows-only APIs (CA1416), amd64 Dockerfile pins and shell architecture gates
5. **1.5 .NET Version Compatibility Check** - Document target frameworks, SDK and live support status (do NOT change them unless `dotnet.framework_bump` allows; a change is one decision for the whole solution)

### Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues only. See [phases/phase2-resolution.md](phases/phase2-resolution.md) for detailed steps.

1. **2.1 Native Library Resolution** - Build committed native files for aarch64 (plain C libraries can be cross-compiled; others on ARM64 hardware), add the Arm64 path to the code that loads them
2. **2.2 Dependency Updates** - Update ONLY MUST UPGRADE packages to the lowest version whose linux-arm64 native files load on the target, through the project's own mechanism, add the target RIDs and regenerate lock files, substitute or change target frameworks only with user confirmation
3. **2.3 Architecture Code Updates** - Add `Arm64` handling to architecture checks, `IsSupported` checks with portable paths for intrinsics, and `aarch64` to scripts
4. **2.4 Build Config Updates** - Remove x64 `PlatformTarget` and `RuntimeIdentifier` pins, publish in Dockerfiles on `$BUILDPLATFORM` with `-a $TARGETARCH` (preserve current base images), set Lambda functions to `arm64`, update the manifests the project ships
5. **2.5 Runtime Recommendations** - Document repo-sourced Graviton runtime settings with their evidence level; do not apply them

### Phase 3: ARM64 Validation & Testing

Build and test on ARM64. See [phases/phase3-validation.md](phases/phase3-validation.md) for detailed steps.

1. **3.0 Build Environment Prep** - .NET SDK alignment (target frameworks, solution format, tools; session-scoped only)
2. **3.1 Build Validation** - Build and test as the repository does, publish every executable project for each target RID and scan each output by content, classify failures as INFRA/ARM64/PRE-EXISTING
3. **3.2 Functional Testing** - Run the tests on ARM64 (on x86 hosts: built natively, run in an arm64 container), classify failures, determine final build
4. **3.3 Startup Validation** - Verify the application starts with `RuntimeInformation.ProcessArchitecture` reporting `Arm64`, every native library loads, IMDSv2 credentials and Lambda invocations work
5. **Write 00-summary.md** - Consolidate exit criteria using template from documentation-standards.md

## Exit Criteria

### Must Pass
1. Every resolved package gives each target RID an aarch64 native file for the target's libc, glibc, libstdc++ and page size, or is managed only, or is a documented user decision
2. Committed native files and assemblies run on ARM64 (aarch64 builds, AnyCPU assemblies), or documented fallbacks function
3. All MUST UPGRADE items applied, or documented as user decisions
4. Every project that moves to Linux publishes for each target RID, and every output scans without findings
5. Container images build for linux/arm64 and their contents scan without findings (if containerized)

### Test Criteria
6. Test suite executes on ARM64
7. Failures classified: `INFRA` (non-blocking) / `ARM64` (blocking) / `PRE-EXISTING` (non-blocking)
8. No ARM64-related test failures

### Startup Criteria
9. Application starts on ARM64 without crashes (`RuntimeInformation.ProcessArchitecture` reports `Arm64`) and every native library loads
10. Target frameworks and SDK unchanged, or changed only through an approved `dotnet.framework_bump`

### Documentation Criteria
11. All files in `graviton-validation/` using canonical names from documentation-standards.md

## Test Failure Handling

Infrastructure failures (missing database, services, credentials, network or feed access, OS packages missing from the test environment) are non-blocking. Classify and document them, then run the final build without tests (the Phase 3.1 build, publish and scan, without the test step):
- `dotnet restore <solution>` (add `--locked-mode` when the repository has `packages.lock.json` files), then `dotnet build <solution> -c Release --no-restore`
- the Phase 3.1 publish and output scan for each target RID

ARM64 failures are blocking. Do not skip tests or projects; the failing build is the final build.

## User Responsibility (Post-Transformation)

- Performance benchmarking and load testing
- Integration testing with external services
- CI/CD pipeline configuration for ARM64 builds (if `skill-config.md` defines `ci.system`, phrase this recommendation in that system's vocabulary; the skill makes no CI changes itself)

## Notes

- ARM64 execution environment required for full validation. On x86 without a container runtime, static analysis and output scans only; under QEMU emulation, run published output and tests built on the host, never builds, and treat the results as smoke tests (see Phase 3 "Emulation limits").
- Solutions with many projects require analysis of every project, including projects no solution lists, and its full resolved package set
- The per-RID check is one Python program embedded in [document_references/nuget-native-assets.md](document_references/nuget-native-assets.md) §11; its block writes it to `${TMPDIR:-/tmp}` once per session, and the other blocks call it from there
- The bash blocks were executed in bash 5.2 and zsh 5.9 on Linux. On Windows, run the skill in a WSL 2 distribution, which runs a Linux kernel ([Microsoft](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)), with the project in the Linux file system
- Every Graviton vCPU maps to a physical core (no SMT), so performance scales more linearly with CPU load than on x86; load test to the maximum sustainable load before comparing instance types ([transition guide](https://github.com/aws/aws-graviton-getting-started/blob/main/transition-guide.md))
