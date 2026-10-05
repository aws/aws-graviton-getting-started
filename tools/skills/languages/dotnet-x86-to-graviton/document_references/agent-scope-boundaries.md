# ARM64 Transformation - Agent Scope Boundaries

## 🎯 Primary Objective
Validate .NET application compatibility with AWS Graviton (ARM64) architecture.  
**Focus ONLY on ARM64-specific compatibility issues.**

Graviton runs Linux only, so for a .NET Framework application, or a modern .NET application that runs on Windows, the move to modern .NET on Linux is itself the ARM64 requirement. It is in scope, approved once for the whole solution (§7 below), and only with changes that modern .NET supports on Linux.

## Quick Reference: ARM64 Dependency Update Decision Tree

Use this decision tree for EVERY dependency analysis:

```
Is this dependency update required for ARM64 compatibility?
│
├─ Does the package have native files for the source or target RID (per-RID check, by content)?
│  ├─ YES → Does the target RID get an aarch64 build for the target's libc and glibc?
│  │  ├─ NO → ✅ MUST UPGRADE (ARM64 native file missing or wrong)
│  │  └─ YES → ✅ COMPATIBLE (has ARM64 support)
│  └─ NO (managed only) → ✅ COMPATIBLE (managed code runs on all architectures)
│
├─ Does current version FAIL to build or publish for linux-arm64?
│  ├─ YES → Check why:
│  │  ├─ Missing ARM64 executable for a build tool? → ✅ MUST UPGRADE
│  │  ├─ PlatformTarget, RuntimeIdentifier or lock file pinned to x64? → ✅ MUST UPGRADE (project setting)
│  │  └─ Other reason? → Investigate root cause
│  └─ NO → Continue checking...
│
├─ Does current version FAIL to run on ARM64?
│  ├─ YES → Check why:
│  │  ├─ DllNotFoundException, or FileNotFoundException for an assembly built for x64? → ✅ MUST UPGRADE
│  │  ├─ PlatformNotSupportedException from x86 intrinsics or a Windows-only API? → ✅ MUST UPGRADE (code)
│  │  ├─ Documented ARM64 bug? → ✅ MUST UPGRADE
│  │  └─ Other reason? → Investigate root cause
│  └─ NO → Continue checking...
│
└─ Is the only reason "old version", "out of support" or "best practice"?
   └─ YES → ❌ OUT OF SCOPE (not an ARM64 issue)

RESULT:
- If no ARM64-specific issue found → Mark COMPATIBLE, do NOT upgrade
- If ARM64-specific issue found → Document evidence and upgrade
```

**Quick Test Questions:**
1. ❓ Will keeping this version cause the ARM64 build or publish to fail?
2. ❓ Will keeping this version cause the ARM64 runtime to fail?
3. ❓ Is there documented evidence of ARM64 incompatibility?

If all answers are **NO** → **Do not upgrade** (out of scope)

A successful `dotnet publish -r linux-arm64` answers none of these questions: it exited 0 with native files missing, and for a Windows Forms project ([nuget-native-assets.md §2](nuget-native-assets.md#2-how-the-sdk-selects-native-files)).

## ✅ IN SCOPE: What to Fix

### 1. Native Library Issues
- ✅ Packages whose target RID gets no aarch64 native file, or one built for the other C library or a newer glibc than the target has
- ✅ Committed native files (`.so` files, prebuilt helpers) that are x86-64 builds
- ✅ Example: SkiaSharp.NativeAssets.Linux 1.68.3 → 2.80.0 (1.68.3 ships `runtimes/linux-x64` only; 2.80.0 is the lowest with `runtimes/linux-arm64`)

> ⚠️ **Verify the package content, never the version number.** Whether a version has an arm64 build is a fact about the files restore selects, judged by their ELF headers. Folder and file names mislead: Microsoft.ML.OnnxRuntime 1.10.0 contains an aarch64 build in `runtimes/linux-aarch64/`, a folder NuGet never selects, and Stub.System.Data.SQLite.Core.NetStandard names its x86-64 Linux library `SQLite.Interop.dll`. Use the per-RID check and `probe` ([nuget-native-assets.md §3 and §5](nuget-native-assets.md#3-the-per-rid-check)).
>
> **Make a missing version fail loudly.** `probe` exits 2 and prints NuGet's error when a version does not exist (`error NU1102: Unable to find package SkiaSharp.NativeAssets.Linux with version (= 9.9.9)`), so an absent package is never read as "no arm64 file". A version missing from an internal feed is INFRA ([package-management-mapping.md §2.6](package-management-mapping.md#26-nugetconfig-feeds-and-package-source-mapping)).

### 2. Build Tool Artifacts
- ✅ Packages that run executables on the build host or in tests, when the build, the tests or the image build run on arm64
- ✅ Example: Grpc.Tools 2.36.4 → 2.37.0 (2.36.4 has no `tools/linux_arm64`; 2.37.0 is the lowest that does)
- ✅ Native AOT publishing for linux-arm64 runs the compiler and linker on the build host: build it on arm64 (Phase 2.4)

### 3. Architecture Detection
- ✅ Code that checks `Architecture.X64`, or an x64 RID string, without an Arm64 branch
- ✅ Native library resolvers that build a path from the architecture and know only x64
- ✅ x86 hardware intrinsics called without an `IsSupported` check (they throw `PlatformNotSupportedException` on Arm64)
- ✅ Tests that assert an x64 RID or architecture: fix the test, not the code

### 4. Documented ARM64 Bugs
- ✅ Current version has known ARM64-specific runtime failures
- ✅ Must have issue tracker evidence or release notes
- ✅ Example: "Version X causes crash only on ARM64"

### 5. Project Settings and Lock Files
- ✅ `<PlatformTarget>x64</PlatformTarget>` (the assembly does not load in an arm64 process)
- ✅ `<RuntimeIdentifier>linux-x64</RuntimeIdentifier>` or a Windows RID in a project file (the output is x64 unless the build passes another RID)
- ✅ `<RuntimeIdentifiers>` and `packages.lock.json` without the target RID (a locked restore fails with NU1004): add the RID and regenerate the lock files

### 6. Deployment Configuration
- ✅ Dockerfiles that pin `--platform=linux/amd64` or publish with `-r linux-x64`, and Windows container images (Phase 2.4)
- ✅ Lambda functions where the project ships the template or `aws-lambda-tools-defaults.json` (architecture `arm64`, and a supported runtime when the current one blocks updates)
- ✅ Kubernetes node selection only when the project already ships manifests, and only the node-selection, registry and ingress lines
- ✅ Deployment and install scripts that gate on `uname -m` or download x86_64 assets
- ✅ AWS SDK for .NET versions without IMDSv2 support, when a target requires IMDSv2 (AWSSDK.Core before 3.3.103.66; Amazon Linux 2023 AMIs require IMDSv2 by default)

### 7. The Move to Linux (Windows and .NET Framework Starting Points)
- ✅ Porting a .NET Framework project to modern .NET, and a Windows-targeting modern .NET project to Linux: one MUST UPGRADE decision for the whole solution, applied after one approval
- ✅ Replacing Windows-only APIs with what modern .NET supports on Linux ([windows-to-linux.md](windows-to-linux.md)); each replacement that changes behavior or data (secrets, imaging, authentication, serialized data) is a user decision
- ✅ Windows Forms, WPF and ASP.NET Web Forms have no Linux path: **BLOCKER**, documented with options, never ported to another Windows-only target

## ❌ OUT OF SCOPE: What NOT to Fix

### 1. General Dependency Modernization
- ❌ "This version is old" → NOT an ARM64 issue
- ❌ "We should use latest" → NOT an ARM64 issue
- ❌ "Deprecated library" → NOT an ARM64 issue
- ❌ Example: Newtonsoft.Json 12.0.3 → 13.x (managed, works on ARM64)

### 2. Security Updates
- ❌ CVE fixes or vulnerability patches, including the NuGet audit warnings NU1901 to NU1904
- ❌ Example: Newtonsoft.Json 12.0.3, reported as `NU1903` (GHSA-5crp-9r3c-p9vr): mention once, change nothing

### 3. Feature Upgrades
- ❌ Newer features or better performance
- ❌ API modernization
- ❌ Example: minimal APIs, Entity Framework Core major versions, `System.Text.Json` instead of Newtonsoft.Json (features, not ARM64)

### 4. .NET Version Changes
- ❌ .NET 8 → 10 or any target framework change that ARM64 does not require
- ❌ Changing the SDK in `global.json`
- ❌ Exception: the changes listed in §7 above and in phase1-static-analysis.md §1.5 (a .NET Framework or `-windows` target, a runtime that cannot run on arm64 as it is, a package version that works on arm64 only on a newer framework), each decided once for the solution
- ❌ Exception: session-scoped SDK switching for build tooling (Phase 3.0)

### 5. Code Refactoring
- ❌ Code quality improvements
- ❌ Design pattern changes
- ❌ Performance optimizations (except recording Graviton-specific recommendations in `05-runtime-configuration.md`)

### 6. Tooling and Platform Changes
- ❌ Moving to or from central package management, lock files or Paket ([package-management-mapping.md](package-management-mapping.md))
- ❌ Base image distribution or version changes (Debian to Alpine, `aspnet:8.0` to `aspnet:10.0`): they change the C library and its version at once. The exception is a target whose glibc is too old for a required native, which the skill documents as a user decision
- ❌ Web server, hosting model or logging framework changes beyond what Linux requires (keeping `UseIIS()` is harmless on Linux; removing it is out of scope)
- ❌ `.gitignore`, `.dockerignore` or CI pipeline edits: phrased as a recommendation only (SKILL.md "User Responsibility")

## 🔍 Decision Tree: Should I Update This Dependency?

```
For each dependency, ask in order:

1. Does it have native files for the source or target RID?
   NO → Mark COMPATIBLE, do NOT update
   YES → Continue to #2

2. Does the target RID get an aarch64 build for the target's libc and glibc?
   YES → Mark COMPATIBLE, do NOT update
   NO → Continue to #3

3. Will build or publish FAIL on ARM64 without update?
   NO → Continue to #4
   YES → MUST UPGRADE (document evidence)

4. Will runtime FAIL on ARM64 without update?
   NO → Mark COMPATIBLE, do NOT update
   YES → MUST UPGRADE (document evidence)
```

A missing native file almost always fails at run time, not at build time, so step 4 is where most findings land.

**Simple Rule:** If it builds and runs on ARM64 today → **DO NOT UPDATE**

## 📈 Recommendations: Validation Ladder

A recommendation (a RECOMMENDED UPGRADE or a runtime setting) may be recorded only with its evidence level. Nothing below level A is recommended by default.

| Level | Evidence | Handling |
|---|---|---|
| **A** | Documented in this repository with a mechanism (file and section cited) | Record in `05-runtime-configuration.md` as a recommendation with the citation |
| **B** | Upstream release note, changelog or published benchmark that names Arm64 or Graviton | Record with the link, labelled "upstream-claimed, measure before adopting" |
| **C** | No written source | Omit. If the user asks, say it is unverified |

A-level sources available in this repository: the .NET version guidance (.NET 10 LTS for new Graviton workloads, .NET 8 or 9 when an earlier supported release is needed) in [dotnet.md](https://github.com/aws/aws-graviton-getting-started/blob/main/dotnet.md#recommended-versions) and the README's [software updates table](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md#recent-software-updates-relevant-to-graviton).

## 📋 Common Managed .NET Libraries (Always ARM64-Compatible)

These packages had **no native files** in their latest stable release at the time of writing (checked by content with `probe`). Managed code runs on any architecture, but a resolved tree still goes through the per-RID check, because any version can add a native dependency:

**Testing Frameworks:**
- xunit 2.9.3
- NUnit 5.0.0
- MSTest.TestFramework 4.4.1
- Moq 4.21.0
- FluentAssertions 8.11.0

**Logging:**
- Serilog 4.4.0
- NLog 6.2.1

**Utilities:**
- AutoMapper 16.2.0
- Polly 8.8.0
- MediatR 14.2.0
- FluentValidation 12.1.1
- Swashbuckle.AspNetCore 10.2.3

**Serialization:**
- Newtonsoft.Json 13.0.4
- Google.Protobuf 3.36.2

**Data and Clients:**
- Dapper 2.1.89
- Microsoft.EntityFrameworkCore 8.0.31 and 10.0.12
- Npgsql 10.0.3
- MySqlConnector 2.6.2
- StackExchange.Redis 3.3.1
- MongoDB.Driver 3.12.0
- Microsoft.Data.SqlClient 7.1.1 (its native files are Windows-only; on Linux it is managed)
- Grpc.Net.Client 2.84.0
- AWSSDK.S3 4.0.104.1, AWSSDK.DynamoDBv2 4.0.107, Amazon.Lambda.Core 3.3.0, Amazon.Lambda.AspNetCoreServer.Hosting 2.2.1
- SixLabors.ImageSharp 4.1.2

**Traps (look managed, are not, or fail on Linux):**
- **System.Drawing.Common:** managed only by content (10.0.12), but Windows-only since .NET 6: `PlatformNotSupportedException: System.Drawing.Common is not supported on non-Windows platforms` ([windows-to-linux.md](windows-to-linux.md))
- **Microsoft.Data.Sqlite:** brings SQLitePCLRaw.lib.e_sqlite3, whose 2.1.12 arm64 build needs GLIBC_2.34
- **Grpc.Core** (native; linux-arm64 from 2.37.0) is not **Grpc.Net.Client** (managed); **Grpc.AspNetCore** brings Grpc.Tools, a build-time executable (2.84.0 has aarch64)
- **Confluent.Kafka:** brings librdkafka.redist (linux-arm64 from 1.6.0). Version 2.15.1 ships a glibc and a musl build in the same `runtimes/linux-arm64/native/` folder and picks one at run time; the check prints a NOTE for the other one
- **Microsoft.Playwright** and **Selenium.WebDriver:** carry executables (Playwright's `node`, Selenium Manager); Selenium.WebDriver.ChromeDriver's Linux driver is x86-64 in every release
- **AWS SDK for .NET:** managed, but AWSSDK.Core before 3.3.103.66 has no IMDSv2 support

Do not extend the list from memory. A package is managed only when the per-RID check or `probe` counts it under `managed only` ([nuget-native-assets.md §3](nuget-native-assets.md#3-the-per-rid-check)).

## 🚫 Red Flags: When Agent is Going Off-Scope

**Stop immediately if you see:**
- ❌ "This version is from [old year], should update"
- ❌ "Security vulnerability CVE-XXXX-YYYY" or "NU1903"
- ❌ "Best practice to use latest version"
- ❌ "Deprecated API, should modernize"
- ❌ "Better performance in newer version"
- ❌ "More features in latest release"
- ❌ "Move to .NET 10 while we are here"
- ❌ "The publish succeeded, so it works on ARM64"

**Correct responses:**
- ✅ "Version X gives linux-arm64 no native file (per-RID check)"
- ✅ "DllNotFoundException on ARM64 with version X"
- ✅ "The native file selected for linux-arm64 is an x86-64 ELF file"
- ✅ "Documented ARM64 crash in issue #XXXX"

## ✅ How to Document Scope Compliance

### For Updates Made:
```markdown
## ARM64-Required Dependency Updates

| Dependency | Old → New | ARM64 Issue | Evidence |
|------------|-----------|-------------|----------|
| SkiaSharp.NativeAssets.Linux (and SkiaSharp, same version) | 1.68.3 → 2.80.0 | no linux-arm64 native file | `FINDING no linux-arm64 native: SkiaSharp.NativeAssets.Linux/1.68.3 (linux-x64 has 1; runtimes/ folders: linux-x64)`; probe of 2.80.0: `OK linux-arm64 ... libSkiaSharp.so (glibc GLIBC_2.17 align 0x10000)` |
| Microsoft.ML.OnnxRuntime | 1.10.0 → 1.11.0 | aarch64 build in `runtimes/linux-aarch64/`, never selected | per-RID check: no linux-arm64 native; 1.11.0 is the first with `runtimes/linux-arm64` |
```

### For Updates NOT Made:
```markdown
## Dependencies Validated as ARM64-Compatible (No Updates)

| Dependency | Version | Status | Notes |
|------------|---------|--------|-------|
| Newtonsoft.Json | 12.0.3 | ✅ Compatible | Managed, works on ARM64. NU1903 is a security finding: out of scope. |
| Dapper | 2.0.123 | ✅ Compatible | Managed, no native files. |
| SQLitePCLRaw.lib.e_sqlite3 | 2.1.12 | ✅ Compatible | linux-arm64 build present; needs GLIBC_2.34 (fine on Amazon Linux 2023 and Debian 12). |
```

## 🎓 Learning from Past Mistakes

### Case Study: Newtonsoft.Json 12.0.3

**Initial Analysis (WRONG):**
> "Newtonsoft.Json 12.0.3 is old and restore reports NU1903 (high severity vulnerability). Mark as MUST UPGRADE."

**Why This Was Wrong:**
- It is managed only (no native files)
- It builds, and its code ran on ARM64 in the test solution's arm64 self-check
- NU1903 is a security finding, and age is not an ARM64 issue

**Correct Analysis:**
> "Newtonsoft.Json 12.0.3: managed, no native files, runs on ARM64. Status: COMPATIBLE. No update required for ARM64. Note for user: restore reports NU1903 (GHSA-5crp-9r3c-p9vr); handle it in a separate security update."

### Case Study: SkiaSharp.NativeAssets.Linux 1.68.3 (right verdict, wrong target version)

**Analysis (PARTLY WRONG):**
> "SkiaSharp.NativeAssets.Linux 1.68.3 has no linux-arm64 native file. MUST UPGRADE to the latest release, 4.153.1."

**What Was Right:**
- 1.68.3 ships `runtimes/linux-x64` only, so linux-arm64 gets nothing and the app fails with `DllNotFoundException: Unable to load shared library 'libSkiaSharp'`
- Verdict MUST UPGRADE is correct, and the reasoning cites the missing file

**What Was Wrong: the target version**
- `runtimes/linux-arm64` first appears in **2.80.0**. The latest release drags several major versions of unrelated change into an ARM64 migration
- Newer is not safer for the target: the 3.119.0 Linux builds need GLIBC_2.27, so they do not load on Amazon Linux 2 (glibc 2.26), while 2.80.0 needs GLIBC_2.17
- SkiaSharp.NativeAssets.Linux 2.80.0 depends on SkiaSharp 2.80.0 (its nuspec; 3.119.0 and 4.153.1 list no dependency), so the minimal change moves both packages to 2.80.0, and nothing else
- The minimal version is not always the one to apply without asking: NuGet audit flags SkiaSharp 2.80.0 to 2.88.5 (NU1903, GHSA-j7hp-h8jx-5ppr) but not 1.68.3, so the arm64 floor brings a new advisory. 2.88.6 is the lowest release without it, and also probes clean for linux-arm64. That choice goes to the user once; it is not a reason to jump to the latest release

**Correct Analysis:**
> "SkiaSharp.NativeAssets.Linux 1.68.3: no linux-arm64 native file. Status: MUST UPGRADE. Minimum ARM64 version: **2.80.0** (with SkiaSharp 2.80.0), the lowest that probes clean, needing GLIBC_2.17. Restore flags 2.80.0 with NU1903, which 1.68.3 did not have; 2.88.6 is the lowest release without it (user decision: 2.80.0 or 2.88.6). For an Alpine target the floor is 3.119.0, the first with linux-musl-arm64: a decision tied to the target OS."

**The transferable lesson:** a content-based verdict can still carry a wrong *minimum version*. Probe upward from the version in use and stop at the first that reports no findings ([nuget-native-assets.md §5](nuget-native-assets.md#5-finding-the-lowest-version-that-works)).

### Case Study: Microsoft.ML.OnnxRuntime 1.10.0 (verify the selection, not the name)

**Initial Analysis (WRONG):**
> "The 1.10.0 package contains a folder named `linux-aarch64` with an aarch64 ELF file: COMPATIBLE."

**Why This Was Wrong:**
- `linux-aarch64` is not a RID, so NuGet never selects files from it; linux-arm64 gets no native file at all
- On arm64 the application failed with `DllNotFoundException: Unable to load shared library 'onnxruntime'`
- A search of the package for "aarch64" or "arm64" found the file and gave the opposite verdict

**Correct Analysis:**
> "Microsoft.ML.OnnxRuntime 1.10.0: per-RID check `FINDING no linux-arm64 native` (runtimes/ folders include linux-aarch64, which NuGet does not select). Status: MUST UPGRADE. Minimum: 1.11.0, the first with `runtimes/linux-arm64`. No release has linux-musl-arm64, so an Alpine target is not an option for this component."

**Lesson:** ask what restore selects for the target RID, then judge that file by its ELF header. Neither a version number nor a folder name decides.

### Case Study: SQLitePCLRaw.lib.e_sqlite3 2.0.0 (old is not missing)

**Initial Analysis (WRONG):**
> "SQLitePCLRaw.lib.e_sqlite3 2.0.0 is several years old and native: MUST UPGRADE."

**Why This Was Wrong:**
- 2.0.0 already ships `runtimes/linux-arm64/native/libe_sqlite3.so`, an aarch64 build needing GLIBC_2.17
- Its floors are not even monotonic: 2.0.5 needs GLIBC_2.28 and 2.0.6 needs GLIBC_2.17 again, and 2.1.12 needs GLIBC_2.34

**Correct Analysis:**
> "SQLitePCLRaw.lib.e_sqlite3 2.0.0: linux-arm64 native present (aarch64, GLIBC_2.17). Status: COMPATIBLE for glibc targets. For Alpine, linux-musl-arm64 starts at 2.1.0."

### Case Study: The False PASS (exit codes and emulation)

**Initial Analysis (WRONG):**
> "`dotnet publish -r linux-arm64` exited 0, and the self-check passed in an arm64 container on the x86 build host: COMPATIBLE."

**Why This Was Wrong:**
- The publish exited 0 with SkiaSharp, ONNX Runtime and SQLite.Interop missing for arm64
- A Windows Forms tool published for linux-arm64 also exited 0, with a runtimeconfig that needs `Microsoft.WindowsDesktop.App`
- In the arm64 container, Selenium Manager 4.48.0, an x86-64 executable, ran anyway: on an x86 host the CPU executes x86-64 files directly, so an emulated run cannot catch an x86-64 executable

**Correct Analysis:**
> "Verdicts come from the per-RID check and the output scan, by content. Emulated runs are smoke tests; executables and anything that loads natives are confirmed by content and on Graviton."

## 🎯 Success Criteria

**Transformation is successful when:**
1. ✅ Application builds and publishes for linux-arm64 without errors
2. ✅ Application runs on ARM64 without crashes
3. ✅ All tests pass on ARM64
4. ✅ Only ARM64-specific issues were addressed
5. ✅ No scope creep into general modernization

**Transformation has scope creep if:**
1. ❌ Updated dependencies that already worked on ARM64
2. ❌ Fixed security issues unrelated to ARM64
3. ❌ Modernized code for "best practices"
4. ❌ Changed the target framework or SDK unnecessarily
5. ❌ Refactored working code

## 📞 When in Doubt

**Ask yourself:**
- "If I don't make this change, will the ARM64 build, publish or runtime fail?"
- "Is there concrete evidence this current version breaks on ARM64?"
- "Am I updating this because it's old, or because ARM64 requires it?"

**If unsure:** Mark as COMPATIBLE and document reasoning. It's better to under-fix than to introduce unnecessary scope creep.

---

**Remember:** This is an ARM64 compatibility validation, not a general dependency modernization project. Stay focused on ARM64-specific issues only.
