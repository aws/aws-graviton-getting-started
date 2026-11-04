# NuGet Native Asset Verification

> The central check of this skill. For every NuGet package the application resolves, it asks one question: does the target runtime identifier (RID) get a native file that runs on Graviton? Read this before Phase 1.2 and Phase 1.3. The commands call the check program, `scripts/dotnet_graviton_check.py` (Documentation Setup in SKILL.md records its path). It needs Python 3.6 or later; `assets`, `probe` and `config` also need the .NET SDK, and `--help` prints its commands and rules.

## Contents

- 1. Managed Code, Native Code, and What Decides Each
- 2. How the SDK Selects Native Files
- 3. The Per-RID Check: Projects That Still Use packages.config
- 4. Package Shapes That Defeat Name-Based Checks
- 5. Finding the Lowest Version That Works
- 6. Target OS: libc, glibc Version, Page Size
- 7. Scanning Build and Publish Outputs
- 8. Lock Files
- 9. Private Feeds and Mirrors
- 10. Traps

## 1. Managed Code, Native Code, and What Decides Each

- **Managed assemblies** (IL) built as `AnyCPU` run on Graviton unchanged; the runtime compiles them for arm64 when they load.
- **Assemblies built for one architecture do not load on arm64.** An assembly built with `<PlatformTarget>x64</PlatformTarget>` (PE machine `0x8664`) fails, and the error names the assembly as missing: `FileNotFoundException: Could not load file or assembly 'Fixture.Legacy, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null'` (executed).
- **x86 assemblies** (`<PlatformTarget>x86</PlatformTarget>`) fail the same way on Linux x64 as well. When an AnyCPU project referenced one, the SDK printed no warning (executed with SDK 8.0.425).
- **Prefer32Bit:** `<Prefer32Bit>` has no effect on modern .NET (`warning NETSDK1189: Prefer32Bit is not supported and has no effect for netcoreapp target.`). An assembly whose header is marked 32-bit preferred, the AnyCPU variant that .NET Framework projects often produce, loaded in an arm64 process (executed under emulation).
- **Native code** depends on the CPU architecture and on the operating system: the ELF machine (`aarch64`), the C library (glibc or musl), the glibc version it was linked against, and, on kernels with 64KB pages, the alignment of its loadable segments. It reaches an application in four ways:
  1. files under `runtimes/<rid>/native/` in NuGet packages, which NuGet selects per RID ("NuGet will select native assets from the runtimes/{rid}/native/ directory", [Microsoft Learn](https://learn.microsoft.com/en-us/nuget/create-packages/native-files-in-net-packages));
  2. executables or libraries a package keeps elsewhere (`tools/`, `build/`, `driver/`, `manager/`) and copies to the output or runs during the build;
  3. files committed to the repository;
  4. files downloaded at run time.
- Decide every native file's architecture from its content (the ELF header), never from its name, extension or folder. §4 shows packages where each of those misleads.

## 2. How the SDK Selects Native Files

- Restore resolves assets for each RID in `<RuntimeIdentifiers>` (or `<RuntimeIdentifier>`) and records them in the project's `project.assets.json`, under targets such as `net8.0/linux-arm64`. The file is in `obj/` by default, in `artifacts/obj/<project>/` with `UseArtifactsOutput`, and wherever `BaseIntermediateOutputPath` points; MSBuild's `ProjectAssetsFile` property gives the path. A build or publish with `-r` uses that RID. A build without a RID copies the `runtimes/<rid>/` folders of every RID, and the host picks one at run time from the `.deps.json`.
- Each RID falls back along the portable RID graph that ships with the SDK (`PortableRuntimeIdentifierGraph.json`; identical in SDK 8.0.425 and 10.0.401):
  - `linux-arm64` → `linux` → `unix-arm64` → `unix` → `any`
  - `linux-musl-arm64` → `linux-musl` → `linux-arm64` → `linux` → `unix-arm64` → `unix` → `any`

  Two consequences: a file in a generic `runtimes/linux/native/` folder is selected for every Linux RID, whatever its architecture; and a package without `linux-musl-arm64` files gives Alpine its glibc `linux-arm64` build.
- "Starting with .NET 8, the default behavior of the .NET SDK and runtime is to only consider non-version-specific and non-distro-specific RIDs" ([RID catalog](https://learn.microsoft.com/en-us/dotnet/core/rid-catalog)), so assets under RIDs such as `debian-arm64` or `ubuntu.16.04-arm64` are ignored.
- The SDK's warning for such assets, NETSDK1206, appeared only in builds without a RID.
- Folder names that are not RIDs are never selected, and NETSDK1206 does not mention them. Microsoft.ML.OnnxRuntime 1.10.0 keeps its aarch64 build in `runtimes/linux-aarch64/native/`; the warning named only its `osx.10.14-arm64` and `osx.10.14-x64` folders.
- **A missing native file is not a build error.** `dotnet publish -r linux-arm64` exits 0 when a package has no arm64 file, and the output can still hold an x86-64 library; the application fails only at run time, with `DllNotFoundException`. Never accept a publish exit code as evidence.

## 3. The Per-RID Check

Run from the repository root (the folder that holds the solution or the project files):

```bash
GV_CHECK=$(sed -n 's/^GV_DOTNET_CHECK=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the path Documentation Setup in SKILL.md recorded
[ -f "$GV_CHECK" ] || echo "ERROR: run the Documentation Setup block in SKILL.md first: it records the path of scripts/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one run per target that §6 recorded; with none, one run named target
GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
GV_T=(); case $GV_TDIR in "") ;; glibc=*) GV_T=(--glibc "${GV_TDIR#glibc=}");; *) GV_T=(--target-root "$GV_TDIR");; esac; GV_T+=(${GV_PAGE:+--page-size} ${GV_PAGE:+"$GV_PAGE"})
python3 "$GV_CHECK" assets --source-rid linux-x64 "${GV_T[@]}" > "graviton-validation/raw/native-assets-$GV_TAG.txt"; rc=$?   # one file per target, named for it
cat "graviton-validation/raw/native-assets-$GV_TAG.txt"; echo "exit status $rc (0 no findings, 1 findings, 2 restore failed or wrote no project.assets.json)"
done
```

What `assets` does:
- **Works on a copy.** It copies the tree to a temporary folder (without `bin`, `obj`, `.git`, `.vs`, `node_modules`, `graviton-validation`), restores every solution at the root (or every project if there is none) for the source and target RIDs, and deletes the copy afterwards. The repository is not touched. A restore with extra RIDs in the repository itself rewrites its tracked `packages.lock.json` files (§8).
- **Reads the assets files of its own restore.** Before restoring, it deletes every `project.assets.json` and `project.nuget.cache` in the copy, then reads each `project.assets.json` the restore writes, in any folder (`obj/`, `artifacts/obj/<project>/`, a custom `BaseIntermediateOutputPath`), so a file left by an earlier restore or a removed project is never read.
- **Runs the repository's MSBuild files.** The restore imports the copy's `Directory.Build.props` and `Directory.Build.targets`, reads its `Directory.Build.rsp`, and runs any target hooked to restore. The start of [Phase 1](phase1-static-analysis.md) lists the steps that do this and how to list such code first.
- **Reports every package with native files for these RIDs**, after a `target:` line that names the target, one line per target RID and file:
  - `OK` when the file is an aarch64 build for the target's libc, with the highest `GLIBC_` and `GLIBCXX_` versions it needs, its smallest LOAD alignment (and its `vaddr-offset align` when that is below `0x10000`, §6), and after `needs` the libraries it needs. Each of those comes from the package or must come from the target image (an OS package to install when the image lacks it);
  - `FINDING` when the target RID gets no file, or gets one that is not an aarch64 build, is an Android build, is built for the other libc, needs a newer glibc or libstdc++ than the target's, is linked for a smaller page size than the target's (§6), or is a binary for another system (Windows, macOS, FreeBSD). With the image's files, a glibc, libstdc++ or libgcc_s library the file needs that the image does not have is also a `FINDING`, and so is a glibc symbol it imports that nothing in a musl image provides. When the x86-64 build of the file needs the same version or library, the line says so: x86-64 hosts with this OS fail as well.
  - `CHECK` when a glibc build for a musl RID needs no glibc library musl's loader lacks, judged without the image's files (with `--target-root`, the check resolves the file's glibc imports against the image's libraries, and a symbol the image does not define is a `FINDING`: the load passes, and a call that reaches that symbol stops the process). A file that needs another library the image does not have, one the scanned files do not ship, is also a `CHECK`: the image the project deploys may install it.
  - With `--target-root`, the target line ends with `read from <folder> (<os-release name>)`, and a version finding names the library: `needs GLIBC_2.35 from libm.so.6; the target's libm.so.6 defines up to GLIBC_2.32`. On a musl image with gcompat, a symbol that only gcompat's library defines is a `CHECK`: musl's loader gives it to the file only when that library is preloaded (`LD_PRELOAD`).
  - Under each `FINDING` and `CHECK`, an indented `via` line with the shortest reference chain from a project to the package, so the direct reference to change is named.
- **Accepts packages that ship both C libraries in one RID folder.** librdkafka.redist 2.15.1 has `librdkafka.so` (glibc) and `alpine-librdkafka.so` (musl) in `runtimes/linux-arm64/native/` and loads one of them at run time. When the target's C library has a build there, the other build is a `NOTE`, not a `FINDING`; Phase 3 confirms which one loads.
- **Judges RID-specific packages as a family.** When a package has no file for the target but another package of the same family does, the line is `OK`. Families are names that differ only by a RID or architecture part: `NetVips.Native.linux-x64` and `NetVips.Native.linux-arm64`, `runtime.linux-x64.*` and `runtime.linux-arm64.*`, `Magick.NET-Q16-x64` and `Magick.NET-Q16-arm64`.
- **Reads static libraries** (ar archives, used when linking with Native AOT) by the ELF headers of their object files: aarch64 code is `OK`, x86-only code a `CHECK` (a Native AOT link fails), no ELF member a `NOTE`. SQLitePCLRaw.lib.e_sqlite3 3.53.3 ships `libe_sqlite3.a` beside `libe_sqlite3.so`.
- **Lists ELF files that packages keep outside `runtimes/`**, per family:
  - `OK` when an aarch64 build is among them;
  - `CHECK` when they are x86-only. They fail only if a build target copies them to the output or a tool runs them, so decide from how the project uses the package (§4).
- **Prints NuGet audit warnings** (NU1901 to NU1904) from its restores as `NOTE NuGet audit:` lines, once each. They are security findings, out of scope unless an ARM64 change introduces them (§5).
- **Flags `packages.config` projects.** Their packages are not restored by PackageReference, so `assets` prints a `CHECK` line that names the `config` command for each such file (below).
- **Exit status:** 0 no findings (`CHECK` lines may remain), 1 findings, 2 the folder is missing, the restore failed or wrote no `project.assets.json` inside the copy (an intermediate path outside the repository). A restore whose projects resolve no NuGet package prints `restored 1 project(s); none of them resolves a NuGet package` and exits 0.
- **Options:**
  - `--target-rid linux-musl-arm64` adds Alpine; the option can be repeated;
  - `--glibc 2.34` reports natives that need a newer glibc than the target's (§6);
  - `--glibcxx 3.4.30` reports natives that need a newer libstdc++ than the target's (§6); it applies to glibc RIDs only;
  - `--target-root FOLDER` judges against a target image's files (§6) in place of `--glibc` and `--glibcxx`; the image's C library sets the RID;
  - `--page-size 65536` reports natives linked for a smaller page size than the target's, by the rule of the target's loader (§6); without it, one `NOTE` lists the aarch64 natives linked for 4 KB pages only;
  - `--tree FILE` also writes every resolved package, per project and target framework, with its reference chain (JSON).

Output on the Linux test solution (`linux-x64` to `linux-arm64`; long lines shortened):

```
restore Fixture.sln for linux-x64;linux-arm64 (scratch copy)
NOTE NuGet audit: warning NU1903: Package 'Newtonsoft.Json' 12.0.3 has a known high severity vulnerability, https://github.com/advisories/GHSA-5crp-9r3c-p9vr
target: glibc (linux-arm64), glibc version not given, page size not given
FINDING no linux-arm64 native: Microsoft.ML.OnnxRuntime/1.10.0 (linux-x64 has 1; runtimes/ folders: android, ios, linux-aarch64, linux-x64, osx.10.14-arm64, osx.10.14-x64, win-arm, win-arm64, win-x64, win-x86); used by src/Fixture.Scoring, ...
  via src/Fixture.Scoring (direct reference)
FINDING linux-arm64 native runtimes/linux/native/selenium-manager of Selenium.WebDriver/4.48.0 is x86-64; used by tests/Fixture.UiTests
  via tests/Fixture.UiTests (direct reference)
FINDING no linux-arm64 native: SkiaSharp.NativeAssets.Linux/1.68.3 (linux-x64 has 1; runtimes/ folders: linux-x64); used by src/Fixture.Api, ...
  via src/Fixture.Core (direct reference)
OK linux-arm64 SQLitePCLRaw.lib.e_sqlite3/2.1.12: runtimes/linux-arm64/native/libe_sqlite3.so (glibc GLIBC_2.34 align 0x10000; needs libc.so.6 ld-linux-aarch64.so.1)
FINDING no linux-arm64 native: Stub.System.Data.SQLite.Core.NetStandard/1.0.119 (linux-x64 has 1; runtimes/ folders: linux-x64, osx-x64, win-x64, win-x86); used by src/Fixture.Api, ...
  via src/Fixture.Core > System.Data.SQLite.Core 1.0.119 > Stub.System.Data.SQLite.Core.NetStandard 1.0.119
CHECK ELF files outside runtimes/ in Microsoft.CodeCoverage/17.11.1 are x86-64 only (they fail only if a build target copies them to the output or a tool runs them), e.g. build/netstandard2.0/InstrumentationEngine/alpine/x64/libCoverageInstrumentationMethod.so, ...
  via tests/Fixture.Tests > Microsoft.NET.Test.Sdk 17.11.1 > Microsoft.CodeCoverage 17.11.1
OK ELF files outside runtimes/ in runtime.linux-arm64.Microsoft.DotNet.ILCompiler/8.0.31, runtime.linux-x64.Microsoft.DotNet.ILCompiler/8.0.31: aarch64, x86-64
packages: 40; with native files for these RIDs: 5; natives for other platforms only: 1; managed only: 34
findings: 4, checks: 1
```

The `via` line gives one chain. In a restored repository, `dotnet nuget why <project> <package>` prints every path, and works on SDK 8.0.425 and 10.0.401. `dotnet list <project> package --include-transitive --format json` lists every resolved package.

### Projects That Still Use packages.config

.NET Framework projects with `packages.config` cannot be restored for Linux RIDs. `config` probes every package the file lists, one at a time, in a scratch `net8.0` project (§5), which shows early which native packages have no Linux arm64 build at all:

```bash
GV_CHECK=$(sed -n 's/^GV_DOTNET_CHECK=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the path Documentation Setup in SKILL.md recorded
[ -f "$GV_CHECK" ] || echo "ERROR: run the Documentation Setup block in SKILL.md first: it records the path of scripts/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" config path/to/packages.config > graviton-validation/raw/native-assets-packages-config.txt; rc=$?
cat graviton-validation/raw/native-assets-packages-config.txt; echo "exit status $rc"
```

The full check runs again with `assets` after the project moves to modern .NET.

## 4. Package Shapes That Defeat Name-Based Checks

| Shape | Example (verified by content) | Result on arm64 |
|---|---|---|
| x64-only native | SkiaSharp.NativeAssets.Linux 1.68.3: `runtimes/linux-x64` only | `DllNotFoundException: Unable to load shared library 'libSkiaSharp' or one of its dependencies` |
| arm64 build in a folder that is not a RID | Microsoft.ML.OnnxRuntime 1.10.0: `runtimes/linux-aarch64` | never selected; `DllNotFoundException: Unable to load shared library 'onnxruntime' or one of its dependencies` |
| one build in a generic `linux` folder | Selenium.WebDriver 4.48.0: `runtimes/linux/native/selenium-manager` is x86-64 | selected for linux-arm64. In an arm64 container on an x86 host it ran, because the host CPU executes x86-64 files, so emulated tests pass it |
| arm64 build only under distribution RIDs | LibGit2Sharp.NativeBinaries 2.0.306: `debian-arm64`, `ubuntu.16.04-arm64` | ignored by .NET 8 and later |
| Linux native named `.dll` | Stub.System.Data.SQLite.Core.NetStandard 1.0.119: `runtimes/linux-x64/native/SQLite.Interop.dll` is an x86-64 ELF file | no linux-arm64 file in any release; `DllNotFoundException: Unable to load shared library 'SQLite.Interop.dll' or one of its dependencies` |
| one package per RID | NetVips.Native.linux-x64 (x64 only) and NetVips.Native.linux-arm64 (from 8.10.0); Magick.NET-Q16-x64 (no linux-arm64 in any release), Magick.NET-Q16-arm64 and Magick.NET-Q16-AnyCPU (linux-arm64 from 11.0.0) | the x64 package never works on arm64. The NetVips.Native meta-package resolves the per-RID packages, including linux-arm64 |
| glibc build given to a musl target | SkiaSharp.NativeAssets.Linux and Microsoft.ML.OnnxRuntime releases without `linux-musl-arm64` | the glibc `linux-arm64` file (§2): `FINDING` if it needs a library musl's loader lacks, such as `ld-linux-aarch64.so.1`, else `CHECK` (§3). x86-64 Alpine can get a `linux-musl-x64` file instead, so it is no guide |
| executables or libraries outside `runtimes/` | Selenium.WebDriver.ChromeDriver: every release from 2.29.0 on carries an x86-64 Linux driver (`driver/linux64/chromedriver`), copied to the output; earlier releases carry none, and no release has an aarch64 build; Microsoft.CodeCoverage (pulled in by Microsoft.NET.Test.Sdk): x86-64 libraries in `build/` in every release from 16.10.0 to 18.10.1; Grpc.Tools: `tools/linux_arm64` from 2.37.0 | the per-RID comparison does not see them, so the check lists them as `CHECK`. ChromeDriver's file is run by UI tests. The CodeCoverage files are the dynamic instrumentation engine: Microsoft documents dynamic instrumentation on Linux for x64 only and static instrumentation on all platforms ([dotnet-coverage](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-coverage)), so confirm coverage collection on arm64 in Phase 3.2 |
| natives in a transitive package | Microsoft.Data.Sqlite → SQLitePCLRaw.lib.e_sqlite3; Confluent.Kafka → librdkafka.redist; LibGit2Sharp → LibGit2Sharp.NativeBinaries; NetVips.Native → NetVips.Native.linux-arm64 | the direct reference looks managed; check the resolved tree |

## 5. Finding the Lowest Version That Works

`probe` restores one package version in a scratch project, exactly as a build would, and runs the same report. It uses the `NuGet.config` in the current directory, if there is one. `--framework` sets the scratch project's target framework (default `net8.0`):

```bash
GV_CHECK=$(sed -n 's/^GV_DOTNET_CHECK=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the path Documentation Setup in SKILL.md recorded
[ -f "$GV_CHECK" ] || echo "ERROR: run the Documentation Setup block in SKILL.md first: it records the path of scripts/dotnet_graviton_check.py"
python3 "$GV_CHECK" probe SkiaSharp.NativeAssets.Linux 2.80.0
# Versions published on nuget.org, oldest first (package ID in lower case; other feeds have their own API):
curl -fsSL https://api.nuget.org/v3-flatcontainer/skiasharp.nativeassets.linux/index.json \
  | python3 -c 'import json,sys; print(" ".join(v for v in json.load(sys.stdin)["versions"] if "-" not in v))'
```

Probe the candidates upward from the version in use and stop at the first that reports no findings and no `CHECK` lines. The minimal fix is that version, not the latest one. For example:
- Confluent.Kafka 1.5.3 resolves librdkafka.redist 1.5.3, which has no linux-arm64 file. The next stable release, 1.6.1, resolves librdkafka.redist 1.6.1: OK, and it needs GLIBC_2.25.
- LibGit2Sharp 0.26.2 resolves LibGit2Sharp.NativeBinaries 2.0.306 (finding); 0.27.0 resolves 2.0.319 (OK).

Floors found by reading every stable release on nuget.org:

| Package | First linux-arm64 | First linux-musl-arm64 | Notes |
|---|---|---|---|
| SkiaSharp.NativeAssets.Linux | 2.80.0 | 3.119.0 | the 3.119.0 Linux builds need GLIBC_2.27; 2.80.0 needs 2.17 |
| Magick.NET-Q16-AnyCPU, Magick.NET-Q16-arm64 | 11.0.0 | none up to 14.17.2 | the 14.17.2 arm64 build needs GLIBC_2.29 |
| NetVips.Native.linux-arm64 | 8.10.0 | NetVips.Native.linux-musl-arm64, from 8.10.6 | |
| Grpc.Core | 2.37.0 | none | |
| Grpc.Tools (build host) | 2.37.0 | none | `tools/linux_arm64` |
| librdkafka.redist | 1.6.0 | none | Confluent.Kafka 1.6.1 is the first stable release whose librdkafka.redist dependency (1.6.1) has one; 1.6.2 also depends on 1.6.1 |
| Microsoft.ML.OnnxRuntime | 1.11.0 | none up to 1.30.0 | |
| Microsoft.ML | 1.6.0 | none | |
| LibGit2Sharp.NativeBinaries | 2.0.312 | 2.0.315 | LibGit2Sharp 0.27.0 is the first stable release that depends on one (2.0.319); it targets net472 and net6.0, while 0.26.2 targets net46 and netstandard2.0 |
| Selenium.WebDriver | 4.49.0 | uses the linux-arm64 build, which is statically linked | |
| SQLitePCLRaw.lib.e_sqlite3 | 2.0.0 | 2.1.0 | see below |

**The floor can carry an advisory that the current version does not have.** NuGet audit reported `warning NU1903: Package 'SkiaSharp' 2.80.0 has a known high severity vulnerability, https://github.com/advisories/GHSA-j7hp-h8jx-5ppr` for SkiaSharp 2.80.0 to 2.88.5, and nothing for 1.68.3 or 2.88.6. SkiaSharp.NativeAssets.Linux 2.88.6 also probes clean for linux-arm64 (GLIBC_2.17; no linux-musl-arm64). `probe` prints these warnings as `NOTE NuGet audit:` lines for the probed package and for its dependencies, each naming its package: its scratch project sets `NuGetAuditMode` to `all`, which NuGet applies by default only to projects that target `net10.0` or later. `probe SkiaSharp.NativeAssets.Linux 2.80.0` printed the NU1903 of its dependency SkiaSharp 2.80.0 above, with `--framework net8.0` and with `net10.0`. When the arm64 floor brings a new NU1901 to NU1904 warning, present the floor and the lowest version without the warning as one user decision (Phase 2.2); the skill does not fix advisories that the current version already has ([agent-scope-boundaries.md](agent-scope-boundaries.md)).

Floors are not always monotonic. The arm64 glibc build of SQLitePCLRaw.lib.e_sqlite3, measured in all 24 stable releases, needs:
- GLIBC_2.17 in 2.0.0 to 2.1.4, except 2.0.5, which needs GLIBC_2.28;
- GLIBC_2.28 in 2.1.5 to 2.1.11;
- GLIBC_2.34 from 2.1.12 (through 3.53.3).

Microsoft.Data.Sqlite 8.0.31 brings in 2.1.12, which needs a newer glibc than Amazon Linux 2 has (§6).

No linux-arm64 build in any stable release, so a substitute is a user decision; the Recommendation is the first substitute named here, and for a package with none named, change nothing and list it:
- System.Data.SQLite.Core and Stub.System.Data.SQLite.Core.NetStandard (up to 1.0.119; use Microsoft.Data.Sqlite);
- Microsoft.ML.Mkl.Redist (up to 5.0.0);
- Magick.NET-Q16-x64 (up to 14.17.2; use Magick.NET-Q16-AnyCPU, or Magick.NET-Q16-arm64 for arm64 only);
- NetVips.Native.linux-x64 (use NetVips.Native, or NetVips.Native.linux-arm64 for arm64 only);
- Selenium.WebDriver.ChromeDriver (up to 154.0.8037.9200).

## 6. Target OS: libc, glibc Version, Page Size

- **.NET's own minimum** ([supported-os.md for 8.0](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md), [for 10.0](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)): .NET 8 needs glibc 2.23 or musl 1.2.2; .NET 10 needs glibc 2.27 (Arm64 and x64) or musl 1.2.3. Amazon Linux 2 has glibc 2.26, below the .NET 10 minimum: in an `amazonlinux:2` arm64 container on Graviton4, .NET 10.0.12 stopped at ``/lib64/libm.so.6: version `GLIBC_2.27' not found`` while .NET 8.0.31 ran.
- **The target image's libc, glibc versions and libstdc++.** For each image, copy its loaders and libraries into a folder with this block, which never starts the container. The check reads the C library from that folder, and passes a file only when the image has every library it needs from glibc, libstdc++ and libgcc_s and those define every version it needs, as the image's loader does (Amazon Linux 2023 reports glibc 2.34, yet its `libc.so.6` defines `GLIBC_2.35` and its `libm.so.6` does not).

  ```bash
  IMG=mcr.microsoft.com/dotnet/aspnet:8.0   # the image the application runs on
  GV_CLI=${CONTAINER_CMD:-docker}   # the CLI that Phase 3's detection found, else Docker
  GV_CPL=(-L); case "$GV_CLI $("$GV_CLI" --version 2> /dev/null)" in *podman*) GV_CPL=();; esac   # docker, Finch and nerdctl copy a symbolic link's target with -L; podman cp has no -L and refuses it, also behind a docker command
  GV_TAG=$(printf '%s' "$IMG" | tr -c 'A-Za-z0-9._-' '_')   # names this target's output files (raw/...-$GV_TAG.txt)
  GV_IMG_ID=$("$GV_CLI" image inspect --format '{{.Id}}' "$IMG" 2> /dev/null)   # the image the tag names now: create --platform moves a local tag to the arm64 image
  GV_IMGS=$("$GV_CLI" images -a -q --no-trunc 2> /dev/null) && GV_IMGS="listed: $GV_IMGS"; case $("$GV_CLI" --version 2> /dev/null) in "Docker version"*|"podman version"*) ;; *) GV_IMGS=;; esac   # the images here before the pull: the cleanup removes only one the pull added, and nothing if this listing fails or the CLI is neither docker nor podman (others may list image IDs in another form)
  command -v timeout > /dev/null 2>&1 || timeout() { while [ $# -gt 1 ]; do case $1 in -k|-s|--kill-after|--signal) shift 2;; -*) shift;; *) break;; esac; done; shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit, dropping the options and the duration
  GV_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/graviton-target-root.XXXXXX") || GV_ROOT=   # a new, empty folder, or nothing: the copies below never run without it
  [ -n "$GV_ROOT" ] || echo "ERROR: mktemp -d made no folder under ${TMPDIR:-/tmp}; set TMPDIR to a writable folder and rerun"
  # The image's loaders and libraries, from a container that is created and never started (no emulation, and no
  # shell needed in the image); timeout 300 bounds the image pull that create does
  if [ -n "$GV_ROOT" ] && cid=$(timeout 300 "$GV_CLI" create --platform linux/arm64 "$IMG" none); then
    for f in /etc/os-release /usr/lib/os-release /lib/apk/db/installed; do
      mkdir -p "$GV_ROOT${f%/*}" && "$GV_CLI" cp "${GV_CPL[@]}" "$cid:$f" "$GV_ROOT$f" 2> /dev/null
    done
    for dir in /lib /lib64 /usr/lib /usr/lib64 /lib/aarch64-linux-gnu /usr/lib/aarch64-linux-gnu; do
      mkdir -p "$GV_ROOT$dir"
      for lib in ld-musl-aarch64.so.1 ld-linux-aarch64.so.1 libc.so.6 libm.so.6 libpthread.so.0 libdl.so.2 librt.so.1 \
          libresolv.so.2 libutil.so.1 libanl.so.1 libmvec.so.1 libnsl.so.1 libstdc++.so.6 libgcc_s.so.1; do
        "$GV_CLI" cp "${GV_CPL[@]}" "$cid:$dir/$lib" "$GV_ROOT$dir/$lib" 2> /dev/null
      done
    done
    for l in $(find "$GV_ROOT" -type l 2> /dev/null); do   # a copy without -L (podman) is the link itself: copy its target
      t=$(readlink "$l"); case $t in /*) ;; *) t=$(dirname "${l#"$GV_ROOT"}")/$t;; esac
      hops=0; while [ "$hops" -lt 40 ] && case $t in */../*) true;; *) false;; esac; do t=$(printf '%s' "$t" | sed -E 's#/[^/]+/\.\./#/#; s#^/\.\./#/#'); hops=$((hops + 1)); done   # /etc/../usr/lib/os-release; a leading /../ is /
      rm -f "$l"; "$GV_CLI" cp "$cid:$t" "$l" 2> /dev/null
    done
    { timeout 300 "$GV_CLI" export "$cid" 2> /dev/null || : > "$GV_ROOT/gv-export-failed"; } | tar -tf - 2> /dev/null | awk -F/ '$NF ~ /\.so(\.[0-9]+)*$/ {print $NF}' | sort -u > "$GV_ROOT/gv-image-libs.txt"   # every shared library's name in the image, read without starting it
    [ ! -e "$GV_ROOT/gv-export-failed" ] || rm -f "$GV_ROOT/gv-image-libs.txt" "$GV_ROOT/gv-export-failed"   # no list from an export that failed or was cut off: the check then says so
    "$GV_CLI" rm "$cid" > /dev/null
    n=$("$GV_CLI" image inspect --format '{{.Id}}' "$IMG" 2> /dev/null); [ -z "$GV_IMG_ID" ] || [ "$n" = "$GV_IMG_ID" ] || "$GV_CLI" tag "$GV_IMG_ID" "$IMG"   # a moved tag goes back to the image it named
    case $GV_IMGS in "") ;; *"${n#sha256:}"*) [ -n "$GV_IMG_ID" ] || [ -z "$n" ] || echo "NOTE: $IMG now names the arm64 image that was already here, so the tag stays (removing it could remove that image)";; *) "$GV_CLI" rmi "$n" > /dev/null 2>&1;; esac   # an image the pull added goes; one that was here, by tag or by digest, stays
    os=$(sed -n 's/^PRETTY_NAME=//p' "$GV_ROOT/etc/os-release" "$GV_ROOT/usr/lib/os-release" 2> /dev/null | head -n 1 | tr -d '"')
    c=$(find "$GV_ROOT" -name libc.so.6 -type f | head -n 1); x=$(find "$GV_ROOT" -name 'libstdc++.so.6' -type f | head -n 1)
    if [ -e "$GV_ROOT/lib/ld-musl-aarch64.so.1" ]; then
      m=$(awk '/^P:musl$/{f=1; next} f && /^V:/{print substr($0, 3); exit}' "$GV_ROOT/lib/apk/db/installed" 2> /dev/null)
      libc="musl${m:+ $m}"; [ -e "$GV_ROOT/lib/ld-linux-aarch64.so.1" ] && libc="$libc, with a glibc loader"
    else
      v=$(grep -ao 'release version 2\.[0-9]*' "$c" 2> /dev/null | head -n 1 | cut -d' ' -f3); libc="glibc ${v:-(no libc.so.6 found)}"
    fi
    if [ -n "$x" ]; then
      cxx=$(grep -ao 'GLIBCXX_3\.4\.[0-9][0-9]*' "$x" | sort -u -t. -k3,3n | tail -n 1); cxx=${cxx:-"libstdc++ with no GLIBCXX_ versions"}
    else cxx="no libstdc++.so.6"; fi
    echo "$IMG: ${os:-no os-release}; $libc; $cxx; files in $GV_ROOT"
    mkdir -p graviton-validation/raw && printf '%s\t%s\n' "$GV_TAG" "$GV_ROOT" >> graviton-validation/raw/target-roots.txt   # Phase 3 reads the folder here when this shell is gone
    # The later checks run once for each target that raw/target-roots.txt records, in this shell or a new one. Remove the
    # folder by that exact path (rm -rf "$GV_ROOT"), never by a wildcard, once the report is written.
  else [ -z "$GV_ROOT" ] || rmdir "$GV_ROOT"; echo "$IMG: no arm64 container was created (no arm64 variant of the image, or the pull failed: see the error above)"; fi   # nothing is recorded for it, so no check runs for this image
  ```

  The scans pass the folder with `--target-root`, once for each target that `raw/target-roots.txt` records; a tag can move to a newer OS release, so read the image the project deploys. For EC2 hosts, run `ldd --version | head -n 1` (glibc) or check for `/lib/ld-musl-aarch64.so.1` on the instance.
- **Android builds.** A file built for Android's C library (bionic) needs a bare `libc.so`, as a musl build does, and carries an ELF note owned by `Android`. The check reports it for every Linux RID instead of reading it as musl. Packages keep such files under `runtimes/android-*` (SQLitePCLRaw.lib.e_sqlite3 3.53.3 has `runtimes/android-arm64/native/libe_sqlite3.so`), which `assets` and `scan` skip for Linux RIDs; the rule matters when such a file is committed to the repository or copied into an image by hand.
- **Natives can need more than .NET does.** SQLitePCLRaw.lib.e_sqlite3 2.1.12 needs GLIBC_2.34, Magick.NET-Q16-arm64 14.17.2 needs GLIBC_2.29, and SkiaSharp.NativeAssets.Linux 3.119.0 needs GLIBC_2.27. Pass the target's files with `--target-root`, or its version with `--glibc` when it has no image: on AlmaLinux 8 (glibc 2.28, Graviton2) the check reported libe_sqlite3.so (`needs GLIBC_2.34 (target glibc 2.28)`), and the application failed with `TypeInitializationException: The type initializer for 'Microsoft.Data.Sqlite.SqliteConnection' threw an exception.`, whose innermost exception was `DllNotFoundException: Unable to load shared library 'e_sqlite3'`; `ldd` named the cause: ``/lib64/libc.so.6: version `GLIBC_2.33' not found``.
- **The target's libstdc++.** A native that needs `libstdc++.so.6` needs its `GLIBCXX_` versions too (the `OK` lines show the highest). The folder above gives them; for a target with no image, pass the highest version its libstdc++ defines with `--glibcxx`. musl's loader does not check the versions a file needs, so `--glibcxx` applies to glibc RIDs only. A file that needs more than the target provides is reported as `needs GLIBCXX_3.4.31 (target libstdc++ provides up to GLIBCXX_3.4.24)`.
- **Page size.** On kernels with 64KB pages, glibc 2.34 and earlier refuse a library whose LOAD segments are aligned to less than the page size (`ELF load command alignment not page-aligned`); glibc 2.35 and later refuse one whose segment addresses and file offsets differ by other than a multiple of the page size (`ELF load command address/offset not page-aligned`), which a library linked for 4KB pages usually does. The default aarch64 kernels of AlmaLinux 8 and Rocky Linux 8 use 64KB pages (AlmaLinux 8.10 on Graviton2 reported 65536); their 9 and 10 releases default to 4KB. Pass `--page-size 65536` for such targets, and the check applies the target loader's rule. With `--glibc` 2.34 or earlier it compares each LOAD alignment with the page size; with 2.35 or later it checks that each segment's `p_vaddr - p_offset` is a multiple of the page size, and the file's line shows that value's alignment (`vaddr-offset align`) when it is below `0x10000`; without `--glibc` it applies both rules. musl's loader checks neither value: it maps each segment from its file offset rounded down to the page size at its address rounded down to the page size ([`ldso/dynlink.c`](https://git.musl-libc.org/cgit/musl/tree/ldso/dynlink.c)), which places the segment correctly only when the two differ by a multiple of the page size, so for musl RIDs the check applies the second rule. On AlmaLinux 8.10 (Graviton2, glibc 2.28), a library linked with `-Wl,-z,max-page-size=4096` failed to load with `DllNotFoundException` and `ELF load command alignment not page-aligned`; for that file, `scan --glibc 2.28 --page-size 65536` reports `LOAD alignment 0x1000 is below the target page size 0x10000`, and `scan --target-rid linux-musl-arm64 --page-size 65536` reports `LOAD vaddr-offset alignment 0x1000 is below the target page size 0x10000`.

## 7. Scanning Build and Publish Outputs

The per-RID check covers packages. The output of `dotnet publish` (or `/app` copied out of an image) also holds the application's own files, vendored libraries and anything copied by build targets, so scan it by content too:

```bash
GV_CHECK=$(sed -n 's/^GV_DOTNET_CHECK=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the path Documentation Setup in SKILL.md recorded
[ -f "$GV_CHECK" ] || echo "ERROR: run the Documentation Setup block in SKILL.md first: it records the path of scripts/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one scan per target that §6 recorded; with none, one scan named target
GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
GV_T=(); case $GV_TDIR in "") ;; glibc=*) GV_T=(--glibc "${GV_TDIR#glibc=}");; *) GV_T=(--target-root "$GV_TDIR");; esac; GV_T+=(${GV_PAGE:+--page-size} ${GV_PAGE:+"$GV_PAGE"})
RID=linux-arm64; [ -z "$GV_TDIR" ] || [ ! -e "$GV_TDIR/lib/ld-musl-aarch64.so.1" ] || RID=linux-musl-arm64   # the RID follows the target's C library, as in Phase 3.1
[ -d "publish/$RID" ] || { echo "NOT SCANNED: no publish/$RID folder"; continue; }   # a missing folder keeps the record Phase 3.1 wrote
python3 "$GV_CHECK" scan --target-rid "$RID" "${GV_T[@]}" "publish/$RID" > "graviton-validation/raw/output-scan-$GV_TAG.txt"; rc=$?
cat "graviton-validation/raw/output-scan-$GV_TAG.txt"; echo "exit status $rc (0 no findings, 1 findings, 2 not a folder)"
done
```

For a repository rather than an output, add `--source-tree`: it skips `.git`, `.vs`, `bin`, `obj`, `node_modules` and `graviton-validation` (Phase 1.2.1).

What `scan` reports:
- every ELF file, which must be aarch64, built for the target's libc (an Android build is a finding for every RID), within the target's glibc and libstdc++ versions, and linked for its page size (`--target-rid`, `--target-root`, `--glibc`, `--glibcxx` and `--page-size` work as in §3); the line of an aarch64 file ends with the libraries it needs;
- managed assemblies, which must be `AnyCPU`, `arm64`, or ReadyToRun for linux-arm64; an assembly built for x64 or x86 is a finding;
- a `.runtimeconfig.json` that needs `Microsoft.WindowsDesktop.App` (Windows Forms or WPF), which is a finding;
- the `.deps.json`: its runtime target must be in the target's RID chain, and, for output built without a RID, every package that lists a native file for the source RID must list one for the target too, or another package of its family must (the family rule of §3; `OK ... of the same family, provides it` for NetVips.Native.linux-x64 when NetVips.Native.linux-arm64 is in the same `.deps.json`);
- a native built for the other C library is a `NOTE` when the `.deps.json` shows that the same package also ships a build for the target's C library in this output (the librdkafka.redist case in §3);
- several Linux builds of one library in the output (files in one folder, or in folders named for each platform such as `runtimes/<rid>/native`, whose names differ only by architecture or C library parts): only the build for the target is judged and one `NOTE` names it, so a `FINDING` means no build suits; the application must load that build, which Phase 3.3 confirms at startup (the fixed Linux solution ships `native/x64/libfastsum.so` and `native/arm64/libfastsum.so`);
- object files and static libraries with no aarch64 code, which are a `CHECK`: no loader reads them, but an arm64 build that links them fails;
- files under `runtimes/` for RIDs outside the chain, native PE files and Mach-O files, which are ignored and counted.

With more than one `--target-rid`, every check runs once per RID under a `== target <rid>` line, and `findings:` counts the findings of all of them: a glibc aarch64 library scanned with `--target-rid linux-arm64 --target-rid linux-musl-arm64`, in either order, gives one finding (`glibc build; musl's loader does not provide ld-linux-aarch64.so.1` for a library that needs the glibc loader) and exit 1.

A scan cannot see files that are missing. A package with no native file for linux-arm64 adds none to a linux-arm64 publish: the scan has nothing to report, and only the per-RID check (§3) finds it.

A build without a RID gives an apphost for the build machine (x86-64 on an x86 host): start such output with `dotnet <app>.dll`, or publish with `-r linux-arm64`.

  The 75 files under `runtimes/` for other RIDs were ignored.
- **Published for linux-x64: 11 findings,** one for each x86-64 native and each x64 assembly.
- **A Windows Forms tool published with `-r linux-arm64`** exited 0, but the scan reported `Orders.AdminTool.runtimeconfig.json needs Microsoft.WindowsDesktop.App, which exists only on Windows`.

## 8. Lock Files

A `packages.lock.json` records the RIDs it was resolved for, as `dependencies` keys such as `net8.0/linux-x64`. On a clone of the Linux test solution, which tracks 9 lock files:

1. `dotnet restore --locked-mode` as committed: exit 0.
2. With `linux-arm64` added to `<RuntimeIdentifiers>` in `Directory.Build.props`, `dotnet restore --locked-mode` failed: `error NU1004: The project's runtime identifiers have changed from. Project's runtime identifiers: linux-arm64;linux-x64, lock file's runtime identifiers linux-x64.`
3. `dotnet restore --force-evaluate`: exit 0, and all 9 lock files changed; their keys became `net8.0`, `net8.0/linux-arm64` and `net8.0/linux-x64`.
4. `dotnet restore --locked-mode`: exit 0.

So the fix is to add the RID, run `dotnet restore --force-evaluate`, and commit the regenerated lock files with that change (Phase 2.4).

## 9. Private Feeds and Mirrors

`assets` and `probe` restore through the repository's `NuGet.config`, so they see what the build sees. If a version exists on nuget.org but the internal feed does not have it, the finding is INFRA (the feed), not ARM64: record it and ask the feed owner. Do not change the feed configuration to make a check pass.

## 10. Traps

| Trap | Instead |
|---|---|
| Trusting `dotnet publish` exit 0 | per-RID check plus output scan |
| Searching package contents for "arm64" or "aarch64" | the file's ELF header: OnnxRuntime 1.10.0 has an `aarch64` folder that is never used, and generic folders such as `linux` hide x86-64 files |
| Checking only direct references | the resolved tree; most natives arrive transitively |
| Testing executables in arm64 containers on an x86 host | the host CPU runs x86-64 executables there (Selenium Manager 4.48.0 ran); confirm executables by content or on Graviton |
| Taking the latest version as the fix | the lowest version that probes clean |
| Restoring with extra RIDs in the repository | `assets` works on a copy; lock files change only in Phase 2, deliberately |
| Ignoring Alpine | add `--target-rid linux-musl-arm64` when the image is Alpine |
| Reading glibc floors as monotonic | probe the exact version (SQLitePCLRaw.lib.e_sqlite3 2.0.5 needs GLIBC_2.28, 2.0.6 needs 2.17) |
