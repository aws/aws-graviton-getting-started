# Phase 1: Static Compatibility Analysis

Analyze the project without making changes. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below picks target runtime identifiers (RIDs), use `dotnet.target_rids` from `skill-config.md` (if defined) in place of the default `linux-arm64`, and use `dotnet.framework_bump` in §1.5. See [skill-configuration.md](skill-configuration.md).

Phase 1 runs on any host, including x86, and changes nothing in the repository. Three steps execute the repository's MSBuild files:
- the property listing in §1.1 (`dotnet msbuild -getProperty`), which evaluates every project with its `Directory.Build.props` and `Directory.Build.targets`;
- `assets` in §1.1, whose restore of a scratch copy also runs any target hooked to restore (a test target with `BeforeTargets="Restore"` ran its `Exec`);
- for a Windows starting point, the CA1416 build of a scratch copy in §1.4, which runs the whole build.

MSBuild also reads `Directory.Build.rsp` for these steps, and that file can add targets: with `-t:` in it, the property listing ran a target of the repository. List what the repository's MSBuild files can run (block below) before the first of them, and for a repository you do not trust, run Phase 1 in a disposable container or VM. `scan` only reads files, and `probe` and `config` restore a project that the check program writes in a scratch folder, copying only `NuGet.config`. Two steps run container images, with the image's own tools: the libc check of each target image (§1.1) and the OS package lookups (§1.2.2). No test or application of the project runs until Phase 3. The commands were executed in bash 5.2 and zsh 5.9 on Linux. They need the .NET SDK, Python 3.6 or later, and the check program, written once per session with the block in [nuget-native-assets.md §11](nuget-native-assets.md#11-the-check-program):

```bash
dotnet --list-sdks
dotnet --version   # the SDK this repository selects (global.json in this folder or a parent)
python3 -c 'import sys; assert sys.version_info >= (3, 6), sys.version; print("python3", sys.version.split()[0])'
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
[ -f "$GV_CHECK" ] || echo "ERROR: write the check program first (nuget-native-assets.md, section 11)"
```

> **If `dotnet --version` fails** with `A compatible .NET SDK was not found.`, the repository's `global.json` pins an SDK that is not installed. Apply the session-scoped SDK switch from [phase3-validation.md](phase3-validation.md) §3.0 now: the first `dotnet` command needs it, not only Phase 3.

Before the property listing, `assets` and the CA1416 build, list the repository's MSBuild code that they can run. The block only reads files; read every line it prints, because an `Exec`, a `UsingTask` or an imported file runs during those steps:

```bash
grep -rnE --exclude-dir=bin --exclude-dir=obj --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=artifacts \
  --include='*.csproj' --include='*.fsproj' --include='*.vbproj' --include='*.props' --include='*.targets' --include='*.proj' \
  '<(Exec|UsingTask|Import)[[:space:]>]|(Before|After)Targets=|InitialTargets=' . | cut -c1-200
find . \( -name bin -o -name obj -o -name .git -o -name node_modules \) -prune -o -name '*.rsp' -print
```

Examples below refer to three test solutions:
- the **Linux solution**: nine projects on .NET 8 for Linux x64, with central package versions and lock files;
- the **Windows solution**: a Windows service, an IIS-hosted API and a Windows Forms tool on .NET 8;
- the **.NET Framework solution**: a .NET Framework 4.8 web application and a .NET Standard library.

## Contents

- 1.1 Project Structure Analysis: Determine Deployment Type; Detect Multi-Module Structure; Determine Starting Point; Determine Target OS and libc; Generate Dependency Tree; Categorize Components by Risk
- 1.2 Native Library Validation: 1.2.1 Statically Bundled .so Scanning; 1.2.2 Runtime-Extracted Native Library Detection; 1.2.3 Tiered Validation Policy
- 1.3 Dependency ARM64 Compatibility Analysis: Generate Filtered Tree; Classify Each Dependency; Document Findings; Build-Tool Artifacts with OS/Arch RIDs
- 1.4 Architecture-Specific Code Detection
- 1.5 .NET Version Compatibility Check

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`**, **`graviton-validation/raw/project-properties.txt`**, **`graviton-validation/raw/dependency-tree.json`** and **`graviton-validation/raw/native-assets.txt`**

### Determine Deployment Type

- Dockerfile or container config present, under any name (`Dockerfile*`, `*.Dockerfile`, `Containerfile`; `docker build -f` and Compose `dockerfile:` accept any name; the block lists them all in `raw/dockerfiles.txt`): **Containerized**
- systemd/init scripts, or a published app started directly (`dotnet <app>.dll` or its apphost): **Host-based**
- A CDK app (`cdk.json`) or Terraform files define the infrastructure, and its architecture settings, in code (§1.4)
- Some applications support both
- AWS Lambda (`aws-lambda-tools-defaults.json`, a SAM, CloudFormation, CDK or Terraform function with a `dotnet` runtime, or a Lambda container image): **Lambda**. The architecture is a function setting (§1.5).
- IIS (`web.config`, `AspNetCoreHostingModel`, `UseIIS`) or a Windows service (`AddWindowsService`, `UseWindowsService`, `ServiceBase`, installation scripts): **Windows host**. The application must move to Linux first ([Determine Starting Point](#determine-starting-point)).

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
# Deployment files (read every hit)
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules -o -name cdk.out -o -name graviton-validation \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' \
  -o -name 'Containerfile*' -o -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' -o -name 'aws-lambda-tools-defaults.json' -o -name 'serverless.template' \
  -o -name 'template.y*ml' -o -name 'cdk.json' -o -name '*.tf' -o -name '[Ww]eb.config' -o -name '*.service' -o -name '*.ps1' -o -name '*.sh' \) -print | sort
# Hosting markers: Kubernetes, Lambda, IIS, Windows services
grep -rnE "${EX[@]}" --include='*.y*ml' --include='*.json' --include='*.template' --include='*.cs' --include='*.vb' --include='*.fs' \
  --include='*.csproj' --include='*.vbproj' --include='*.fsproj' --include='*.config' \
  'kubernetes\.io/arch|AWS::(Serverless|Lambda)::Function|"function-runtime"|AddWindowsService|UseWindowsService|ServiceBase|UseIIS|AspNetCoreHostingModel' . 2>/dev/null || true
# Dockerfiles under any name: by name, plus the files a build's -f or --file, Compose dockerfile: and
# docker/build-push-action file: name. A file is kept when it has a FROM line; a name that is no file
# here is printed: find that file by hand and add it to the list.
mkdir -p graviton-validation/raw
{ find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules -o -name cdk.out -o -name graviton-validation \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' -o -name 'Containerfile*' \) -print
  grep -rnoE "${EX[@]}" --include='*.sh' --include=Makefile --include='*.mk' --include='*.y*ml' --include='Jenkinsfile*' -- \
    "(build|bud)[[:space:]][^;|&#]*(-f[[:space:]]+|--file[[:space:]=]+)[\"']?[^[:space:];|&\"')]+|(dockerfile|file):[[:space:]]*[\"']?[^[:space:]#\"']+" . |
    while IFS= read -r hit; do
      src=${hit%%:*}; ref=$(printf '%s\n' "${hit#*:*:}" | sed -E "s/^.*(-f[[:space:]]+|--file[[:space:]=]+|file:[[:space:]]*)[\"']?//")
      if [ -f "$ref" ]; then printf './%s\n' "${ref#./}"
      elif [ -f "${src%/*}/$ref" ]; then printf '%s/%s\n' "${src%/*}" "${ref#./}"
      else printf 'not found: %s names %s\n' "$src" "$ref" >&2; fi
    done
} | while IFS= read -r f; do grep -qiE '^[[:space:]]*FROM[[:space:]]' "$f" && printf '%s\n' "$f"; done |
  sort -u > graviton-validation/raw/dockerfiles.txt
cat graviton-validation/raw/dockerfiles.txt
```

### Detect Multi-Module Structure

- Solutions: `.sln`, `.slnx` (written by `dotnet new sln` in SDK 10) and `.slnf` list projects
- `Directory.Build.props`, `Directory.Build.targets` and `Directory.Packages.props` (central package versions) apply to every project below their folder
- If multi-project: enumerate all project files (`.csproj`, `.fsproj`, `.vbproj`), analyze each independently, including projects no solution lists
- Native libraries may come from any project; do NOT limit the analysis to the startup project

```bash
# Solutions, projects and the files that shape every project's build
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name '*.sln' -o -name '*.slnx' -o -name '*.slnf' \
  -o -name '*.csproj' -o -name '*.fsproj' -o -name '*.vbproj' -o -name 'Directory.Build.props' -o -name 'Directory.Build.targets' \
  -o -name 'Directory.Packages.props' -o -name 'global.json' -o -iname 'nuget.config' -o -name 'packages.config' -o -name 'packages.lock.json' \
  -o -name 'dotnet-tools.json' \) -print | sort
# Projects each solution lists; a project found above but listed by no solution is analyzed too
find . -maxdepth 1 -type f \( -name '*.sln' -o -name '*.slnx' \) | while IFS= read -r s; do echo "== $s"; dotnet sln "$s" list < /dev/null; done
```

SDK 8.0.425 cannot read a `.slnx` solution (``Invalid solution `Orders.slnx`. Expected file header not found.``); SDK 10.0.401 can.

### Determine Starting Point

Graviton instances and arm64 Lambda functions run Linux, so the first question is how far the code is from modern .NET on Linux. Read it from the evaluated properties of every project (`Directory.Build.props` and other imports applied). `-getProperty` evaluates the project without building it; it needs MSBuild 17.8 or later ([Microsoft Learn](https://learn.microsoft.com/en-us/visualstudio/msbuild/evaluate-items-and-properties)), and was run with SDK 8.0.425 and 10.0.401:

```bash
mkdir -p graviton-validation/raw
# Evaluated properties of every project file, one line each
P=TargetFramework,TargetFrameworks,TargetFrameworkVersion,OutputType,RuntimeIdentifier,RuntimeIdentifiers,PlatformTarget,Prefer32Bit,UseWindowsForms,UseWPF,SelfContained,PublishAot,PublishReadyToRun,PublishSingleFile,InvariantGlobalization,AspNetCoreHostingModel,UsingMicrosoftNETSdk
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name '*.csproj' -o -name '*.fsproj' -o -name '*.vbproj' \) -print | sort |
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
| .NET Framework | no `UsingMicrosoftNETSdk`, `TargetFrameworkVersion=v4.x`, a `packages.config`; or `TargetFramework` `net4x` | **MUST UPGRADE:** port to modern .NET on Linux, one approval for the whole solution ([windows-to-linux.md](windows-to-linux.md)) |
| Modern .NET on Windows | `TargetFramework` ending in `-windows`, `UseWindowsForms=true` or `UseWPF=true`, `RuntimeIdentifier=win-*`, plus the Windows hosting markers above | **MUST UPGRADE:** move to Linux, one approval for the whole solution. Windows Forms and WPF projects have no Linux path: **BLOCKER**, user decision |
| Modern .NET on Linux | `TargetFramework` `netcoreapp*` or `net5.0` and later, Linux RIDs | the arm64 checks in this skill apply directly |
| .NET Standard library | `TargetFramework` `netstandard*` | portable; the same checks apply |

A project without `UsingMicrosoftNETSdk=true` is not an SDK-style project (a .NET Framework project, with `TargetFrameworkVersion=v4.8`, for example).

Never decide the starting point from a successful build or publish. With `EnableWindowsTargeting=true`, `dotnet publish -r linux-arm64` of the Windows Forms tool exited 0 and produced an aarch64 apphost, but its `.runtimeconfig.json` requires `Microsoft.WindowsDesktop.App`, which exists only on Windows. Phase 3's output scan reports that file; the properties above report it first.

### Determine Target OS and libc

Native files depend on the OS the workload runs on as well as the CPU: glibc or musl, the glibc version, and the kernel's page size ([nuget-native-assets.md §6](nuget-native-assets.md#6-target-os-libc-glibc-version-page-size)). Find every target:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
# The image each Dockerfile's last stage runs on
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.dockerfile' \) -print |
  while IFS= read -r f; do echo "$f: $(grep -iE '^[[:space:]]*FROM[[:space:]]' "$f" | tail -n 1)"; done
# Lambda runtimes and architectures
grep -rnE "${EX[@]}" --include='*.y*ml' --include='*.json' --include='*.template' \
  'Runtime:[[:space:]]*(dotnet|provided)|"function-runtime"|Architectures:|"function-architecture"|- (x86_64|arm64)$' . 2>/dev/null || true
```

Then, for each target:
- **Container images:** read the image's libc, and for a glibc image its libstdc++ version, with the blocks in [nuget-native-assets.md §6](nuget-native-assets.md#6-target-os-libc-glibc-version-page-size), which also list the results for the common .NET and Lambda images.
- **Lambda managed runtimes:** `dotnet8` and `dotnet10` run on Amazon Linux 2023 (glibc 2.34); `dotnet6` and `dotnetcore3.1` ran on Amazon Linux 2 (glibc 2.26) ([Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)).
- **EC2 hosts:** ask for the AMI if no file names it. Amazon Linux 2023 AMIs launch in IMDSv2-only mode by default ([Deprecated in AL2023](https://docs.aws.amazon.com/linux/al2023/ug/deprecated-al2023.html)); §1.3 uses this for the AWS SDK.

Record four values for the rest of the skill:
- the **target RIDs**: `linux-arm64`, plus `linux-musl-arm64` when any target image is Alpine;
- the **lowest glibc version** across the targets;
- the **lowest libstdc++ version** (`GLIBCXX_3.4.N`) across the glibc targets, when it can be read for each of them (from an image, with the block in §6; a Lambda managed runtime has no image to read it from);
- the **page size** when a target kernel uses 64KB pages (AlmaLinux 8 and Rocky Linux 8 aarch64).

For a Lambda function on a managed .NET runtime, the arm64 target is `dotnet8` or `dotnet10` (§1.5), so the lowest glibc is 2.34; the managed runtime's libstdc++ version cannot be read, so `--glibcxx` is left out. When no file names the target OS, as for an EC2 host whose AMI no file names, ask.

### Generate Dependency Tree

> **If this restore fails** for the SDK reason above, or because the project needs an SDK feature the selected SDK lacks, apply the session-scoped SDK switch from [phase3-validation.md](phase3-validation.md) §3.0 now.

One scratch restore gives both the dependency tree (every resolved package with the shortest reference chain from a project, as JSON) and the per-RID native report used in §1.2 and §1.3. The repository is not modified ([nuget-native-assets.md §3](nuget-native-assets.md#3-the-per-rid-check)):

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
# --source-rid: linux-x64 for a Linux starting point, win-x64 for Windows. --glibc: the target's version (Determine Target OS and libc);
# add --glibcxx and --page-size when those values were recorded there.
python3 "$GV_CHECK" assets --source-rid linux-x64 --target-rid linux-arm64 --glibc 2.34 \
  --tree graviton-validation/raw/dependency-tree.json > graviton-validation/raw/native-assets.txt; rc=$?
cat graviton-validation/raw/native-assets.txt; echo "exit status $rc (0 no findings, 1 findings, 2 restore failed or wrote no project.assets.json)"
# Sanity check: nothing resolved is a failed restore, not an all-clear (unless the solution references no packages)
grep -q '^packages: [1-9]' graviton-validation/raw/native-assets.txt || echo "WARNING: no packages resolved; read the restore errors above"
```

A project that uses `packages.config` is not in this report: the program prints `CHECK <file>: these packages are not restored by PackageReference and are not in this report; run: config <file>`, and that project gets the per-package check instead ([nuget-native-assets.md §3](nuget-native-assets.md#projects-that-still-use-packagesconfig)).

### Categorize Components by Risk

- **CRITICAL**: Native code (NuGet native assets, P/Invoke, committed `.so` files), x86 hardware intrinsics, Windows Forms and WPF, .NET Framework technology with no modern .NET equivalent (Web Forms)
- **HIGH**: Packages with known x64-only versions, Windows-only APIs, runtimes that cannot move to arm64 as they are (Lambda `dotnetcore3.1`), crypto and graphics libraries with native parts
- **MEDIUM**: Build configs (RIDs, `PlatformTarget`, lock files), Dockerfiles, deployment scripts, CI files, architecture detection code
- **LOW**: Managed code built as AnyCPU, without architecture or OS dependencies

## 1.2 Native Library Validation (.so File Analysis)

> **Output: `graviton-validation/02-native-library-report.md`**, **`graviton-validation/raw/native-assets.txt`** (from §1.1) and **`graviton-validation/raw/repo-native-scan.txt`**

Native code reaches a .NET application in four ways ([nuget-native-assets.md §1](nuget-native-assets.md#1-managed-code-native-code-and-what-decides-each)):
- files under `runtimes/<rid>/native/` in NuGet packages;
- files that packages keep elsewhere and copy to the output or run;
- files committed to the repository;
- downloads at run time.

The per-RID report from §1.1 covers the first two. This section reads it, scans the repository, and finds what arrives at run time. All of them depend on the target OS as well as the CPU (§1.1, Determine Target OS and libc).

### 1.2.1 Statically Bundled .so Scanning

Statically bundled native code sits in two places. Judge both by content, never by name: a Linux library can be named `SQLite.Interop.dll`, and an executable has no extension.

1. **NuGet packages.** Read `graviton-validation/raw/native-assets.txt` from §1.1. Each package with native files for the source or target RIDs gets one line per target RID and file:
   - `OK`: an aarch64 build for the target's libc, with the GLIBC_ and GLIBCXX_ versions it needs, its LOAD alignment and the libraries it needs;
   - `FINDING`: no file for the target RID, or a file that is x86-64, an Android build, built for the other libc, too new for the target's glibc or libstdc++, linked for a smaller page size than the target's, or a Windows or macOS binary;
   - `CHECK`: x86-only files outside `runtimes/`, which fail only if a build target copies them or a tool runs them;
   - an indented `via` line under each `FINDING` and `CHECK`, with the reference chain from a project.

   What each line means, and the package shapes behind them: [nuget-native-assets.md §3 and §4](nuget-native-assets.md#3-the-per-rid-check).
2. **Files committed to the repository**: vendored libraries, prebuilt helpers, and managed assemblies built for one architecture. Scan the source tree by content. `--source-tree` skips `.git`, `.vs`, `bin`, `obj`, `node_modules` and `graviton-validation`; build and publish outputs are scanned in Phase 3.1:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" scan --source-tree . > graviton-validation/raw/repo-native-scan.txt; rc=$?
cat graviton-validation/raw/repo-native-scan.txt; echo "exit status $rc (0 no findings, 1 findings, 2 not a folder)"
```

The same scan reports committed managed assemblies built for x64 or x86, which fail on arm64 as described in [nuget-native-assets.md §1](nuget-native-assets.md#1-managed-code-native-code-and-what-decides-each).

### 1.2.2 Runtime-Extracted Native Library Detection

Some code loads or downloads native code at run time instead of shipping it in a package, and some images install it from the OS:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
# Native loads with file:line (C#, VB, F#)
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' \
  '[[<](DllImport|LibraryImport)\(|Declare (Auto |Ansi |Unicode )?(Function|Sub) .* Lib "|NativeLibrary\.(Load|TryLoad|SetDllImportResolver)|LoadUnmanagedDll|GetDelegateForFunctionPointer' . 2>/dev/null || true
# Every download in scripts, Dockerfiles and CI. A URL that names no architecture still fetches a build
# for one, so each downloaded file is judged by its content (below)
grep -rnE "${EX[@]}" --include='*.sh' --include='*.ps1' --include='*.cmd' --include='Dockerfile*' --include='*.[Dd]ockerfile' \
  --include='Containerfile*' --include='*.y*ml' --include='Jenkinsfile*' '(curl|wget|Invoke-WebRequest|iwr|Start-BitsTransfer)[[:space:]]|^[[:space:]]*ADD([[:space:]]+--[^[:space:]]+)*[[:space:]]+https?:|releases/(latest/)?download/' . 2>/dev/null || true
# Packages that run or download executables (a prompt, not an allowlist; the content check decides)
grep -rnE "${EX[@]}" --include='*.csproj' --include='*.fsproj' --include='*.vbproj' --include='*.props' --include='*.targets' --include='packages.config' \
  'Selenium\.WebDriver|Microsoft\.Playwright|ChromeDriver|GeckoDriver' . 2>/dev/null || true
# OS packages that images and scripts install (each must exist for arm64 on the target OS)
grep -rnE "${EX[@]}" --include='Dockerfile*' --include='*.sh' '(apt-get|apt|dnf|yum|microdnf|apk|zypper)[[:space:]].*(install|add)[[:space:]]' . 2>/dev/null || true
```

Windows system DLLs never exist on Linux: a `[DllImport("kernel32.dll")]` call fails there with `DllNotFoundException: Unable to load shared library 'kernel32.dll' or one of its dependencies`.

Fetch each download into a scratch folder and scan what it holds, whatever its URL says. Resolve the script's variables in the URL first; an archive is unpacked first:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
URL='https://github.com/jqlang/jq/releases/download/jq-1.6/jq-linux64'   # one download from the list above
d=$(mktemp -d "${TMPDIR:-/tmp}/graviton-download.XXXXXX"); mkdir "$d/x"
if curl -fsSL --max-time 300 -o "$d/download" "$URL"; then
  # Unpack by the first bytes, not the name: a .deb (an ar archive), an .rpm, a zip or a tar archive
  case "$(od -An -tx1 -N4 "$d/download" | tr -d ' \t\n')" in
    213c6172) if head -c 64 "$d/download" | grep -q debian-binary; then   # another ar archive is a static library, which the scan reads
                (cd "$d/x" && ar x ../download && for t in data.tar.*; do tar -xf "$t"; done) && rm "$d/download" \
                  || echo "CHECK: $URL is a .deb this host cannot unpack (needs ar, and tar with xz or zstd)"
              fi ;;
    edabeedb) { if command -v rpm2cpio > /dev/null 2>&1; then (cd "$d/x" && rpm2cpio ../download | cpio -idm --quiet)
                else bsdtar -xf "$d/download" -C "$d/x"; fi; } && rm "$d/download" \
                || echo "CHECK: $URL is an .rpm this host cannot unpack (needs rpm2cpio and cpio, or bsdtar)" ;;
    *) python3 -m zipfile -e "$d/download" "$d/x" 2>/dev/null || tar -xf "$d/download" -C "$d/x" 2>/dev/null ;;
  esac
  python3 "$GV_CHECK" scan "$d"
else echo "CHECK: $URL did not download"; fi
rm -rf "$d"
```

Executed: jq 1.6's `jq-linux64`, whose URL names no architecture, gave `FINDING download is x86-64`; jq 1.7.1's `jq-linux-arm64` gave no finding. A download that cannot be fetched from here (credentials, a private network) stays CHECK until it is scanned where it can be.

Check that every OS package exists for arm64 on the target OS, from a container that runs natively on this host. On an x86 host, asking the arm64 image itself runs under emulation; that took 17 seconds for Debian and did not finish in 480 seconds for Amazon Linux 2023.

```bash
# Debian or Ubuntu target: ask its package index for the arm64 builds, from a container that runs natively on this host
IMG=mcr.microsoft.com/dotnet/aspnet:8.0   # the runtime image (Determine Target OS and libc)
PKGS="libfontconfig1"                     # the packages its Dockerfile installs
command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
ARM_PKGS=$(echo "$PKGS" | sed 's/[^ ][^ ]*/&:arm64/g')
# On an amd64 Ubuntu image the x86 mirrors carry no arm64 files (apt-get update: "binary-arm64/Packages 404 Not
# Found"): keep the image's sources for amd64 and read arm64 from ports.ubuntu.com
PORTS='. /etc/os-release
if [ "$ID" = ubuntu ] && [ "$(dpkg --print-architecture)" = amd64 ]; then
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do [ -f "$f" ] && sed -i -E "s/^deb (https?:)/deb [arch=amd64] \1/" "$f"; done
  for f in /etc/apt/sources.list.d/*.sources; do [ -f "$f" ] && sed -i "/^Types:/a Architectures: amd64" "$f"; done
  for s in "" -updates -security; do
    echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports $VERSION_CODENAME$s main restricted universe multiverse"
  done > /etc/apt/sources.list.d/arm64-ports.list
fi
'
# 480 seconds inside the container stops apt-get; 600 outside stops the container if it does not exit
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "$PORTS dpkg --add-architecture arm64 && apt-get update -qq && apt-get install -s --no-install-recommends $ARM_PKGS 2>&1 | grep -E '^(Inst|E:)'"
```

```bash
# Amazon Linux 2023 (dnf) target: ask the aarch64 repositories, from a container that runs natively on this host
IMG=public.ecr.aws/amazonlinux/amazonlinux:2023
PKGS="fontconfig libicu"
command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
# 480 seconds inside the container stops dnf; 600 outside stops the container if it does not exit
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "dnf -q --forcearch aarch64 repoquery --arch aarch64,noarch --latest-limit 1 $PKGS"
```

- **Debian or Ubuntu** (observed on Debian 12, Ubuntu 22.04 and Ubuntu 24.04): judge only the requested `:arm64` packages, because some dependencies resolve to the host's architecture in this simulation. A package with no arm64 build stops it: `E: Unable to locate package <name>:arm64`.
- **Amazon Linux 2023:** a package with no aarch64 build prints no line.

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

The full graph, including managed packages, is in `graviton-validation/raw/dependency-tree.json`.

### Classify Each Dependency

**MUST UPGRADE (Blocking):** The target RID gets no native file, or one that is x86-64, built for the other libc, needs a newer glibc than the target has, or is aligned below the target's page size; or the package has known critical ARM64 bugs; or a version that works needs a newer target framework (§1.5).

**RECOMMENDED UPGRADE (Non-blocking):** ARM64 works but has known performance issues or bug fixes in a newer version.

**COMPATIBLE (No action):** `OK` lines, and managed-only packages (the `managed only` count in the summary line).

**OUT OF SCOPE:** Security advisories that restore reports as NU1901 to NU1904 warnings (the `NOTE NuGet audit:` lines of `native-assets.txt`), such as `NU1903` for Newtonsoft.Json 12.0.3 in the Linux solution. Mention them once and change nothing ([agent-scope-boundaries.md](agent-scope-boundaries.md)).

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

An AWSSDK.Core older than 3.3.103.66 has no IMDSv2 support. This is MUST UPGRADE when any target requires IMDSv2, and the floor is the first release of the referenced AWSSDK package that requires Core 3.3.103.66 (AWSSDK.S3 3.3.107.2). Without it, the instance-role credentials call failed on Graviton4 with IMDSv2 required: `HttpRequestException: Response status code does not indicate success: 401 (Unauthorized).` Confirm the credentials call on the target in Phase 3.3.

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

> **Verify the package content, never the version number.** Do not infer "old version, so no arm64 file". Confirm with the per-RID report or `probe` ([nuget-native-assets.md §5](nuget-native-assets.md#5-finding-the-lowest-version-that-works)). Counter-examples:
> - SQLitePCLRaw.lib.e_sqlite3 2.0.0 already ships a linux-arm64 file;
> - Microsoft.ML.OnnxRuntime 1.10.0 contains an aarch64 build that NuGet never selects (`runtimes/linux-aarch64`);
> - glibc needs do not only grow: SQLitePCLRaw.lib.e_sqlite3 2.0.5 needs GLIBC_2.28, while 2.0.6 needs 2.17.
>
> Also make a **missing** package fail loudly. `probe` exits 2 and prints NuGet's error when a version does not exist (`error NU1102: Unable to find package SkiaSharp.NativeAssets.Linux with version (= 9.9.9)`), so an absent package is never reported as "no arm64 file". A private feed that lacks the version is INFRA, not ARM64 ([nuget-native-assets.md §9](nuget-native-assets.md#9-private-feeds-and-mirrors)).

### Build-Tool Artifacts with OS/Arch RIDs

Some packages carry executables that run on the build host or in test steps rather than in the application. They matter where the build or the tests run, for example on an arm64 CI runner or in a `docker build` on Graviton, even when the application never loads them. The per-RID report lists them as `CHECK` or `OK` lines (files outside `runtimes/`). Find what uses them:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
# Build-time packages and tools that run executables on the build host
grep -rnE "${EX[@]}" --include='*.csproj' --include='*.fsproj' --include='*.vbproj' --include='*.props' --include='*.targets' \
  'Grpc\.Tools|PublishAot|Microsoft\.DotNet\.ILCompiler|Microsoft\.NET\.Test\.Sdk|Microsoft\.CodeCoverage|coverlet|ChromeDriver' . 2>/dev/null || true
find . \( -name .git -o -name node_modules \) -prune -o -name dotnet-tools.json -print | while IFS= read -r f; do echo "== $f"; cat "$f"; done
```

| Package or feature | On an arm64 build host | Evidence |
|---|---|---|
| Grpc.Tools | `tools/linux_arm64` from 2.37.0 | `probe Grpc.Tools 2.36.4`: `CHECK ELF files outside runtimes/ in Grpc.Tools/2.36.4 are i386, x86-64 only ..., e.g. tools/linux_x64/grpc_csharp_plugin, tools/linux_x64/protoc, ...`; 2.37.0: `OK ... aarch64, i386, x86-64` |
| Native AOT (`PublishAot`) | restore adds `runtime.<rid>.Microsoft.DotNet.ILCompiler` for each RID; the compiler and linker run on the build host | publishing linux-arm64 from x64 without a cross toolchain failed: `gcc : error : unrecognized command-line option ‘--target=aarch64-linux-gnu’`. Build on arm64 (Phase 2.4) |
| Microsoft.CodeCoverage (via Microsoft.NET.Test.Sdk) | no arm64 build of its dynamic instrumentation engine | dynamic instrumentation runs on Linux x64 only, static instrumentation everywhere ([dotnet-coverage](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-coverage)); confirm coverage collection on arm64 in Phase 3.2 |
| Selenium.WebDriver.ChromeDriver | none | an x86-64 Linux driver in every release from 2.29.0 on, none in earlier releases, no aarch64 build in any |

Match the RID to the *target*, not the developer machine. **Graviton is Linux, so `linux-arm64` (and `linux-musl-arm64` for Alpine) decides the verdict.** `osx-arm64` and `win-arm64` matter only for local builds on Apple silicon or Windows on Arm, and are never a Graviton blocker.

## 1.4 Architecture-Specific Code Detection

> **Output: `graviton-validation/04-code-scan-findings.md`** and **`graviton-validation/raw/ca1416.txt`**

Scan the source tree for architecture-sensitive patterns. Scan from the root (`.`), not from one project folder, and include C#, VB and F# sources:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
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

In the output:
- A test that asserts `RuntimeInformation.RuntimeIdentifier` equals `linux-x64` fails on arm64 by construction. Fix the test, not the code.
- An x86 intrinsic called with no `IsSupported` check before it, such as `Avx2.Add`, throws `System.PlatformNotSupportedException: Operation is not supported on this platform.` on arm64, and the compiler gives no warning. A guarded call is not reported; its fallback runs on arm64 (RECOMMENDED: a `Vector128` path).
- Project settings are evaluated values, for example `./src/Fixture.Api/Fixture.Api.csproj: PlatformTarget=x64, RuntimeIdentifier=linux-x64, RuntimeIdentifiers=linux-x64`.

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

CA1416 does not report three cases:
- P/Invoke into Windows DLLs, such as the `kernel32.dll` import in §1.2.2;
- projects whose target framework ends in `-windows`, which declare Windows support;
- .NET Framework projects, which do not build on Linux (`MSB3644: The reference assemblies for .NETFramework,Version=v4.8 were not found.`).

So also search the text:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
# Windows paths and separators, Windows time zone IDs, Windows-only APIs (also in code the analyzer does not check)
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' --include='*.json' --include='*.config' \
  '[A-Za-z]:\\|"[^"]*\\\\[^"]*"|Standard Time"|Microsoft\.Win32|Registry\.|EventLog|ProtectedData|WindowsIdentity|ServiceBase|AddWindowsService|System\.Drawing|System\.Management|System\.DirectoryServices' . 2>/dev/null || true
# .NET Framework technologies without a Linux path, or with a different one on modern .NET
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' \
  'System\.Web\.(UI|Http|Mvc)|System\.ServiceModel|System\.EnterpriseServices|System\.Runtime\.Remoting|AppDomain\.CreateDomain|BinaryFormatter|System\.Workflow|System\.Activities' . 2>/dev/null || true
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name graviton-validation \) -prune -o -type f \( -name '*.aspx' -o -name '*.ascx' -o -name '*.asmx' -o -name '*.svc' -o -name 'Global.asax' -o -name '*.xaml' \) -print
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name graviton-validation \) -prune -o -type f -iname 'web.config' -print | while IFS= read -r f; do
  grep -nE '<authentication mode="Windows"|<system\.serviceModel>|<httpModules>|<httpHandlers>|targetFramework=' "$f" | sed "s#^#$f:#"; done
# Deployment descriptors, scripts and CI that pin x64, Windows or one architecture, and the resources
# whose architecture can be absent (functions, task definitions, node groups)
DP='--platform[= ]linux/amd64|(-r|--runtime) (linux|win)-x64|(-a|--arch) (x64|amd64)|nanoserver|servercore|kubernetes\.io/arch: *amd64|runs-on: |x86_64|-amd64([^A-Za-z0-9]|$)|(^|[^A-Za-z0-9])amd64/|uname -m|docker build |--locked-mode|AWS::(Lambda::Function|Serverless::Function|ECS::TaskDefinition|EKS::Nodegroup)|requires_?[Cc]ompatibilities|resource "aws_(lambda_function|ecs_task_definition|eks_node_group)"'
grep -rnE "${EX[@]}" --include='*.y*ml' --include='*.json' --include='*.tf' --include='*.sh' --include='*.ps1' --include='*.template' -- "$DP" . 2>/dev/null || true
if [ -f graviton-validation/raw/dockerfiles.txt ]; then   # the Dockerfiles of §1.1, under any name
  while IFS= read -r f; do grep -nE -- "$DP" "$f" | sed "s#^#$f:#"; done < graviton-validation/raw/dockerfiles.txt
else echo "CHECK: run the Determine Deployment Type block (§1.1) first: it writes graviton-validation/raw/dockerfiles.txt"; fi
# CDK apps: the constructs that take an architecture, and the settings, in each folder with a cdk.json
# (a construct that sets none gets x86_64)
find . \( -name .git -o -name .venv -o -name bin -o -name obj -o -name node_modules -o -name cdk.out \) -prune -o -name cdk.json -print |
  while IFS= read -r c; do grep -rnE --exclude-dir=node_modules --exclude-dir=cdk.out --exclude-dir=bin --exclude-dir=obj --exclude-dir=.venv --include='*.py' --include='*.ts' --include='*.js' \
    --include='*.java' --include='*.cs' --include='*.go' 'Architecture[._](X86_64|ARM_64)|CpuArchitecture[._](X86_64|ARM64)|AmazonLinuxCpuType[._]|MachineImage[._]|NodegroupAmiType[._]|InstanceType(\(|[._][Oo]f\()|InstanceClass[._]|(^|[^A-Za-z0-9_])(New)?(Function|DockerImageFunction|NodejsFunction|PythonFunction|GoFunction|FargateTaskDefinition|Nodegroup|Cluster)(\(|\.Builder)|[Aa]dd_?[Nn]odegroup_?[Cc]apacity' "$(dirname "$c")"; done | sort -u
# System calls made by number: the numbers differ (x86-64's 186 is gettid, aarch64's is 178, and 186 there
# is msgget), and open, fork, pipe, dup2 and poll have no aarch64 number at all (openat, clone, pipe2, dup3
# and ppoll do). Use the libc function or the target's SYS_ constant instead of the number.
grep -rnE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' -- \
  'syscall\([[:space:]]*(0x[0-9a-fA-F]+|[0-9]+)' . 2>/dev/null || true
# Types and build flags whose results differ by architecture (checked in Phase 3)
grep -rnE "${EX[@]}" --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' \
  --include=CMakeLists.txt --include=Makefile --include='*.mk' -- 'long double|__float128|longdouble|float128|float96|complex256|-ffast-math|-Ofast|-funsafe-math' . 2>/dev/null || true
# x86-only compiler flags and intrinsics in native C and C++ sources the repository builds
grep -rnE "${EX[@]}" --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' \
  --include=CMakeLists.txt --include=Makefile --include='*.mk' -- '-m(avx|sse|fma|bmi|popcnt|pclmul|aes|crc32|f16c|lzcnt)|-march=|-mtune=|[a-z0-9]+intrin\.h|cpuid\.h|__builtin_ia32_|__cpuid|__rdtsc|__x86_64__|_M_X64|__SSE|__AVX|__m(128|256|512)|_mm[0-9]*_' . 2>/dev/null || true
```

What each Windows or .NET Framework hit means on Linux, with the replacement, is in [windows-to-linux.md](windows-to-linux.md). The descriptor fixes are in Phase 2.4.

A setting that is absent also picks an architecture. A Lambda function that names none runs on x86_64, the default of the Lambda API, Terraform and the CDK, whose templates then carry no `Architectures`; a Fargate task definition without `cpuArchitecture` runs `X86_64`, and an ECS task on EC2 capacity without it goes where its capacity providers place it; an EKS managed node group with no instance type launches `t3.medium`, and the CDK's `aws-eks` `Cluster` without `defaultCapacityInstance` adds `m5.large` (x86) nodes, two unless `defaultCapacity` sets another count; the CDK's `MachineImage.latestAmazonLinux2023()` without `cpuType` picks the x86_64 AMI. So each function, task definition and node group the resource lines list needs an arm64 setting (Phase 2.4), whether or not an architecture line matched it. An image can also name one architecture: through its tag (`mcr.microsoft.com/dotnet/aspnet:8.0-bookworm-slim-amd64`, `public.ecr.aws/lambda/dotnet:8-x86_64`). Native C or C++ sources the repository builds need an Arm path for any x86 intrinsics they use: `sse2neon.h` ([sse2neon](https://github.com/DLTcollab/sse2neon)) implements the SSE to SSE4.2 and AES intrinsics with NEON, but no AVX (`_mm256_*`); port what it does not cover, and the hot paths found by profiling on Graviton, to NEON intrinsics. `long double` and fast-math flags change results between x86 and Graviton without an error: check them in Phase 3 (Results That Change Without Failing).

Every image the project builds from, tests with or deploys has to list `linux/arm64`, including images a library starts at run time: a test that calls `WithImage("mysql:5.7")` starts `mysql:5.7`, which has no arm64 build. List the images and read each one's platforms from its registry, without pulling it:

```bash
EX=(--exclude-dir=.git --exclude-dir=bin --exclude-dir=obj --exclude-dir=node_modules --exclude-dir=graviton-validation --exclude-dir=.venv)
mkdir -p graviton-validation/raw
# Image references: FROM lines of the Dockerfiles in raw/dockerfiles.txt (§1.1; not stage names), image: keys in
# YAML and JSON, image names in test code. A reference built from a variable is left out: resolve it by hand.
{ if [ -f graviton-validation/raw/dockerfiles.txt ]; then
    while IFS= read -r f; do
      awk 'toupper($1) == "FROM" { i = ($2 ~ /^--platform=/) ? 3 : 2; if (!($i in s)) print $i
             for (k = i + 1; k < NF; k++) if (toupper($k) == "AS") s[$(k + 1)] = 1 }' "$f"
    done < graviton-validation/raw/dockerfiles.txt
  else echo "CHECK: run the Determine Deployment Type block (§1.1) first: it writes graviton-validation/raw/dockerfiles.txt" >&2; fi
  grep -rhoiE "${EX[@]}" --include='*.y*ml' --include='*.json' \
    '"?image(uri)?"?[[:space:]]*:[[:space:]]*"?[a-z0-9][^"[:space:],}]*' . |
    sed -E 's/^"?[Ii][Mm][Aa][Gg][Ee]([Uu][Rr][Ii])?"?[[:space:]]*:[[:space:]]*"?//'
  grep -rhoE "${EX[@]}" --include='*.cs' --include='*.vb' --include='*.fs' 'WithImage\("[^"]+"' . |
    sed -E 's/.*\("//; s/"$//'
} | grep -vE '\$|^scratch$' | sort -u > graviton-validation/raw/images.txt
# Platforms per image, from its registry (docker CLI). Without docker, or a login a private registry needs, the line is CHECK.
while IFS= read -r img; do
  if ! out=$(docker manifest inspect -v "$img" 2>&1); then printf 'CHECK   %s: %s\n' "$img" "$(printf '%s\n' "$out" | grep -v '^errors:$' | head -n 1)"
  elif printf '%s' "$out" | grep -q '"architecture": "arm64"'; then printf 'OK      %s\n' "$img"
  else printf 'FINDING %s: no linux/arm64 build\n' "$img"; fi
done < graviton-validation/raw/images.txt
```

`docker manifest inspect -v` prints every platform of a multi-architecture image and the one platform of a single-architecture image. A FINDING is fixed in Phase 2.4. On an ARM64 host a list without arm64 stops the pull (`no matching manifest for linux/arm64/v8 in the manifest list entries`), while a single amd64 manifest is pulled and its container stops with `exec format error` (`--platform linux/arm64` stops that pull: `was found but does not match the specified platform: wanted linux/arm64, actual: linux/amd64`).

## 1.5 .NET Version Compatibility Check

> **Output: `graviton-validation/01-project-assessment.md`** (.NET Environment section)

```bash
# Target frameworks in use (from 1.1) and the SDK the repository pins
grep -oE 'TargetFrameworks?=[^,]+|TargetFrameworkVersion=[^,]+' graviton-validation/raw/project-properties.txt | sort | uniq -c
find . \( -name .git -o -name node_modules \) -prune -o -name global.json -print | while IFS= read -r f; do echo "== $f"; cat "$f"; done
# Support phase and end of support of every .NET release (Microsoft release metadata)
curl -fsSL https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json | python3 -c 'import json, sys
for r in json.load(sys.stdin)["releases-index"]:
    print("%-5s %-3s %-12s end of support %-10s latest runtime %s" % (r["channel-version"], r.get("release-type", "-"), r["support-phase"], r.get("eol-date") or "-", r["latest-runtime"]))'
```

1. Document the target framework of every project, the SDK (`global.json`), the runtime image tags, and the Lambda runtimes (§1.1).
2. **Modern .NET runs on Linux Arm64:**
   - Microsoft's supported-OS lists for .NET 8 and 10 include Arm64 for Linux distributions such as Alpine, Azure Linux, CentOS Stream and Debian ([8.0](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md), [10.0](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)).
   - .NET 10 needs glibc 2.27, which Amazon Linux 2 (glibc 2.26) does not have; .NET 8 needs glibc 2.23. On Graviton4, in an `amazonlinux:2` container, .NET 8.0.31 ran a console app and .NET 10.0.12 stopped at ``Failed to load .../libcoreclr.so, error: /lib64/libm.so.6: version `GLIBC_2.27' not found``; .NET 10.0.12 ran on AlmaLinux 8 (glibc 2.28).
   - The .NET Framework does not support Linux, and Windows is not supported on Graviton.
3. **Support:** the block above prints each release's type (`lts` or `sts`), support phase and end of support from Microsoft's release index. Use the newest `lts` release in `active` support for new Graviton workloads, or an earlier release in `active` or `maintenance` support when the project needs it; a release in `eol` is out of support.
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
