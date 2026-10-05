# Phase 1: Static Compatibility Analysis

Analyze the project without making changes. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below picks target runtime identifiers (RIDs), use `dotnet.target_rids` from `skill-config.md` (if defined) in place of the default `linux-arm64`, and use `dotnet.framework_bump` in §1.5. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Phase 1 runs on any host, including x86: every check below reads files, evaluates project files, or restores scratch copies. Nothing from the project is built for the target or run until Phase 3. The commands were executed in bash 5.2 and zsh 5.9 on Linux. They need the .NET SDK, Python 3.6 or later, and the check program, written once per session with the block in [nuget-native-assets.md §11](../document_references/nuget-native-assets.md#11-the-check-program):

```bash
dotnet --list-sdks
dotnet --version   # the SDK this repository selects (global.json in this folder or a parent)
python3 -c 'import sys; assert sys.version_info >= (3, 6), sys.version; print("python3", sys.version.split()[0])'
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
[ -f "$GV_CHECK" ] || echo "ERROR: write the check program first (document_references/nuget-native-assets.md, section 11)"
```

> **If `dotnet --version` fails** with `A compatible .NET SDK was not found.`, the repository's `global.json` pins an SDK that is not installed. Apply the session-scoped SDK switch from [phase3-validation.md](phase3-validation.md) §3.0 now: the first `dotnet` command needs it, not only Phase 3.

"Executed on" lines below refer to three test solutions:
- the **Linux solution**: nine projects on .NET 8 for Linux x64, with central package versions and lock files;
- the **Windows solution**: a Windows service, an IIS-hosted API and a Windows Forms tool on .NET 8;
- the **.NET Framework solution**: a .NET Framework 4.8 web application and a .NET Standard library.

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`**, **`graviton-validation/raw/project-properties.txt`**, **`graviton-validation/raw/dependency-tree.json`** and **`graviton-validation/raw/native-assets.txt`**

### Determine Deployment Type

- Dockerfile or container config present: **Containerized**
- systemd/init scripts, or a published app started directly (`dotnet <app>.dll` or its apphost): **Host-based**
- Some applications support both
- AWS Lambda (`aws-lambda-tools-defaults.json`, a SAM or CloudFormation function with a `dotnet` runtime, or a Lambda container image): **Lambda**. The architecture is a function setting (§1.5).
- IIS (`web.config`, `AspNetCoreHostingModel`, `UseIIS`) or a Windows service (`AddWindowsService`, `UseWindowsService`, `ServiceBase`, installation scripts): **Windows host**. The application must move to Linux first ([Determine Starting Point](#determine-starting-point)).

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# Deployment files (read every hit)
find . \( -name .git -o -name bin -o -name obj -o -name node_modules -o -name graviton-validation \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.dockerfile' \
  -o -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' -o -name 'aws-lambda-tools-defaults.json' -o -name 'serverless.template' \
  -o -name 'template.y*ml' -o -name '[Ww]eb.config' -o -name '*.service' -o -name '*.ps1' -o -name '*.sh' \) -print | sort
# Hosting markers: Kubernetes, Lambda, IIS, Windows services
grep -rnE "${EX[@]}" --include='*.y*ml' --include='*.json' --include='*.template' --include='*.cs' --include='*.vb' --include='*.fs' \
  --include='*.csproj' --include='*.vbproj' --include='*.fsproj' --include='*.config' \
  'kubernetes\.io/arch|AWS::(Serverless|Lambda)::Function|"function-runtime"|AddWindowsService|UseWindowsService|ServiceBase|UseIIS|AspNetCoreHostingModel' . 2>/dev/null || true
```

Executed on the three solutions:
- **Linux solution:** its Dockerfile, `deploy/deploy.sh`, the Lambda files (`aws-lambda-tools-defaults.json` with `"function-runtime": "dotnetcore3.1"`, `template.yaml` with `AWS::Serverless::Function`) and `kubernetes.io/arch: amd64` in `deploy/k8s/deployment.yaml`.
- **Windows solution:** a Dockerfile, `deploy/install-service.ps1`, `web.config`, `AddWindowsService`, `UseIIS()` and `<AspNetCoreHostingModel>InProcess</AspNetCoreHostingModel>`.
- **.NET Framework solution:** `Web.config`, a `ServiceBase` class and `<UseIISExpress>true</UseIISExpress>`.

### Detect Multi-Module Structure

- Solutions: `.sln`, `.slnx` (written by `dotnet new sln` in SDK 10) and `.slnf` list projects
- `Directory.Build.props`, `Directory.Build.targets` and `Directory.Packages.props` (central package versions) apply to every project below their folder
- If multi-project: enumerate all project files (`.csproj`, `.fsproj`, `.vbproj`), analyze each independently, including projects no solution lists
- Native libraries may come from any project; do NOT limit the analysis to the startup project

```bash
# Solutions, projects and the files that shape every project's build
find . \( -name .git -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name '*.sln' -o -name '*.slnx' -o -name '*.slnf' \
  -o -name '*.csproj' -o -name '*.fsproj' -o -name '*.vbproj' -o -name 'Directory.Build.props' -o -name 'Directory.Build.targets' \
  -o -name 'Directory.Packages.props' -o -name 'global.json' -o -iname 'nuget.config' -o -name 'packages.config' -o -name 'packages.lock.json' \
  -o -name 'dotnet-tools.json' \) -print | sort
# Projects each solution lists; a project found above but listed by no solution is analyzed too
find . -maxdepth 1 -type f \( -name '*.sln' -o -name '*.slnx' \) | while IFS= read -r s; do echo "== $s"; dotnet sln "$s" list < /dev/null; done
```

Executed:
- **Linux solution:** `Fixture.sln` with 9 projects, `Directory.Build.props`, `Directory.Packages.props`, `global.json` and 9 `packages.lock.json` files.
- **Windows solution:** `Orders.slnx` with 3 projects. SDK 10.0.401 listed them; SDK 8.0.425 failed with ``Invalid solution `Orders.slnx`. Expected file header not found.``
- **.NET Framework solution:** two project files and a `packages.config`, with no solution file at the root.

### Determine Starting Point

Graviton instances and arm64 Lambda functions run Linux, so the first question is how far the code is from modern .NET on Linux. Read it from the evaluated properties of every project (`Directory.Build.props` and other imports applied). `-getProperty` evaluates the project without building it; it needs MSBuild 17.8 or later ([Microsoft Learn](https://learn.microsoft.com/en-us/visualstudio/msbuild/evaluate-items-and-properties)), and was run with SDK 8.0.425 and 10.0.401:

```bash
mkdir -p graviton-validation/raw
# Evaluated properties of every project file, one line each
P=TargetFramework,TargetFrameworks,TargetFrameworkVersion,OutputType,RuntimeIdentifier,RuntimeIdentifiers,PlatformTarget,Prefer32Bit,UseWindowsForms,UseWPF,SelfContained,PublishAot,PublishReadyToRun,PublishSingleFile,InvariantGlobalization,AspNetCoreHostingModel,UsingMicrosoftNETSdk
find . \( -name .git -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name '*.csproj' -o -name '*.fsproj' -o -name '*.vbproj' \) -print | sort |
  while IFS= read -r p; do
    printf '%s: ' "$p"
    dotnet msbuild "$p" -getProperty:"$P" < /dev/null 2>&1 | python3 -c 'import json, sys
t = sys.stdin.read()
try:
    print(", ".join("%s=%s" % kv for kv in sorted(json.loads(t)["Properties"].items()) if kv[1]))
except ValueError:
    print("EVALUATION FAILED: " + " ".join(t.split())[:300])'
  done | tee graviton-validation/raw/project-properties.txt
```

| Starting point | What the properties show | Path |
|---|---|---|
| .NET Framework | no `UsingMicrosoftNETSdk`, `TargetFrameworkVersion=v4.x`, a `packages.config`; or `TargetFramework` `net4x` | **MUST UPGRADE:** port to modern .NET on Linux, one approval for the whole solution ([windows-to-linux.md](../document_references/windows-to-linux.md)) |
| Modern .NET on Windows | `TargetFramework` ending in `-windows`, `UseWindowsForms=true` or `UseWPF=true`, `RuntimeIdentifier=win-*`, plus the Windows hosting markers above | **MUST UPGRADE:** move to Linux, one approval for the whole solution. Windows Forms and WPF projects have no Linux path: **BLOCKER**, user decision |
| Modern .NET on Linux | `TargetFramework` `netcoreapp*` or `net5.0` and later, Linux RIDs | the arm64 checks in this skill apply directly |
| .NET Standard library | `TargetFramework` `netstandard*` | portable; the same checks apply |

Executed (lines shortened):
- **Linux solution:**
  - `./src/Fixture.Lambda/Fixture.Lambda.csproj: ..., TargetFramework=netcoreapp3.1, ...`
  - `./src/Fixture.Api/Fixture.Api.csproj: AspNetCoreHostingModel=inprocess, OutputType=Exe, PlatformTarget=x64, ..., RuntimeIdentifier=linux-x64, RuntimeIdentifiers=linux-x64, ...`
  - `./src/Fixture.Agent/Fixture.Agent.csproj: InvariantGlobalization=true, OutputType=Exe, ..., PublishAot=true, ...`
- **Windows solution:**
  - `./src/Orders.AdminTool/Orders.AdminTool.csproj: OutputType=WinExe, ..., TargetFramework=net8.0-windows, ..., UseWindowsForms=true, ...`
  - `./src/Orders.Service/Orders.Service.csproj: ..., PlatformTarget=x64, ..., RuntimeIdentifier=win-x64, ...`
- **.NET Framework solution:**
  - `./Orders.Web/Orders.Web.csproj: OutputType=Library, PlatformTarget=x64, Prefer32Bit=false, TargetFrameworkVersion=v4.8`, with no `UsingMicrosoftNETSdk`, so it is not an SDK-style project;
  - `./Orders.Contracts/Orders.Contracts.csproj: ..., TargetFramework=netstandard2.0, ..., UsingMicrosoftNETSdk=true`.

Never decide the starting point from a successful build or publish. With `EnableWindowsTargeting=true`, `dotnet publish -r linux-arm64` of the Windows Forms tool exited 0 and produced an aarch64 apphost, but its `.runtimeconfig.json` requires `Microsoft.WindowsDesktop.App`, which exists only on Windows. Phase 3's output scan reports that file; the properties above report it first.

### Determine Target OS and libc

Native files depend on the OS the workload runs on as well as the CPU: glibc or musl, the glibc version, and the kernel's page size ([nuget-native-assets.md §6](../document_references/nuget-native-assets.md#6-target-os-libc-glibc-version-page-size)). Find every target:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# The image each Dockerfile's last stage runs on
find . \( -name .git -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.dockerfile' \) -print |
  while IFS= read -r f; do echo "$f: $(grep -iE '^[[:space:]]*FROM[[:space:]]' "$f" | tail -n 1)"; done
# Lambda runtimes and architectures
grep -rnE "${EX[@]}" --include='*.y*ml' --include='*.json' --include='*.template' \
  'Runtime:[[:space:]]*(dotnet|provided)|"function-runtime"|Architectures:|"function-architecture"|- (x86_64|arm64)$' . 2>/dev/null || true
```

Then, for each target:
- **Container images:** read the image's libc with the block in [nuget-native-assets.md §6](../document_references/nuget-native-assets.md#6-target-os-libc-glibc-version-page-size), which also lists the results for the common .NET and Lambda images.
- **Lambda managed runtimes:** `dotnet8` and `dotnet10` run on Amazon Linux 2023 (glibc 2.34); `dotnet6` and `dotnetcore3.1` ran on Amazon Linux 2 (glibc 2.26) ([Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)).
- **EC2 hosts:** ask for the AMI if no file names it. Amazon Linux 2023 AMIs launch in IMDSv2-only mode by default ([Deprecated in AL2023](https://docs.aws.amazon.com/linux/al2023/ug/deprecated-al2023.html)); §1.3 uses this for the AWS SDK.

Record three values for the rest of the skill:
- the **target RIDs**: `linux-arm64`, plus `linux-musl-arm64` when any target image is Alpine;
- the **lowest glibc version** across the targets;
- the **page size** when a target kernel uses 64KB pages (AlmaLinux 8 and Rocky Linux 8 aarch64).

Executed:
- **Linux solution:**
  - `./Dockerfile: FROM mcr.microsoft.com/dotnet/aspnet:8.0` (Debian 12, glibc 2.36).
  - The Lambda function: `Runtime: dotnetcore3.1` with `Architectures: - x86_64`, and the same in `aws-lambda-tools-defaults.json`. Its arm64 target is `dotnet8` or `dotnet10` (§1.5), so the lowest glibc is 2.34.
  - `deploy/deploy.sh` installs the agent on an EC2 host whose AMI no file names: ask.
- **Windows solution:** `FROM mcr.microsoft.com/dotnet/aspnet:8.0-nanoserver-ltsc2022`, a Windows image; the Linux image is part of the move to Linux.
- **.NET Framework solution:** no deployment file names a target: ask.

### Generate Dependency Tree

> **If this restore fails** for the SDK reason above, or because the project needs an SDK feature the selected SDK lacks, apply the session-scoped SDK switch from [phase3-validation.md](phase3-validation.md) §3.0 now.

One scratch restore gives both the dependency tree (every resolved package with the shortest reference chain from a project, as JSON) and the per-RID native report used in §1.2 and §1.3. The repository is not modified ([nuget-native-assets.md §3](../document_references/nuget-native-assets.md#3-the-per-rid-check)):

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
# --source-rid: linux-x64 for a Linux starting point, win-x64 for Windows. --glibc: the target's version (Determine Target OS and libc).
python3 "$GV_CHECK" assets --source-rid linux-x64 --target-rid linux-arm64 --glibc 2.34 \
  --tree graviton-validation/raw/dependency-tree.json > graviton-validation/raw/native-assets.txt; rc=$?
cat graviton-validation/raw/native-assets.txt; echo "exit status $rc (0 no findings, 1 findings, 2 restore failed)"
# Sanity check: nothing resolved is a failed restore, not an all-clear (unless the solution references no packages)
grep -q '^packages: [1-9]' graviton-validation/raw/native-assets.txt || echo "WARNING: no packages resolved; read the restore errors above"
```

Executed:
- **Linux solution:** 3 seconds; `dependency tree: 9 projects written to .../graviton-validation/raw/dependency-tree.json`, then `packages: 40; ...; findings: 4; checks: 1` and exit status 1. Each tree entry names the chain, for example `"SQLitePCLRaw.lib.e_sqlite3 2.1.12": {"type": "package", "via": ["Fixture.Core", "Microsoft.Data.Sqlite 8.0.31", "SQLitePCLRaw.bundle_e_sqlite3 2.1.12"]}` for the tool project.
- **Windows solution** (with `--source-rid win-x64`): 33 packages, all managed, no findings. Its blockers are in the code (§1.4), not in its packages.
- **.NET Framework solution:** `CHECK Orders.Web/packages.config: these packages are not restored by PackageReference and are not in this report; run: config Orders.Web/packages.config`. A `packages.config` project gets the per-package check instead: [nuget-native-assets.md §3](../document_references/nuget-native-assets.md#projects-that-still-use-packagesconfig) (5 entries, 1 finding: System.Data.SQLite.Core 1.0.118.0).

### Categorize Components by Risk

- **CRITICAL**: Native code (NuGet native assets, P/Invoke, committed `.so` files), x86 hardware intrinsics, Windows Forms and WPF, .NET Framework technology with no modern .NET equivalent (Web Forms)
- **HIGH**: Packages with known x64-only versions, Windows-only APIs, runtimes that cannot move to arm64 as they are (Lambda `dotnetcore3.1`), crypto and graphics libraries with native parts
- **MEDIUM**: Build configs (RIDs, `PlatformTarget`, lock files), Dockerfiles, deployment scripts, CI files, architecture detection code
- **LOW**: Managed code built as AnyCPU, without architecture or OS dependencies

## 1.2 Native Library Validation (.so File Analysis)

> **Output: `graviton-validation/02-native-library-report.md`**, **`graviton-validation/raw/native-assets.txt`** (from §1.1) and **`graviton-validation/raw/repo-native-scan.txt`**

Native code reaches a .NET application in four ways ([nuget-native-assets.md §1](../document_references/nuget-native-assets.md#1-managed-code-native-code-and-what-decides-each)):
- files under `runtimes/<rid>/native/` in NuGet packages;
- files that packages keep elsewhere and copy to the output or run;
- files committed to the repository;
- downloads at run time.

The per-RID report from §1.1 covers the first two. This section reads it, scans the repository, and finds what arrives at run time. All of them depend on the target OS as well as the CPU (§1.1, Determine Target OS and libc).

### 1.2.1 Statically Bundled .so Scanning

Statically bundled native code sits in two places. Judge both by content, never by name: a Linux library can be named `SQLite.Interop.dll`, and an executable has no extension.

1. **NuGet packages.** Read `graviton-validation/raw/native-assets.txt` from §1.1. Each package with native files for the source or target RIDs gets one line per target RID and file:
   - `OK`: an aarch64 build for the target's libc, with the GLIBC_ version it needs and its LOAD alignment;
   - `FINDING`: no file for the target RID, or a file that is x86-64, built for the other libc, too new for the target's glibc, or a Windows or macOS binary;
   - `CHECK`: x86-only files outside `runtimes/`, which fail only if a build target copies them or a tool runs them;
   - an indented `via` line under each `FINDING` and `CHECK`, with the reference chain from a project.

   What each line means, and the package shapes behind them: [nuget-native-assets.md §3 and §4](../document_references/nuget-native-assets.md#3-the-per-rid-check).
2. **Files committed to the repository**: vendored libraries, prebuilt helpers, and managed assemblies built for one architecture. Scan the source tree by content. `--source-tree` skips `.git`, `.vs`, `bin`, `obj`, `node_modules` and `graviton-validation`; build and publish outputs are scanned in Phase 3.1:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" scan --source-tree . > graviton-validation/raw/repo-native-scan.txt; rc=$?
cat graviton-validation/raw/repo-native-scan.txt; echo "exit status $rc (0 no findings, 1 findings, 2 not a folder)"
```

Executed on the Linux solution:

```
ELF x86-64   glibc GLIBC_2.2.5 align 0x1000           src/Fixture.Core/native/x64/libfastsum.so
FINDING src/Fixture.Core/native/x64/libfastsum.so is x86-64
files by kind: ELF x86-64 1
findings: 1
exit status 1 (0 no findings, 1 findings, 2 not a folder)
```

The Windows and .NET Framework solutions commit no native files (`files by kind: none`). The same scan reports committed managed assemblies built for x64 or x86, which fail on arm64 as described in [nuget-native-assets.md §1](../document_references/nuget-native-assets.md#1-managed-code-native-code-and-what-decides-each).

### 1.2.2 Runtime-Extracted Native Library Detection

Some code loads or downloads native code at run time instead of shipping it in a package, and some images install it from the OS:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# Native loads with file:line (C#, VB, F#)
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' \
  '[[<](DllImport|LibraryImport)\(|Declare (Auto |Ansi |Unicode )?(Function|Sub) .* Lib "|NativeLibrary\.(Load|TryLoad|SetDllImportResolver)|LoadUnmanagedDll|GetDelegateForFunctionPointer' . 2>/dev/null || true
# Binary downloads with an architecture in the URL or file name (scripts, Dockerfiles, CI)
grep -rnE "${EX[@]}" --include='*.sh' --include='*.ps1' --include='*.cmd' --include='Dockerfile*' --include='*.y*ml' \
  '(curl|wget|Invoke-WebRequest|iwr|Start-BitsTransfer)[^#]*(x86_64|amd64|x64|linux64|win64)' . 2>/dev/null || true
# Packages that run or download executables (a prompt, not an allowlist; the content check decides)
grep -rnE "${EX[@]}" --include='*.csproj' --include='*.fsproj' --include='*.vbproj' --include='*.props' --include='*.targets' --include='packages.config' \
  'Selenium\.WebDriver|Microsoft\.Playwright|ChromeDriver|GeckoDriver' . 2>/dev/null || true
# OS packages that images and scripts install (each must exist for arm64 on the target OS)
grep -rnE "${EX[@]}" --include='Dockerfile*' --include='*.sh' '(apt-get|apt|dnf|yum|microdnf|apk|zypper)[[:space:]].*(install|add)[[:space:]]' . 2>/dev/null || true
```

Executed:
- **Linux solution:**
  - `./src/Fixture.Core/Native.cs:11:` `NativeLibrary.SetDllImportResolver(...)`, `Native.cs:26:` `NativeLibrary.Load(Path.Combine(AppContext.BaseDirectory, "native", arch, "libfastsum.so"))` and `Native.cs:29:` `[DllImport("fastsum", EntryPoint = "fast_sum")]`;
  - `./deploy/deploy.sh:10:` the `awscli-exe-linux-x86_64.zip` download;
  - Selenium.WebDriver in the UI test project, with version 4.48.0 in `Directory.Packages.props`;
  - `apt-get install -y --no-install-recommends libfontconfig1` in the Dockerfile.
- **Windows solution:** `./src/Orders.Service/Platform.cs:20:` `[DllImport("kernel32.dll")]`. Windows system DLLs never exist on Linux: the call failed there with `DllNotFoundException: Unable to load shared library 'kernel32.dll' or one of its dependencies`.

Check that every OS package exists for arm64 on the target OS, from a container that runs natively on this host. On an x86 host, asking the arm64 image itself runs under emulation; that took 17 seconds for Debian and did not finish in 480 seconds for Amazon Linux 2023.

```bash
# Debian or Ubuntu target: ask its package index for the arm64 builds, from a container that runs natively on this host
IMG=mcr.microsoft.com/dotnet/aspnet:8.0   # the runtime image (Determine Target OS and libc)
PKGS="libfontconfig1"                     # the packages its Dockerfile installs
command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
ARM_PKGS=$(echo "$PKGS" | sed 's/[^ ][^ ]*/&:arm64/g')
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "dpkg --add-architecture arm64 && apt-get update -qq && apt-get install -s --no-install-recommends $ARM_PKGS 2>&1 | grep -E '^(Inst|E:)'"
```

```bash
# Amazon Linux 2023 (dnf) target: ask the aarch64 repositories, from a container that runs natively on this host
IMG=public.ecr.aws/amazonlinux/amazonlinux:2023
PKGS="fontconfig libicu"
command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "dnf -q --forcearch aarch64 repoquery --arch aarch64,noarch --latest-limit 1 $PKGS"
```

Executed:
- **Debian 12** (the Linux solution's image), 6 seconds: `Inst libfontconfig1:arm64 (2.14.1-4 Debian:12.15/oldstable [arm64])`. Some dependencies resolve to the host's architecture in this simulation (`fontconfig-config ... [amd64]`, which was `[arm64]` in the arm64 image itself), so judge only the requested `:arm64` packages. A package with no arm64 build stops the simulation: the x86-only `cpuid` and `msr-tools` gave `E: Unable to locate package cpuid:arm64` and `E: Unable to locate package msr-tools:arm64`.
- **Amazon Linux 2023**, 16 seconds: `fontconfig-0:2.13.94-2.amzn2023.0.2.aarch64` and `libicu-0:67.1-7.amzn2023.0.4.aarch64`. A package with no aarch64 build prints no line: the x86-only `grub2-pc` and `microcode_ctl` printed nothing for aarch64, and `grub2-pc-1:2.06-61.amzn2023.0.22.x86_64` and `microcode_ctl-2:2.1-53.amzn2023.0.16.x86_64` without `--forcearch`.

**Common sources of native code at run time** (this list is a *prompt*, not an allowlist):
- **P/Invoke and `NativeLibrary`**: `[DllImport]`, `[LibraryImport]`, VB `Declare ... Lib`, and resolvers that build a path from `RuntimeInformation.ProcessArchitecture`. The Linux solution's resolver knows only `X64`, so on arm64 it throws `PlatformNotSupportedException: fastsum is not built for Arm64` (§1.4).
- **Windows DLLs** in imports, such as the Windows solution's `kernel32.dll`: no Linux equivalent, so the code changes (Phase 2.3).
- **Packages that run executables**:
  - Selenium.WebDriver: 4.48.0 ships one x86-64 Selenium Manager for every Linux RID, and 4.49.0 adds linux-arm64;
  - Selenium.WebDriver.ChromeDriver: its Linux chromedriver is x86-64 in every release that ships one.
- **Downloads in scripts and images**, such as the x86_64 AWS CLI installer above. The aarch64 installer, `awscli-exe-linux-aarch64.zip`, answered HTTP 200.
- **OS packages**, checked above.

**Do not rely on the named list alone.** The authoritative signals are the content checks: the per-RID report for packages and `scan` for files. Every native file the application loads must be an aarch64 build for the target's libc, whatever loads it. The greps above only find the places to look.

### 1.2.3 Tiered Validation Policy

**FAIL immediately if:**
- The target RID gets no native file, or one that is not an aarch64 build for the target's libc and glibc, AND no version or package of the same family provides one (§1.3) AND no source code is available AND the user cannot provide an arm64 build

**WARN but proceed if:**
- The line is a `CHECK` (a file outside `runtimes/` that only a tool or a test step uses), OR a managed fallback exists, OR source is available for recompilation (the Linux solution's `libfastsum.so` has its C source in `native/fastsum.c`)

**PASS if:**
- The line is `OK`: an aarch64 ELF build for the target's libc, needing no newer GLIBC_ version than the target has, with a LOAD alignment no smaller than the target's page size

For x86-only native files: check for source in the repository, document recompilation needs (Phase 2.1), or ask the user. Validate a single file with:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" scan path/to/folder   # the file's line must start with "ELF aarch64", and no FINDING may follow
file path/to/folder/libname.so            # where file(1) exists: must show "ARM aarch64"
```

## 1.3 Dependency ARM64 Compatibility Analysis

> **Output: `graviton-validation/03-dependency-compatibility-report.md`** and **`graviton-validation/raw/dependency-tree-native.txt`**

**IMPORTANT:** ARM64-incompatible native code can be introduced through transitive dependencies. A managed direct dependency may pull in a package with native files: System.Data.SQLite.Core brings Stub.System.Data.SQLite.Core.NetStandard, Microsoft.Data.Sqlite brings SQLitePCLRaw.lib.e_sqlite3, and Microsoft.NET.Test.Sdk brings Microsoft.CodeCoverage. Analyze the full tree.

### Generate Filtered Tree

Name filters miss packages whose names do not look native. The per-RID report from §1.1 is already the filtered view: it lists exactly the packages that have native files for these RIDs, found by content, each with its reference chain. Save it:

```bash
grep -E '^(FINDING|CHECK|OK|  via)' graviton-validation/raw/native-assets.txt > graviton-validation/raw/dependency-tree-native.txt
cat graviton-validation/raw/dependency-tree-native.txt
```

Executed on the Linux solution: 4 `FINDING`, 1 `CHECK` and 2 `OK` lines (quoted in [nuget-native-assets.md §3](../document_references/nuget-native-assets.md#3-the-per-rid-check)), with these chains:
- `via src/Fixture.Scoring (direct reference)` for Microsoft.ML.OnnxRuntime 1.10.0;
- `via tests/Fixture.UiTests (direct reference)` for Selenium.WebDriver 4.48.0;
- `via src/Fixture.Core (direct reference)` for SkiaSharp.NativeAssets.Linux 1.68.3;
- `via src/Fixture.Core > System.Data.SQLite.Core 1.0.119 > Stub.System.Data.SQLite.Core.NetStandard 1.0.119`;
- `via tests/Fixture.Tests > Microsoft.NET.Test.Sdk 17.11.1 > Microsoft.CodeCoverage 17.11.1`.

The full graph, including managed packages, is in `graviton-validation/raw/dependency-tree.json`.

### Classify Each Dependency

**MUST UPGRADE (Blocking):** The target RID gets no native file, or one that is x86-64, built for the other libc, needs a newer glibc than the target has, or is aligned below the target's page size; or the package has known critical ARM64 bugs; or a version that works needs a newer target framework (§1.5).

**RECOMMENDED UPGRADE (Non-blocking):** ARM64 works but has known performance issues or bug fixes in a newer version.

**COMPATIBLE (No action):** `OK` lines, and managed-only packages (the `managed only` count in the summary line).

**OUT OF SCOPE:** Security advisories that restore reports as NU1901 to NU1904 warnings (the `NOTE NuGet audit:` lines of `native-assets.txt`), such as `NU1903` for Newtonsoft.Json 12.0.3 in the Linux solution. Mention them once and change nothing ([agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md)).

For transitive dependencies: the `via` line names the direct reference that pulls the package in. Resolution may require updating that parent, or pinning the transitive package (Phase 2.2).

**AWS SDK for .NET and IMDSv2.** The target can turn a working SDK into a failing one:
- Amazon Linux 2023 AMIs launch in IMDSv2-only mode by default ([Deprecated in AL2023](https://docs.aws.amazon.com/linux/al2023/ug/deprecated-al2023.html)).
- An account can also enforce IMDSv2 for every instance: in the account used to validate this skill, switching a test instance to IMDSv1 was refused with `You can't set httpTokens to 'optional' because httpTokensEnforced is enabled for this account.`
- The AWS News Blog says that newly released EC2 instance types use only IMDSv2 from mid-2024 ([IMDSv2 by default](https://aws.amazon.com/blogs/aws/amazon-ec2-instance-metadata-service-imdsv2-by-default/)).
- AWSSDK.Core 3.3.103.66 is the release that "Updates IMDS to obtain a metadata token ... This also updates IMDS based instance profile credentials to use metadata tokens" ([SDK changelog 2019](https://github.com/aws/aws-sdk-net/blob/main/changelogs/SDK.CHANGELOG.2019.md)).

Check the resolved version:

```bash
# AWS SDK for .NET: AWSSDK.Core before 3.3.103.66 has no IMDSv2 (session token) support
python3 - graviton-validation/raw/dependency-tree.json <<'EOF'
import json, re, sys
seen = set()
for proj, frameworks in json.load(open(sys.argv[1])).items():
    for packages in frameworks.values():
        for name in packages:
            m = re.match(r"AWSSDK\.Core ([0-9.]+)$", name)
            if m:
                seen.add((m.group(1), proj))
for v, proj in sorted(seen):
    old = tuple(int(x) for x in v.split(".")) < (3, 3, 103, 66)
    print("AWSSDK.Core %s in %s: %s" % (v, proj, "no IMDSv2 support (3.3.103.66 or later needed)" if old else "IMDSv2 supported"))
print("projects resolving AWSSDK.Core: %d" % len(seen))
EOF
```

Executed on the Linux solution: `AWSSDK.Core 3.3.103.65 in src/Fixture.Api: no IMDSv2 support (3.3.103.66 or later needed)`, and the same for three more projects (AWSSDK.S3 3.3.107.1 resolves it). This is MUST UPGRADE when any target requires IMDSv2, and the floor is the first AWSSDK.S3 release that requires Core 3.3.103.66 (3.3.107.2). On Graviton4 (Amazon Linux 2023, IMDSv2 required), the fixed tool with AWSSDK.S3 put back to 3.3.107.1 failed its instance-role credentials call with `HttpRequestException: Response status code does not indicate success: 401 (Unauthorized).`, and with 3.3.107.2 it listed the account's buckets. Confirm the credentials call on the target in Phase 3.3.

### Document Findings

```
Dependency: Stub.System.Data.SQLite.Core.NetStandard (transitive via System.Data.SQLite.Core 1.0.119, from src/Fixture.Core)
Current Version: 1.0.119
Status: MUST UPGRADE (substitute: user decision)
Reason: no linux-arm64 native file in this or any stable release; its linux-x64 file SQLite.Interop.dll is an x86-64 ELF library
Evidence: native-assets.txt: FINDING no linux-arm64 native: Stub.System.Data.SQLite.Core.NetStandard/1.0.119 (linux-x64 has 1; runtimes/ folders: linux-x64, osx-x64, win-x64, win-x86)
Minimum ARM64 Version: none
Resolution: replace with Microsoft.Data.Sqlite (already in the solution, linux-arm64 and linux-musl-arm64 natives); code change in the class that uses it
```

> **Verify the package content, never the version number.** Do not infer "old version, so no arm64 file". Confirm with the per-RID report or `probe` ([nuget-native-assets.md §5](../document_references/nuget-native-assets.md#5-finding-the-lowest-version-that-works)). Counter-examples:
> - SQLitePCLRaw.lib.e_sqlite3 2.0.0 already ships a linux-arm64 file;
> - Microsoft.ML.OnnxRuntime 1.10.0 contains an aarch64 build that NuGet never selects (`runtimes/linux-aarch64`);
> - glibc needs do not only grow: SQLitePCLRaw.lib.e_sqlite3 2.0.5 needs GLIBC_2.28, while 2.0.6 needs 2.17.
>
> Also make a **missing** package fail loudly. `probe` exits 2 and prints NuGet's error when a version does not exist (`error NU1102: Unable to find package SkiaSharp.NativeAssets.Linux with version (= 9.9.9)`), so an absent package is never reported as "no arm64 file". A private feed that lacks the version is INFRA, not ARM64 ([nuget-native-assets.md §9](../document_references/nuget-native-assets.md#9-private-feeds-and-mirrors)).

### Build-Tool Artifacts with OS/Arch RIDs

Some packages carry executables that run on the build host or in test steps rather than in the application. They matter where the build or the tests run, for example on an arm64 CI runner or in a `docker build` on Graviton, even when the application never loads them. The per-RID report lists them as `CHECK` or `OK` lines (files outside `runtimes/`). Find what uses them:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# Build-time packages and tools that run executables on the build host
grep -rnE "${EX[@]}" --include='*.csproj' --include='*.fsproj' --include='*.vbproj' --include='*.props' --include='*.targets' \
  'Grpc\.Tools|PublishAot|Microsoft\.DotNet\.ILCompiler|Microsoft\.NET\.Test\.Sdk|Microsoft\.CodeCoverage|coverlet|ChromeDriver' . 2>/dev/null || true
find . \( -name .git -o -name node_modules \) -prune -o -name dotnet-tools.json -print | while IFS= read -r f; do echo "== $f"; cat "$f"; done
```

Executed on the Linux solution: `Microsoft.NET.Test.Sdk` in both test projects (version 17.11.1 in `Directory.Packages.props`) and `<PublishAot>true</PublishAot>` in `src/Fixture.Agent/Fixture.Agent.csproj`. No solution has a `dotnet-tools.json`.

| Package or feature | On an arm64 build host | Evidence |
|---|---|---|
| Grpc.Tools | `tools/linux_arm64` from 2.37.0 | `probe Grpc.Tools 2.36.4`: `CHECK ELF files outside runtimes/ in Grpc.Tools/2.36.4 are i386, x86-64 only ..., e.g. tools/linux_x64/grpc_csharp_plugin, tools/linux_x64/protoc, ...`; 2.37.0: `OK ... aarch64, i386, x86-64` |
| Native AOT (`PublishAot`) | restore adds `runtime.<rid>.Microsoft.DotNet.ILCompiler` for each RID; the compiler and linker run on the build host | publishing linux-arm64 from x64 without a cross toolchain failed: `gcc : error : unrecognized command-line option ‘--target=aarch64-linux-gnu’`. Build on arm64 (Phase 2.4) |
| Microsoft.CodeCoverage (via Microsoft.NET.Test.Sdk) | no arm64 build of its dynamic instrumentation engine | dynamic instrumentation runs on Linux x64 only, static instrumentation everywhere ([dotnet-coverage](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-coverage)); confirm coverage collection on arm64 in Phase 3.2 |
| Selenium.WebDriver.ChromeDriver | none | x86-64 Linux driver in all 281 stable releases |

Match the RID to the *target*, not the developer machine. **Graviton is Linux, so `linux-arm64` (and `linux-musl-arm64` for Alpine) decides the verdict.** `osx-arm64` and `win-arm64` matter only for local builds on Apple silicon or Windows on Arm, and are never a Graviton blocker.

## 1.4 Architecture-Specific Code Detection

> **Output: `graviton-validation/04-code-scan-findings.md`** and **`graviton-validation/raw/ca1416.txt`**

Scan the source tree for architecture-sensitive patterns. Scan from the root (`.`), not from one project folder, and include C#, VB and F# sources:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# Architecture checks with file:line
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' \
  'RuntimeInformation\.(ProcessArchitecture|OSArchitecture|RuntimeIdentifier)|Architecture\.(X64|X86|Arm64|Arm)\b|Is64Bit(Process|OperatingSystem)|IntPtr\.Size|"(linux|win|osx)-(x64|x86)"|"(x64|x86_64|amd64)"' . 2>/dev/null || true
# The risky shape: files that test for x64 but never for Arm64 (a heuristic; read the hits above)
grep -rlE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' 'Architecture\.X64|"(x64|x86_64|amd64)"' . 2>/dev/null |
  while IFS= read -r f; do grep -qE 'Architecture\.Arm64|"(arm64|aarch64)"' "$f" || echo "x64 without Arm64: $f"; done
# x86 hardware intrinsics: a call without an IsSupported check before it throws PlatformNotSupportedException on Arm64,
# and without an Arm64 or portable path the code runs a slower fallback. Heuristic: the check is in the 30 lines above.
python3 - <<'EOF'
import os, re
call = re.compile(r"\b(Sse[0-9]*|Ssse3|Avx[0-9]*|Avx512[A-Za-z]*|Bmi[12]|Fma|Lzcnt|Popcnt|Pclmulqdq|X86Base)\.([A-Z]\w*)")
for root, dirs, files in os.walk("."):
    dirs[:] = sorted(d for d in dirs if d not in (".git", "bin", "obj", "node_modules", "graviton-validation"))
    for n in sorted(files):
        if not n.endswith((".cs", ".vb", ".fs")):
            continue
        p = os.path.join(root, n)
        lines = open(p, errors="replace").read().split("\n")
        x86 = False
        for i, l in enumerate(lines):
            for m in call.finditer(l):
                if m.group(2) == "IsSupported":
                    continue
                x86 = True
                if not re.search(r"\b%s\.IsSupported" % m.group(1), "\n".join(lines[max(0, i - 30):i + 1])):
                    print("%s:%d: %s.%s without %s.IsSupported before it" % (p, i + 1, m.group(1), m.group(2), m.group(1)))
        if x86 and not re.search(r"AdvSimd|Vector128|Vector64|Vector<|System\.Numerics", "\n".join(lines)):
            print("%s: x86 intrinsics without an Arm64 or portable path" % p)
EOF
# Vector width assumptions (Vector<byte>.Count is 32 on x64 with AVX2, 16 on Arm64)
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' 'Vector256|Vector<[A-Za-z]+>\.Count' . 2>/dev/null || true
# Project settings that pin x64 or x86, or a Windows, macOS or x64 RID (from 1.1)
python3 - graviton-validation/raw/project-properties.txt <<'EOF'
import re, sys
for line in open(sys.argv[1]):
    proj, _, props = line.rstrip("\n").partition(": ")
    hits = [p for p in props.split(", ") if re.match(r"PlatformTarget=(x64|x86)$|RuntimeIdentifiers?=.*(linux-x64|win-|osx-)|Prefer32Bit=true$", p)]
    if hits:
        print("%s: %s" % (proj, ", ".join(hits)))
EOF
```

Executed on the Linux solution (selected lines):
- `./tests/Fixture.Tests/CoreTests.cs:37:` `Assert.Equal("linux-x64", RuntimeInformation.RuntimeIdentifier)`: a test that fails on arm64 by construction. Fix the test, not the code.
- `x64 without Arm64: ./src/Fixture.Core/Native.cs`: the native-library resolver handles only `Architecture.X64` and throws `PlatformNotSupportedException: fastsum is not built for Arm64` on arm64.
- `./src/Fixture.Core/Native.cs:44: Avx2.Add without Avx2.IsSupported before it`. On arm64 this throws `System.PlatformNotSupportedException: Operation is not supported on this platform.`, and the compiler gives no warning. The guarded call at line 74 (`if (Avx2.IsSupported)` at line 69) is not reported.
- `./src/Fixture.Core/Native.cs: x86 intrinsics without an Arm64 or portable path`: the guarded method falls back to a scalar loop on arm64 (RECOMMENDED: a `Vector128` path).
- The `Vector256<int>` loops in the same file.
- Project settings:
  - `./src/Fixture.Api/Fixture.Api.csproj: PlatformTarget=x64, RuntimeIdentifier=linux-x64, RuntimeIdentifiers=linux-x64`;
  - `./src/Fixture.Legacy/Fixture.Legacy.csproj: PlatformTarget=x64, RuntimeIdentifiers=linux-x64`;
  - `RuntimeIdentifiers=linux-x64` in every other project (from `Directory.Build.props`).

  These are evaluated values. The API project's file has no `<PlatformTarget>` element: the SDK derives `PlatformTarget=x64` from `RuntimeIdentifier=linux-x64` (without the RID it was empty, and with `-r linux-arm64` it was `arm64`). Find the element that sets each value, in the project file or a `Directory.Build.props`, before changing anything.

On arm64 (executed under emulation): `Avx2.IsSupported` is false and `AdvSimd.IsSupported` true; `Vector128` is hardware accelerated and `Vector256` is not; `Vector<byte>.Count` is 16, against 32 on x64 with AVX2.

Flag code that:
- checks `Architecture.X64` or an x64 RID string without an Arm64 branch;
- calls x86 intrinsics without an `IsSupported` check, or has no Arm64 or portable path;
- assumes a vector width;
- pins `PlatformTarget` to x64 or x86, or a project RID to x64 or Windows.

**Windows-only APIs.** For a Windows starting point (§1.1), compile a scratch copy on Linux. The platform compatibility analyzer, CA1416, reports calls to Windows-only APIs:

```bash
SOLUTION=Orders.slnx   # the solution (or project) from 1.1
mkdir -p graviton-validation/raw
d=$(mktemp -d)
python3 -c 'import shutil, sys; shutil.copytree(".", sys.argv[1], symlinks=True, ignore=shutil.ignore_patterns(".git", ".vs", "bin", "obj", "node_modules", "graviton-validation"))' "$d/src"
(cd "$d/src" && dotnet build "$SOLUTION" -p:EnableWindowsTargeting=true -p:RestoreLockedMode=false > "$d/build.txt" 2>&1; echo "build exit $?")
grep -oE '[^ ]+\.(cs|vb|fs)\([0-9]+,[0-9]+\): (warning|error) CA1416: [^[]+' "$d/build.txt" | sed "s#^$d/src/##" | sort -u | tee graviton-validation/raw/ca1416.txt
echo "CA1416 call sites: $(wc -l < graviton-validation/raw/ca1416.txt)"
rm -rf "$d"
```

Executed: the Windows solution reported `CA1416 call sites: 8`:
- `Registry.GetValue` (`Platform.cs(14,18)`);
- `ProtectedData.Unprotect` and `DataProtectionScope.LocalMachine` (line 18);
- `Bitmap` (lines 42 and 43) and `Image.Width` (line 44);
- `AddEventLog` (`Platform.cs(85,55)` and `Program.cs(10,1)`).

The Linux solution reported 0.

CA1416 does not report three cases:
- P/Invoke into Windows DLLs, such as the `kernel32.dll` import in §1.2.2;
- projects whose target framework ends in `-windows`, which declare Windows support;
- .NET Framework projects, which do not build on Linux (`MSB3644: The reference assemblies for .NETFramework,Version=v4.8 were not found.`).

So also search the text:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation)
# Windows paths and separators, Windows time zone IDs, Windows-only APIs (also in code the analyzer does not check)
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' --include='*.json' --include='*.config' \
  '[A-Za-z]:\\|"[^"]*\\\\[^"]*"|Standard Time"|Microsoft\.Win32|Registry\.|EventLog|ProtectedData|WindowsIdentity|ServiceBase|AddWindowsService|System\.Drawing|System\.Management|System\.DirectoryServices' . 2>/dev/null || true
# .NET Framework technologies without a Linux path, or with a different one on modern .NET
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' \
  'System\.Web\.(UI|Http|Mvc)|System\.ServiceModel|System\.EnterpriseServices|System\.Runtime\.Remoting|AppDomain\.CreateDomain|BinaryFormatter|System\.Workflow|System\.Activities' . 2>/dev/null || true
find . \( -name .git -o -name bin -o -name obj -o -name graviton-validation \) -prune -o -type f \( -name '*.aspx' -o -name '*.ascx' -o -name '*.asmx' -o -name '*.svc' -o -name 'Global.asax' -o -name '*.xaml' \) -print
find . \( -name .git -o -name bin -o -name obj -o -name graviton-validation \) -prune -o -type f -iname 'web.config' -print | while IFS= read -r f; do
  grep -nE '<authentication mode="Windows"|<system\.serviceModel>|<httpModules>|<httpHandlers>|targetFramework=' "$f" | sed "s#^#$f:#"; done
# Deployment descriptors, scripts and CI that pin x64, Windows or one architecture
grep -rnE "${EX[@]}" --include='Dockerfile*' --include='*.y*ml' --include='*.json' --include='*.sh' --include='*.ps1' --include='*.template' -- \
  '--platform[= ]linux/amd64|(-r|--runtime) (linux|win)-x64|(-a|--arch) (x64|amd64)|nanoserver|servercore|kubernetes\.io/arch: *amd64|runs-on: |x86_64|uname -m|docker build |--locked-mode' . 2>/dev/null || true
```

Executed:
- **Windows solution:**
  - `@"C:\ProgramData\Orders"` (`Platform.cs:25`);
  - `"Config\\Settings.json"` (`Platform.cs:35`), where the file on disk is `config/settings.json`;
  - `"Pacific Standard Time"` (`Platform.cs:38`);
  - `AddWindowsService` and `AddEventLog` (`Program.cs:9` and `10`);
  - the two `nanoserver-ltsc2022` images, and the `runs-on: windows-latest` job that publishes with `-r win-x64`.
- **.NET Framework solution:**
  - the `ServiceBase` class and `Data Source=C:\ProgramData\Orders\orders.db` in `Web.config`;
  - `BinaryFormatter`, `System.ServiceModel`, `AppDomain.CreateDomain`, `System.Web.Http` and `System.Web.UI`;
  - `OrderService.svc`, `Global.asax` and `Default.aspx`;
  - `<authentication mode="Windows" />` and `<system.serviceModel>` in `Web.config`.
- **Linux solution:**
  - the `x86_64` Lambda architecture and `kubernetes.io/arch: amd64`;
  - the `uname -m` gate and the x86_64 AWS CLI URL in `deploy/deploy.sh`;
  - `FROM --platform=linux/amd64 mcr.microsoft.com/dotnet/sdk:8.0 AS build` and `-r linux-x64` in the Dockerfile;
  - in CI: `runs-on: ubuntu-latest`, `dotnet restore --locked-mode`, `-r linux-x64` for the Native AOT agent and a single-architecture `docker build`.

What each Windows or .NET Framework hit means on Linux, with the replacement, is in [windows-to-linux.md](../document_references/windows-to-linux.md). The descriptor fixes are in Phase 2.4.

## 1.5 .NET Version Compatibility Check

> **Output: `graviton-validation/01-project-assessment.md`** (.NET Environment section)

```bash
# Target frameworks in use (from 1.1) and the SDK the repository pins
grep -oE 'TargetFrameworks?=[^,]+|TargetFrameworkVersion=[^,]+' graviton-validation/raw/project-properties.txt | sort | uniq -c
find . \( -name .git -o -name node_modules \) -prune -o -name global.json -print | while IFS= read -r f; do echo "== $f"; cat "$f"; done
# Support phase and end of support of every .NET release (Microsoft release metadata)
curl -fsSL https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json | python3 -c 'import json, sys
for r in json.load(sys.stdin)["releases-index"]:
    print("%-5s %-12s end of support %-10s latest runtime %s" % (r["channel-version"], r["support-phase"], r.get("eol-date") or "-", r["latest-runtime"]))'
```

Executed (first lines):

```
11.0  go-live      end of support -          latest runtime 11.0.0-rc.1.26425.128
10.0  active       end of support 2028-11-14 latest runtime 10.0.12
9.0   maintenance  end of support 2026-11-10 latest runtime 9.0.20
8.0   maintenance  end of support 2026-11-10 latest runtime 8.0.31
7.0   eol          end of support 2024-05-14 latest runtime 7.0.20
6.0   eol          end of support 2024-11-12 latest runtime 6.0.36
```

Target frameworks and SDKs found:
- **Linux solution:** `net8.0` (7 projects), `netcoreapp3.1` (the Lambda function) and `netstandard2.0`; `global.json` pins SDK 8.0.400 with `latestFeature`, so SDK 8.0.425 is selected.
- **Windows solution:** `net8.0` (2) and `net8.0-windows` (1); no `global.json`, so SDK 10.0.401 is selected.
- **.NET Framework solution:** `TargetFrameworkVersion=v4.8` and `netstandard2.0`.

1. Document the target framework of every project, the SDK (`global.json`), the runtime image tags, and the Lambda runtimes (§1.1).
2. **Modern .NET runs on Linux Arm64:**
   - Microsoft's supported-OS lists for .NET 8 and 10 include Arm64 for Linux distributions such as Alpine, Azure Linux, CentOS Stream and Debian ([8.0](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md), [10.0](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)).
   - .NET 10 needs glibc 2.27, which Amazon Linux 2 (glibc 2.26) does not have; .NET 8 needs glibc 2.23. On Graviton4, in an `amazonlinux:2` container, .NET 8.0.31 ran a console app and .NET 10.0.12 stopped at ``Failed to load .../libcoreclr.so, error: /lib64/libm.so.6: version `GLIBC_2.27' not found``; .NET 10.0.12 ran on AlmaLinux 8 (glibc 2.28).
   - The .NET Framework does not support Linux, and Windows is not supported on Graviton ([dotnet.md](https://github.com/aws/aws-graviton-getting-started/blob/main/dotnet.md#net-versions)).
3. **Support:** .NET 10 (LTS) is supported until 2028-11-14; .NET 8 (LTS) and .NET 9 until 2026-11-10; earlier releases are out of support. The repository's guidance recommends .NET 10 for new Graviton workloads, or .NET 8 or 9 when an earlier supported release is needed ([dotnet.md](https://github.com/aws/aws-graviton-getting-started/blob/main/dotnet.md#recommended-versions)).
4. **Lambda:** changing a function's architecture means uploading new code built for it ([Lambda architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html)). After a runtime's block-update date, "Lambda begins blocking the update of code and configuration for existing functions", but "You can still upgrade the function configuration to a supported runtime" ([Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)):

   | Runtime | OS | Deprecation | Block create | Block update |
   |---|---|---|---|---|
   | `dotnet10` | Amazon Linux 2023 | Nov 14, 2028 | Dec 14, 2028 | Jan 15, 2029 |
   | `dotnet8` | Amazon Linux 2023 | Nov 10, 2026 | Jul 29, 2027 | Aug 31, 2027 |
   | `dotnet6` | Amazon Linux 2 | Dec 20, 2024 | Jul 29, 2027 | Aug 31, 2027 |
   | `dotnetcore3.1` | Amazon Linux 2 | Apr 3, 2023 | Apr 3, 2023 | May 3, 2023 |

   So the Linux solution's `dotnetcore3.1` function cannot move to arm64 as it is: its runtime must move too (MUST UPGRADE). The Lambda API refused a new `dotnetcore3.1` function for both architectures: `The runtime parameter of dotnetcore3.1 is no longer supported for creating or updating AWS Lambda functions.`
5. **DO NOT change** target frameworks or the SDK, except where the move to Graviton requires it:
   - a .NET Framework or `-windows` target framework: port to modern .NET on Linux (MUST UPGRADE);
   - a runtime that cannot run on arm64 as it is, such as Lambda `dotnetcore3.1`;
   - a package version that works on arm64 but needs a newer target framework. For example, LibGit2Sharp 0.27.0 targets net472 and net6.0, while 0.26.2 targets net46 and netstandard2.0.

   Each of these is one decision for the whole solution: present the options with their support dates and the glibc they need, and apply the choice after one approval (`dotnet.framework_bump` in `skill-config.md`). An out-of-support framework that still has a linux-arm64 runtime (Microsoft.NETCore.App.Runtime.linux-arm64 exists for 3.1.32) is a RECOMMENDED UPGRADE for EC2 and containers, not a Graviton requirement.
6. The SDK used for the build and test steps is aligned in Phase 3.0.
