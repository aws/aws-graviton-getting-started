# NuGet Native Asset Verification

> The central check of this skill. For every NuGet package the application resolves, it asks one question: does the target runtime identifier (RID) get a native file that runs on Graviton? Read this before Phase 1.2 and Phase 1.3. The commands call the check program in [§11](#11-the-check-program): write it to a temporary file once per session with the block there. It needs Python 3.6 or later; `assets`, `probe` and `config` also need the .NET SDK.

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
- The SDK's warning for such assets, NETSDK1206, appeared only in builds without a RID. Executed on the fixture: 1 warning without a RID, none with `-r linux-x64` or `-r linux-arm64`.
- Folder names that are not RIDs are never selected, and NETSDK1206 does not mention them. Microsoft.ML.OnnxRuntime 1.10.0 keeps its aarch64 build in `runtimes/linux-aarch64/native/`; the warning named only its `osx.10.14-arm64` and `osx.10.14-x64` folders.
- **A missing native file is not a build error.** Executed on the fixture: `dotnet publish -r linux-arm64` exited 0 although SkiaSharp, ONNX Runtime and System.Data.SQLite had no arm64 file and the output still held an x86-64 library; the application failed only at run time, with `DllNotFoundException`. Never accept a publish exit code as evidence.

## 3. The Per-RID Check

Write the program once per session (§11), then run from the repository root (the folder that holds the solution or the project files):

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"   # written by the block in §11
[ -f "$GV_CHECK" ] || echo "ERROR: write the check program first (document_references/nuget-native-assets.md, section 11)"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" assets --source-rid linux-x64 --target-rid linux-arm64 > graviton-validation/raw/native-assets.txt; rc=$?
cat graviton-validation/raw/native-assets.txt; echo "exit status $rc (0 no findings, 1 findings, 2 restore failed or wrote no project.assets.json)"
```

What `assets` does:
- **Works on a copy.** It copies the tree to a temporary folder (without `bin`, `obj`, `.git`, `.vs`, `node_modules`, `graviton-validation`), restores every solution at the root (or every project if there is none) for the source and target RIDs, and deletes the copy afterwards. The repository is not touched. A restore with extra RIDs in the repository itself rewrites its tracked `packages.lock.json` files (§8).
- **Reads the assets files of its own restore.** Before restoring, it deletes every `project.assets.json` and `project.nuget.cache` in the copy, then reads each `project.assets.json` the restore writes, in any folder (`obj/`, `artifacts/obj/<project>/`, a custom `BaseIntermediateOutputPath`), so a file left by an earlier restore or a removed project is never read.
- **Runs the repository's MSBuild files.** The restore imports the copy's `Directory.Build.props` and `Directory.Build.targets`, reads its `Directory.Build.rsp`, and runs any target hooked to restore. The start of [Phase 1](../phases/phase1-static-analysis.md) lists the steps that do this and how to list such code first.
- **Reports every package with native files for these RIDs**, one line per target RID and file:
  - `OK` when the file is an aarch64 build for the target's libc, with the highest `GLIBC_` and `GLIBCXX_` versions it needs, its smallest LOAD alignment (and its `vaddr-offset align` when that is below `0x10000`, §6), and after `needs` the libraries it needs. Each of those comes from the package or must come from the target image: libSkiaSharp.so 2.80.0 needs `libfontconfig.so.1`, which `mcr.microsoft.com/dotnet/aspnet:8.0` and `:10.0` do not contain, so the fixture's Dockerfile installs `libfontconfig1`. Without it, the fixture's thumbnail test failed under arm64 emulation with `libfontconfig.so.1: cannot open shared object file`;
  - `FINDING` when the target RID gets no file, or gets one that is not an aarch64 build, is an Android build, is built for the other libc, needs a newer glibc or libstdc++ than the target's, is linked for a smaller page size than the target's (§6), or is a Windows or macOS binary.
  - Under each `FINDING` and `CHECK`, an indented `via` line with the shortest reference chain from a project to the package, so the direct reference to change is named.
- **Accepts packages that ship both C libraries in one RID folder.** librdkafka.redist 2.15.1 has `librdkafka.so` (glibc) and `alpine-librdkafka.so` (musl) in `runtimes/linux-arm64/native/` and loads one of them at run time. When the target's C library has a build there, the other build is a `NOTE`, not a `FINDING`; Phase 3 confirms which one loads.
- **Judges RID-specific packages as a family.** When a package has no file for the target but another package of the same family does, the line is `OK`. Families are names that differ only by a RID or architecture part: `NetVips.Native.linux-x64` and `NetVips.Native.linux-arm64`, `runtime.linux-x64.*` and `runtime.linux-arm64.*`, `Magick.NET-Q16-x64` and `Magick.NET-Q16-arm64`.
- **Reads static libraries** (ar archives, used when linking with Native AOT) by the ELF headers of their object files. SQLitePCLRaw.lib.e_sqlite3 3.53.3 ships `libe_sqlite3.a` beside `libe_sqlite3.so`.
- **Lists ELF files that packages keep outside `runtimes/`**, per family:
  - `OK` when an aarch64 build is among them;
  - `CHECK` when they are x86-only. They fail only if a build target copies them to the output or a tool runs them, so decide from how the project uses the package (§4).
- **Prints NuGet audit warnings** (NU1901 to NU1904) from its restores as `NOTE NuGet audit:` lines, once each. They are security findings, out of scope unless an ARM64 change introduces them (§5).
- **Flags `packages.config` projects.** Their packages are not restored by PackageReference, so `assets` prints a `CHECK` line that names the `config` command for each such file (below).
- **Exit status:** 0 no findings (`CHECK` lines may remain), 1 findings, 2 the restore failed or wrote no `project.assets.json` inside the copy (an intermediate path outside the repository). A restore whose projects resolve no NuGet package prints `restored 1 project(s); none of them resolves a NuGet package` and exits 0.
- **Options:**
  - `--target-rid linux-musl-arm64` adds Alpine; the option can be repeated;
  - `--glibc 2.34` reports natives that need a newer glibc than the target's (§6);
  - `--glibcxx 3.4.30` reports natives that need a newer libstdc++ than the target's (§6); it applies to glibc RIDs only;
  - `--page-size 65536` reports natives linked for a smaller page size than the target's, by the rule of the target's loader (§6);
  - `--tree FILE` also writes every resolved package, per project and target framework, with its reference chain (JSON).

Executed on the fixture (`linux-x64` to `linux-arm64`, 3 seconds with a warm package cache; long lines shortened):

```
restore Fixture.sln for linux-x64;linux-arm64 (scratch copy)
NOTE NuGet audit: warning NU1903: Package 'Newtonsoft.Json' 12.0.3 has a known high severity vulnerability, https://github.com/advisories/GHSA-5crp-9r3c-p9vr
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
packages: 40; with native files for these RIDs: 5; natives for other platforms only: 1; managed only: 34; findings: 4; checks: 1
```

The `via` line gives one chain. In a restored repository, `dotnet nuget why <project> <package>` prints every path, and works on SDK 8.0.425 and 10.0.401. For the fixture it printed `Fixture.Core` → `Microsoft.Data.Sqlite (v8.0.31)` → `SQLitePCLRaw.bundle_e_sqlite3 (v2.1.12)` → `SQLitePCLRaw.lib.e_sqlite3 (v2.1.12)`. `dotnet list <project> package --include-transitive --format json` lists every resolved package; the fixture's tool resolved 17 transitive packages.

### Projects That Still Use packages.config

.NET Framework projects with `packages.config` cannot be restored for Linux RIDs. `config` probes every package the file lists, one at a time, in a scratch `net8.0` project (§5), which shows early which native packages have no Linux arm64 build at all:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" config path/to/packages.config > graviton-validation/raw/native-assets-packages-config.txt; rc=$?
cat graviton-validation/raw/native-assets-packages-config.txt; echo "exit status $rc"
```

Executed on the .NET Framework fixture: `assets` printed `CHECK Orders.Web/packages.config: these packages are not restored by PackageReference and are not in this report; run: config Orders.Web/packages.config`, and `config` found 5 entries and 1 finding (`no linux-arm64 native: Stub.System.Data.SQLite.Core.NetStandard/1.0.118`, `via probe > System.Data.SQLite.Core 1.0.118 > Stub.System.Data.SQLite.Core.NetStandard 1.0.118`). The full check runs again with `assets` after the project moves to modern .NET.

## 4. Package Shapes That Defeat Name-Based Checks

| Shape | Example (verified by content) | Result on arm64 |
|---|---|---|
| x64-only native | SkiaSharp.NativeAssets.Linux 1.68.3: `runtimes/linux-x64` only | `DllNotFoundException: Unable to load shared library 'libSkiaSharp' or one of its dependencies` |
| arm64 build in a folder that is not a RID | Microsoft.ML.OnnxRuntime 1.10.0: `runtimes/linux-aarch64` | never selected; `DllNotFoundException: Unable to load shared library 'onnxruntime' or one of its dependencies` |
| one build in a generic `linux` folder | Selenium.WebDriver 4.48.0: `runtimes/linux/native/selenium-manager` is x86-64 | selected for linux-arm64. In an arm64 container on an x86 host it ran, because the host CPU executes x86-64 files, so emulated tests pass it |
| arm64 build only under distribution RIDs | LibGit2Sharp.NativeBinaries 2.0.306: `debian-arm64`, `ubuntu.16.04-arm64` | ignored by .NET 8 and later |
| Linux native named `.dll` | Stub.System.Data.SQLite.Core.NetStandard 1.0.119: `runtimes/linux-x64/native/SQLite.Interop.dll` is an x86-64 ELF file | no linux-arm64 file in any release; `DllNotFoundException: Unable to load shared library 'SQLite.Interop.dll' or one of its dependencies` |
| one package per RID | NetVips.Native.linux-x64 (x64 only) and NetVips.Native.linux-arm64 (from 8.10.0); Magick.NET-Q16-x64 (no linux-arm64 in any release), Magick.NET-Q16-arm64 and Magick.NET-Q16-AnyCPU (linux-arm64 from 11.0.0) | the x64 package never works on arm64. The NetVips.Native meta-package resolves the per-RID packages, including linux-arm64 |
| glibc build given to a musl target | SkiaSharp.NativeAssets.Linux 2.80.0 and Microsoft.ML.OnnxRuntime 1.11.0 (no `linux-musl-arm64`) | on Alpine arm64 (emulated), both failed with `DllNotFoundException` |
| executables or libraries outside `runtimes/` | Selenium.WebDriver.ChromeDriver: every release from 2.29.0 on carries an x86-64 Linux driver (`driver/linux64/chromedriver`), copied to the output; earlier releases carry none, and no release has an aarch64 build; Microsoft.CodeCoverage (pulled in by Microsoft.NET.Test.Sdk): x86-64 libraries in `build/` in every release from 16.10.0 to 18.10.1; Grpc.Tools: `tools/linux_arm64` from 2.37.0 | the per-RID comparison does not see them, so the check lists them as `CHECK`. ChromeDriver's file is run by UI tests. The CodeCoverage files are the dynamic instrumentation engine: Microsoft documents dynamic instrumentation on Linux for x64 only and static instrumentation on all platforms ([dotnet-coverage](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-coverage)), so confirm coverage collection on arm64 in Phase 3.2 |
| natives in a transitive package | Microsoft.Data.Sqlite → SQLitePCLRaw.lib.e_sqlite3; Confluent.Kafka → librdkafka.redist; LibGit2Sharp → LibGit2Sharp.NativeBinaries; NetVips.Native → NetVips.Native.linux-arm64 | the direct reference looks managed; check the resolved tree |

## 5. Finding the Lowest Version That Works

`probe` restores one package version in a scratch project, exactly as a build would, and runs the same report. It uses the `NuGet.config` in the current directory, if there is one. `--framework` sets the scratch project's target framework (default `net8.0`):

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" probe SkiaSharp.NativeAssets.Linux 2.80.0
# Versions published on nuget.org, oldest first (package ID in lower case; other feeds have their own API):
curl -fsSL https://api.nuget.org/v3-flatcontainer/skiasharp.nativeassets.linux/index.json \
  | python3 -c 'import json,sys; print(" ".join(v for v in json.load(sys.stdin)["versions"] if "-" not in v))'
```

Probe the candidates upward from the version in use and stop at the first that reports no findings. The minimal fix is that version, not the latest one. Executed:
- Confluent.Kafka 1.5.3 resolves librdkafka.redist 1.5.3, which has no linux-arm64 file. The next stable release, 1.6.1, resolves librdkafka.redist 1.6.1: OK, and it needs GLIBC_2.25.
- LibGit2Sharp 0.26.2 resolves LibGit2Sharp.NativeBinaries 2.0.306 (finding); 0.27.0 resolves 2.0.319 (OK).

Floors found by reading every stable release on nuget.org at the time of writing:

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

No linux-arm64 build in any stable release, so a substitute is a user decision:
- System.Data.SQLite.Core and Stub.System.Data.SQLite.Core.NetStandard (up to 1.0.119);
- Microsoft.ML.Mkl.Redist (up to 5.0.0);
- Magick.NET-Q16-x64 (up to 14.17.2; use Magick.NET-Q16-AnyCPU or Magick.NET-Q16-arm64);
- NetVips.Native.linux-x64 (use NetVips.Native or NetVips.Native.linux-arm64);
- Selenium.WebDriver.ChromeDriver (up to 154.0.8037.9200).

## 6. Target OS: libc, glibc Version, Page Size

- **.NET's own minimum** ([supported-os.md for 8.0](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md), [for 10.0](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md)): .NET 8 needs glibc 2.23 or musl 1.2.2; .NET 10 needs glibc 2.27 (Arm64 and x64) or musl 1.2.3. Amazon Linux 2 has glibc 2.26, below the .NET 10 minimum: in an `amazonlinux:2` arm64 container on Graviton4, .NET 10.0.12 stopped at ``/lib64/libm.so.6: version `GLIBC_2.27' not found`` while .NET 8.0.31 ran.
- **The target image's libc.** Run the image's own C library as the entrypoint. This works on images without a shell (chiseled). On an x86 host the arm64 image runs under emulation (Phase 3, Container Runtime Detection):

  ```bash
  IMG=mcr.microsoft.com/dotnet/aspnet:8.0
  command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
  for e in /lib/aarch64-linux-gnu/libc.so.6 /usr/lib/aarch64-linux-gnu/libc.so.6 /lib64/libc.so.6 /usr/lib64/libc.so.6 /lib/ld-musl-aarch64.so.1; do
    out=$(timeout 150 docker run --rm --platform linux/arm64 --entrypoint "$e" "$IMG" 2>&1 | grep -m1 -E 'release version|^Version')
    [ -n "$out" ] && { echo "$IMG: $e: $out"; break; }
  done
  [ -n "$out" ] || echo "$IMG: no libc version printed (on an x86 host, check that arm64 images run: Phase 3, Container Runtime Detection)"
  ```

  Executed on arm64 images (tags as published at the time of writing):

  | Image | OS | libc |
  |---|---|---|
  | `mcr.microsoft.com/dotnet/aspnet:8.0` | Debian 12 | glibc 2.36 |
  | `mcr.microsoft.com/dotnet/aspnet:10.0` | Ubuntu 24.04 | glibc 2.39 |
  | `mcr.microsoft.com/dotnet/aspnet:8.0-alpine`, `:10.0-alpine` | Alpine 3.24 | musl 1.2.6 |
  | `mcr.microsoft.com/dotnet/runtime-deps:10.0-noble-chiseled` | Ubuntu 24.04, no shell | glibc 2.39 |
  | `mcr.microsoft.com/dotnet/aspnet:8.0-azurelinux3.0` | Azure Linux 3.0 | glibc 2.38 |
  | `public.ecr.aws/lambda/dotnet:8`, `:10` | Amazon Linux 2023 | glibc 2.34 |
  | `public.ecr.aws/amazonlinux/amazonlinux:2023` | Amazon Linux 2023 | glibc 2.34 |
  | `public.ecr.aws/amazonlinux/amazonlinux:2` | Amazon Linux 2 | glibc 2.26 |

  For EC2 hosts, run `ldd --version | head -n 1` (glibc) or check for `/lib/ld-musl-aarch64.so.1` on the instance.
- **Android builds.** A file built for Android's C library (bionic) needs a bare `libc.so`, as a musl build does, and carries an ELF note owned by `Android`. The check reports it for every Linux RID instead of reading it as musl. Packages keep such files under `runtimes/android-*` (SQLitePCLRaw.lib.e_sqlite3 3.53.3 has `runtimes/android-arm64/native/libe_sqlite3.so`), which `assets` and `scan` skip for Linux RIDs; the rule matters when such a file is committed to the repository or copied into an image by hand.
- **Natives can need more than .NET does.** SQLitePCLRaw.lib.e_sqlite3 2.1.12 needs GLIBC_2.34, Magick.NET-Q16-arm64 14.17.2 needs GLIBC_2.29, and SkiaSharp.NativeAssets.Linux 3.119.0 needs GLIBC_2.27. Pass the target's version with `--glibc`. Executed on the fixed fixture with `--glibc 2.26`: `needs GLIBC_2.34 (target glibc 2.26)` for libe_sqlite3.so. On AlmaLinux 8 (glibc 2.28, Graviton2), `assets` and `scan` with `--glibc 2.28` (run with the system Python 3.6.8) reported the same file, and the fixed tool then failed both SQLite checks with `TypeInitializationException: The type initializer for 'Microsoft.Data.Sqlite.SqliteConnection' threw an exception.`; the innermost exception was `DllNotFoundException: Unable to load shared library 'e_sqlite3'`, and `ldd` named the cause: ``/lib64/libc.so.6: version `GLIBC_2.33' not found``.
- **The target's libstdc++.** A native that needs `libstdc++.so.6` needs its `GLIBCXX_` versions too (the `OK` lines show the highest). Pass the highest version the target image's libstdc++ defines with `--glibcxx`. This block reads it without emulation, from a container that is created but never started, so it also works on images without a shell:

  ```bash
  IMG=mcr.microsoft.com/dotnet/aspnet:8.0
  command -v timeout > /dev/null 2>&1 || timeout() { shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit
  # The container is created, never started: no emulation is needed, and images without a shell work too
  cid=$(timeout 300 docker create --platform linux/arm64 "$IMG" none) || cid=
  d=$(mktemp -d "${TMPDIR:-/tmp}/graviton-libstdcxx.XXXXXX")
  for f in /usr/lib/aarch64-linux-gnu/libstdc++.so.6 /lib/aarch64-linux-gnu/libstdc++.so.6 /usr/lib64/libstdc++.so.6 /usr/lib/libstdc++.so.6; do
    [ -n "$cid" ] && docker cp -L "$cid:$f" "$d/libstdc++.so.6" 2> /dev/null && break
  done
  [ -n "$cid" ] && docker rm "$cid" > /dev/null
  if [ -s "$d/libstdc++.so.6" ]; then
    v=$(grep -ao 'GLIBCXX_3\.4\.[0-9][0-9]*' "$d/libstdc++.so.6" | sort -u -t. -k3,3n | tail -n 1)
    echo "$IMG: $f: ${v:-defines no GLIBCXX_ versions (musl images: leave --glibcxx out)}"
  else
    echo "$IMG: no libstdc++.so.6 (a native file that needs it fails to load until the image installs it)"
  fi
  rm -rf "$d"
  ```

  Executed on arm64 images, in bash and zsh (each value equals the highest version definition that `readelf -V` reads from the same file):

  | Image | libstdc++ |
  |---|---|
  | `mcr.microsoft.com/dotnet/aspnet:8.0` | GLIBCXX_3.4.30 |
  | `mcr.microsoft.com/dotnet/aspnet:10.0`, `mcr.microsoft.com/dotnet/runtime-deps:10.0-noble-chiseled` | GLIBCXX_3.4.33 |
  | `mcr.microsoft.com/dotnet/aspnet:8.0-azurelinux3.0` | GLIBCXX_3.4.32 |
  | `public.ecr.aws/lambda/dotnet:8`, `:10`, `public.ecr.aws/amazonlinux/amazonlinux:2023` | GLIBCXX_3.4.33 |
  | `public.ecr.aws/amazonlinux/amazonlinux:2` | GLIBCXX_3.4.24 |
  | `mcr.microsoft.com/dotnet/aspnet:8.0-alpine`, `:10.0-alpine` | defines no `GLIBCXX_` versions |

  musl's loader does not check the versions a file needs, so `--glibcxx` applies to glibc RIDs only. The linux-arm64 natives in the packages this skill was tested with need at most GLIBCXX_3.4.22 (`libhostpolicy.so` of the .NET 10.0.12 runtime pack), below every image above. Executed with an aarch64 library that needs GLIBCXX_3.4.31: `scan --glibc 2.41 --glibcxx 3.4.24` reported `needs GLIBCXX_3.4.31 (target libstdc++ provides up to GLIBCXX_3.4.24)`, and `--glibcxx 3.4.33` gave `findings: 0`.
- **Page size.** On kernels with 64KB pages, glibc 2.34 and earlier refuse a library whose LOAD segments are aligned to less than the page size (`ELF load command alignment not page-aligned`); glibc 2.35 and later refuse one whose segment addresses and file offsets differ by other than a multiple of the page size (`ELF load command address/offset not page-aligned`), which a library linked for 4KB pages usually does. The default aarch64 kernels of AlmaLinux 8 and Rocky Linux 8 use 64KB pages (AlmaLinux 8.10 on Graviton2 reported 65536); their 9 and 10 releases default to 4KB. Pass `--page-size 65536` for such targets, and the check applies the target loader's rule. With `--glibc` 2.34 or earlier it compares each LOAD alignment with the page size; with 2.35 or later it checks that each segment's `p_vaddr - p_offset` is a multiple of the page size, and the file's line shows that value's alignment (`vaddr-offset align`) when it is below `0x10000`; without `--glibc` it applies both rules. musl's loader checks neither value: it maps each segment from its file offset rounded down to the page size at its address rounded down to the page size ([`ldso/dynlink.c`](https://git.musl-libc.org/cgit/musl/tree/ldso/dynlink.c)), which places the segment correctly only when the two differ by a multiple of the page size, so for musl RIDs the check applies the second rule. Both 4KB-linked libraries tested break both rules. Every arm64 native resolved by the fixed fixture is aligned to `0x10000`. Executed on AlmaLinux 8.10 (Graviton2, 65536-byte pages, glibc 2.28): an aarch64 build of the fixture's library linked with `-Wl,-z,max-page-size=4096` failed with `DllNotFoundException` and `ELF load command alignment not page-aligned`, while the same file loaded on Graviton4 (4096-byte pages). For that file, `scan --glibc 2.28 --page-size 65536` reports `LOAD alignment 0x1000 is below the target page size 0x10000`, and `scan --target-rid linux-musl-arm64 --page-size 65536` reports `LOAD vaddr-offset alignment 0x1000 is below the target page size 0x10000`.

## 7. Scanning Build and Publish Outputs

The per-RID check covers packages. The output of `dotnet publish` (or `/app` copied out of an image) also holds the application's own files, vendored libraries and anything copied by build targets, so scan it by content too:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
mkdir -p graviton-validation/raw
python3 "$GV_CHECK" scan publish/linux-arm64 > graviton-validation/raw/output-scan.txt; rc=$?
cat graviton-validation/raw/output-scan.txt; echo "exit status $rc (0 no findings, 1 findings, 2 not a folder)"
```

For a repository rather than an output, add `--source-tree`: it skips `.git`, `.vs`, `bin`, `obj`, `node_modules` and `graviton-validation` (Phase 1.2.1).

What `scan` reports:
- every ELF file, which must be aarch64, built for the target's libc (an Android build is a finding for every RID), within the target's glibc and libstdc++ versions, and linked for its page size (`--target-rid`, `--glibc`, `--glibcxx` and `--page-size` work as in §3); the line of an aarch64 file ends with the libraries it needs;
- managed assemblies, which must be `AnyCPU`, `arm64`, or ReadyToRun for linux-arm64; an assembly built for x64 or x86 is a finding;
- a `.runtimeconfig.json` that needs `Microsoft.WindowsDesktop.App` (Windows Forms or WPF), which is a finding;
- the `.deps.json`: its runtime target must be in the target's RID chain, and, for output built without a RID, every package that lists a native file for the source RID must list one for the target too, or another package of its family must (the family rule of §3; `OK ... of the same family, provides it` for NetVips.Native.linux-x64 when NetVips.Native.linux-arm64 is in the same `.deps.json`);
- a native built for the other C library is a `NOTE` when the `.deps.json` shows that the same package also ships a build for the target's C library in this output (the librdkafka.redist case in §3);
- an x86-64 file is a `NOTE`, not a `FINDING`, when an aarch64 build of the same file name is in the same output: the application ships both and must load the right one, which Phase 3.3 confirms at startup (the fixed Linux solution ships `native/x64/libfastsum.so` and `native/arm64/libfastsum.so`);
- files under `runtimes/` for RIDs outside the chain, native PE files and Mach-O files, which are ignored and counted.

With more than one `--target-rid`, every check runs once per RID under a `== target <rid>` line, and `findings:` counts the findings of all of them: a glibc aarch64 library scanned with `--target-rid linux-arm64 --target-rid linux-musl-arm64`, in either order, gives one finding (`is a glibc build (target uses musl)`) and exit 1.

A scan cannot see files that are missing. The fixture published with `-r linux-arm64` produced one finding, the vendored `native/x64/libfastsum.so`; the same output had no SkiaSharp, ONNX Runtime or SQLite.Interop library at all, and only the per-RID check (§3) reports those.

Executed on other outputs of the fixture:
- **Built without a RID: 6 findings.** They were:
  - the apphost `Fixture.Tool`, built for the build machine (x86-64); start such output with `dotnet <app>.dll` or publish with `-r linux-arm64`;
  - `Fixture.Legacy.dll is managed x64`;
  - three `.deps.json` entries (ONNX Runtime 1.10.0, SkiaSharp 1.68.3, System.Data.SQLite);
  - `libfastsum.so`.

  The 75 files under `runtimes/` for other RIDs were ignored.
- **Published for linux-x64: 11 findings,** one for each x86-64 native and each x64 assembly.
- **A Windows Forms tool published with `-r linux-arm64`** exited 0, but the scan reported `Orders.AdminTool.runtimeconfig.json needs Microsoft.WindowsDesktop.App, which exists only on Windows`.

## 8. Lock Files

A `packages.lock.json` records the RIDs it was resolved for, as `dependencies` keys such as `net8.0/linux-x64`. Executed on a scratch clone of the fixture, which tracks 9 lock files:

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

## 11. The Check Program

Run this block once per session, in any shell, before the commands above. It writes the program to a temporary file and replaces any earlier copy; the program reads files and restores scratch copies, and never writes to the repository:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
cat > "$GV_CHECK" <<'EOF'
#!/usr/bin/env python3
"""Graviton (Linux arm64) checks for .NET projects. Needs Python 3.6+ and, except for scan, the .NET SDK.

  assets [DIR]            Restore a scratch copy of DIR for the source and target runtime identifiers (RIDs)
                          and report, per NuGet package, the native files selected for each target RID,
                          judged by their content (ELF header), plus ELF files packages carry outside runtimes/.
                          --tree FILE also writes every resolved package with its shortest reference chain.
  scan DIR                Report the files of a build or publish output (or an extracted image) by content.
                          --source-tree skips .git, .vs, bin, obj, node_modules and graviton-validation.
  probe ID VERSION        Run the assets report on one package version in a scratch project.
  config PACKAGES_CONFIG  Probe every package listed in a packages.config file (.NET Framework projects).

The repository is never modified: restores run in a temporary copy. FINDING lines are files that fail on the
target; CHECK lines are x86-only files that fail only if something runs them (decide from how they are used);
NOTE lines need no change on their own (including NuGet audit warnings, NU1901 to NU1904, from the restores).
Exit status: 0 no findings (CHECK lines may remain), 1 findings, 2 usage or restore error.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ELF_ARCH = {3: "i386", 40: "arm", 62: "x86-64", 183: "aarch64", 243: "riscv"}
PE_ARCH = {0x14C: "x86", 0x8664: "x64", 0xAA64: "arm64", 0x1C4: "arm"}
R2R_LINUX = 0x7B79  # ReadyToRun images for Linux store the machine XOR this value
AUDIT_SEEN = set()  # NuGet audit warnings (NU1901 to NU1904) already printed
MACHO = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
# Portable RID graph of the .NET 8 and 10 SDKs (PortableRuntimeIdentifierGraph.json).
RID_CHAIN = {
    "linux-arm64": ["linux-arm64", "linux", "unix-arm64", "unix", "any"],
    "linux-musl-arm64": ["linux-musl-arm64", "linux-musl", "linux-arm64", "linux", "unix-arm64", "unix", "any"],
    "linux-x64": ["linux-x64", "linux", "unix-x64", "unix", "any"],
    "linux-musl-x64": ["linux-musl-x64", "linux-musl", "linux-x64", "linux", "unix-x64", "unix", "any"],
}
FINDINGS = []
CHECKS = []


def finding(text):
    FINDINGS.append(text)
    print("FINDING " + text)


def check(text):
    CHECKS.append(text)
    print("CHECK " + text)


def vtuple(s):
    return tuple(int(x) for x in s.split("."))


def elf_info(b):
    """Architecture, libc, highest GLIBC_ and GLIBCXX_ versions needed, smallest PT_LOAD alignment, alignment of
    p_vaddr - p_offset over the PT_LOAD segments (voff), and the libraries the file needs (DT_NEEDED)."""
    if len(b) < 20:
        return {"arch": "truncated", "libc": "", "glibc": "", "glibcxx": "", "align": 0, "voff": 0, "needed": []}
    machine = struct.unpack_from("<H", b, 18)[0]
    i = {"arch": ELF_ARCH.get(machine, "e_machine %d" % machine), "libc": "", "glibc": "", "glibcxx": "", "align": 0,
         "voff": 0, "needed": []}
    if len(b) < 64 or b[4] != 2 or b[5] != 1:
        return i  # only 64-bit little-endian files are parsed further
    phoff = struct.unpack_from("<Q", b, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", b, 54)
    loads, dyn, android = [], None, False
    for k in range(phnum):
        o = phoff + k * phentsize
        if o + 56 > len(b):
            break
        p_type = struct.unpack_from("<I", b, o)[0]
        p_offset, p_vaddr = struct.unpack_from("<QQ", b, o + 8)
        p_filesz = struct.unpack_from("<Q", b, o + 32)[0]
        p_align = struct.unpack_from("<Q", b, o + 48)[0]
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz, p_align))
        elif p_type == 2:
            dyn = (p_offset, p_filesz)
        elif p_type == 4:  # notes: one owned by "Android" marks a build for Android's C library (bionic)
            q = p_offset
            while q + 12 <= min(len(b), p_offset + p_filesz):
                namesz, descsz = struct.unpack_from("<II", b, q)
                android = android or b[q + 12:q + 12 + namesz].rstrip(b"\0") == b"Android"
                q += 12 + (namesz + 3) // 4 * 4 + (descsz + 3) // 4 * 4
    if loads:
        i["align"] = min(x[3] for x in loads)
        d = [v - o for v, o, _, _ in loads if v != o]
        i["voff"] = min(x & -x for x in d) if d else 0  # largest power of two dividing every p_vaddr - p_offset
    if dyn is None:
        i["libc"] = "static"
        return i

    def off(va):
        for v, o, sz, _ in loads:
            if v <= va < v + sz:
                return va - v + o
        return None
    tags, needed = {}, []
    for k in range(dyn[1] // 16):
        if dyn[0] + 16 * k + 16 > len(b):
            break
        tag, val = struct.unpack_from("<qQ", b, dyn[0] + 16 * k)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        else:
            tags.setdefault(tag, val)
    strtab = off(tags[5]) if 5 in tags else None

    def string(o):
        if strtab is None:
            return ""
        e = b.find(b"\0", strtab + o)
        return b[strtab + o:e].decode("latin-1")
    names = [string(n) for n in needed]
    i["needed"] = names
    if "libc.so.6" in names:
        i["libc"] = "glibc"
    elif "libc.so" in names and android:
        i["libc"] = "android"
    elif any(n == "libc.so" or n.startswith("libc.musl") for n in names):
        i["libc"] = "musl"
    vers = []
    o = off(tags[0x6FFFFFFE]) if 0x6FFFFFFE in tags else None
    for _ in range(tags.get(0x6FFFFFFF, 0)):
        if o is None or o + 16 > len(b):
            break
        _v, cnt, vn_file, aux, nxt = struct.unpack_from("<HHIII", b, o)
        lib = string(vn_file)
        a = o + aux
        for _ in range(cnt):
            if a + 16 > len(b):
                break
            _h, _fl, _ot, name, anext = struct.unpack_from("<IHHII", b, a)
            vers.append((lib, string(name)))
            if not anext:
                break
            a += anext
        if not nxt:
            break
        o += nxt

    def highest(prefix, skip=()):
        v = [n[len(prefix):] for lib, n in vers if lib not in skip and n.startswith(prefix)
             and re.match(r"^[0-9]+(\.[0-9]+)*$", n[len(prefix):])]
        return prefix + max(v, key=vtuple) if v else ""
    if i["libc"] not in ("musl", "android"):  # they need no glibc; a GLIBC_ version requested from libgcc_s is not a glibc need
        i["glibc"] = highest("GLIBC_", skip=("libgcc_s.so.1",))
    i["glibcxx"] = highest("GLIBCXX_")  # GLIBCXX_ versions come from libstdc++, on musl targets too
    return i


def ar_arches(b):
    """ELF machines of the object files in a static library (ar archive)."""
    arches, o = set(), 8
    while o + 60 <= len(b):
        try:
            size = int(b[o + 48:o + 58].decode("ascii").strip() or "0")
        except ValueError:
            break
        data = b[o + 60:o + 60 + size]
        if data[:4] == b"\x7fELF" and len(data) >= 20:
            m = struct.unpack_from("<H", data, 18)[0]
            arches.add(ELF_ARCH.get(m, "e_machine %d" % m))
        o += 60 + size + (size & 1)
    return arches


def pe_kind(b):
    """'managed AnyCPU', 'managed x64', 'managed ReadyToRun linux-arm64', 'native PE x64', or None."""
    if len(b) < 0x40 or b[:2] != b"MZ":
        return None
    o = struct.unpack_from("<I", b, 0x3C)[0]
    if o + 24 > len(b) or b[o:o + 4] != b"PE\0\0":
        return None
    machine, nsec = struct.unpack_from("<HH", b, o + 4)
    optsz = struct.unpack_from("<H", b, o + 20)[0]
    opt = o + 24
    dd = opt + (96 if struct.unpack_from("<H", b, opt)[0] == 0x10B else 112)
    clr = struct.unpack_from("<I", b, dd + 14 * 8)[0] if dd + 120 <= len(b) else 0
    arch, target = PE_ARCH.get(machine), "windows"
    if arch is None and machine ^ R2R_LINUX in PE_ARCH:
        arch, target = PE_ARCH[machine ^ R2R_LINUX], "linux"
    if not clr:
        return "native PE " + (arch or hex(machine))
    c = None
    for k in range(nsec):
        vs, va, rs, rp = struct.unpack_from("<IIII", b, opt + optsz + 40 * k + 8)
        if va <= clr < va + max(vs, rs):
            c = clr - va + rp
    if c is None or c + 68 > len(b):
        return "managed (unreadable header)"
    flags = struct.unpack_from("<I", b, c + 16)[0]
    if struct.unpack_from("<I", b, c + 64)[0]:
        return "managed ReadyToRun %s-%s" % (target, arch or hex(machine))
    if machine == 0x14C:  # 0x2 32BITREQUIRED; with 0x20000 32BITPREFERRED it is AnyCPU (prefer 32-bit)
        return "managed x86" if flags & 0x2 and not flags & 0x20000 else "managed AnyCPU"
    return "managed " + (arch or hex(machine))


def head(path, n=64):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def read_all(path):
    with open(path, "rb") as f:
        return f.read()


def elf_problems(i, args, target):
    """Problems of an ELF file for one target RID (empty list if none)."""
    if i["arch"] != "aarch64":
        return ["is %s" % i["arch"]]
    p = []
    musl = "musl" in target
    if i["libc"] == "android":
        p.append("is an Android build (bionic C library; target uses %s)" % ("musl" if musl else "glibc"))
    if musl and i["libc"] == "glibc":
        p.append("is a glibc build (target uses musl)")
    if not musl and i["libc"] == "musl":
        p.append("is a musl build (target uses glibc)")
    if args.glibc and i["glibc"] and vtuple(i["glibc"][6:]) > vtuple(args.glibc):
        p.append("needs %s (target glibc %s)" % (i["glibc"], args.glibc))
    if not musl and args.glibcxx and i["glibcxx"] and vtuple(i["glibcxx"][8:]) > vtuple(args.glibcxx):
        # glibc targets only: musl's loader does not check version needs, and Alpine's libstdc++ defines no versions
        p.append("needs %s (target libstdc++ provides up to GLIBCXX_%s)" % (i["glibcxx"], args.glibcxx))
    if args.page_size:
        # glibc 2.34 and earlier refuse a PT_LOAD whose p_align is not a multiple of the page size; glibc 2.35 and
        # later, and musl, need p_vaddr - p_offset to be one. A glibc target without --glibc: both rules.
        old = not musl and not (args.glibc and vtuple(args.glibc) >= (2, 35))
        new = musl or not (args.glibc and vtuple(args.glibc) < (2, 35))
        if old and i["align"] and i["align"] < args.page_size:
            p.append("LOAD alignment %#x is below the target page size %#x" % (i["align"], args.page_size))
        if new and i["voff"] and i["voff"] < args.page_size:
            p.append("LOAD vaddr-offset alignment %#x is below the target page size %#x" % (i["voff"], args.page_size))
    return p


def describe(i):
    voff = "vaddr-offset align %#x" % i["voff"] if i["arch"] == "aarch64" and 0 < i["voff"] < 0x10000 else ""
    return " ".join(x for x in (i["libc"], i["glibc"], i["glibcxx"], ("align %#x" % i["align"]) if i["align"] else "", voff)
                    if x)


def needs(i):
    """The libraries an aarch64 file needs (DT_NEEDED): each comes from the target image or ships with the file."""
    return "needs " + " ".join(i["needed"]) if i["arch"] == "aarch64" and i["needed"] else ""


def base_name(name):
    """Package name without its RID or architecture part, so x64 and arm64 variants are judged as one family."""
    n = re.sub(r"^runtime\.(linux|osx|win|freebsd|alpine|unix)(-[a-z0-9]+)*\.", "", name, flags=re.I)
    n = re.sub(r"\.(linux|osx|win|freebsd|alpine)(-[a-z0-9]+)+$", "", n, flags=re.I)
    return re.sub(r"-(x64|x86|arm64|arm)$", "", n, flags=re.I)


# ---------- assets, probe, config ----------

def restore(work, rids, timeout):
    targets = sorted(f for f in os.listdir(work) if f.endswith((".sln", ".slnx")))
    projects = list(targets)
    if not projects:
        for d, dirs, files in os.walk(work):
            dirs[:] = [x for x in dirs if x not in ("bin", "obj", ".git")]
            projects += [os.path.relpath(os.path.join(d, f), work) for f in files if f.endswith((".csproj", ".fsproj", ".vbproj"))]
    if not projects:
        print("no .sln, .slnx or project file found")
        return False
    ok = True
    for p in projects:
        print("restore %s for %s (scratch copy)" % (p, ";".join(rids)))
        cmd = ["dotnet", "restore", p, "-p:RuntimeIdentifiers=\"%s\"" % ";".join(rids),
               "-p:RestoreLockedMode=false", "-p:EnableWindowsTargeting=true"]
        try:
            r = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            print("restore of %s timed out after %d s" % (p, timeout))
            return False
        errors = sorted(set(re.findall(r"error [A-Z]+[0-9]+: [^\[\n]{0,200}", r.stdout)))
        for w in sorted(set(x.strip() for x in re.findall(r"warning NU190[1-4]: [^\[\n]{0,200}", r.stdout))):
            if w not in AUDIT_SEEN:
                AUDIT_SEEN.add(w)
                print("NOTE NuGet audit: %s" % w)
        if r.returncode:
            ok = False
            print("restore of %s failed (exit %d)%s" % (p, r.returncode, "".join("\n  " + e for e in errors[:5])))
    return ok


def load_packages(root):
    """Packages of every restored project, and per project and framework the graph used for reference chains."""
    pkgs, graphs = {}, []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("bin", ".git")]
        if "project.assets.json" not in files:
            continue
        a = json.load(open(os.path.join(d, "project.assets.json")))
        folders = list(a.get("packageFolders", {}))
        pp = a.get("project", {}).get("restore", {}).get("projectPath", "")
        proj = os.path.relpath(os.path.dirname(pp) if pp else os.path.dirname(d), root)
        for key, entries in a.get("targets", {}).items():
            rid = key.split("/", 1)[1] if "/" in key else ""
            for name, e in entries.items():
                if e.get("type") != "package":
                    continue
                lib = a["libraries"].get(name, {})
                r = pkgs.setdefault(name, {"rids": {}, "projects": set(), "path": lib.get("path", ""),
                                           "files": lib.get("files", []), "folders": folders})
                r["projects"].add(proj)
                if rid:
                    r["rids"].setdefault(rid, set()).update(k for k in e.get("native", {}) if not k.endswith("_._"))
            if not rid:
                byname = dict((k.split("/")[0].lower(), k) for k in entries)
                roots = [byname[x.split()[0].lower()] for x in a.get("projectFileDependencyGroups", {}).get(key, [])
                         if x.split() and x.split()[0].lower() in byname]
                graphs.append((proj, key, entries, byname, roots))
    return pkgs, graphs


def shortest_paths(entries, byname, roots):
    """Breadth-first search from a project's direct references: node -> previous node (None for roots)."""
    prev, queue = dict((r, None) for r in roots), list(roots)
    while queue:
        nxt = []
        for n in queue:
            for dep in entries.get(n, {}).get("dependencies", {}):
                k = byname.get(dep.lower())
                if k and k not in prev:
                    prev[k] = n
                    nxt.append(k)
        queue = nxt
    return prev


def label(entries, k):
    return k.split("/")[0] if entries.get(k, {}).get("type") == "project" else k.replace("/", " ")


def path_to(entries, prev, k):
    out = []
    while k is not None:
        out.append(label(entries, k))
        k = prev[k]
    return out[::-1]


def chain(graphs, cache, name):
    """Shortest reference chain from any project to package name, for example
    'src/Fixture.Tool > Fixture.Core > Microsoft.Data.Sqlite 8.0.31 > SQLitePCLRaw.lib.e_sqlite3 2.1.12'."""
    best = None
    for i, (proj, key, entries, byname, roots) in enumerate(graphs):
        k = byname.get(name.lower())
        if k is None:
            continue
        if i not in cache:
            cache[i] = shortest_paths(entries, byname, roots)
        if k in cache[i]:
            c = [proj] + path_to(entries, cache[i], k)
            if best is None or len(c) < len(best):
                best = c
    if best is None:
        return ""
    return "%s (direct reference)" % best[0] if len(best) == 2 else " > ".join(best)


def locate(r, f):
    for fo in r["folders"]:
        p = os.path.join(fo, r["path"], f)
        if os.path.isfile(p):
            return p
    return None


def report_assets(root, args):
    start, cstart = len(FINDINGS), len(CHECKS)
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("bin", "obj", ".git", "packages")]
        if "packages.config" in files:
            rel = os.path.relpath(os.path.join(d, "packages.config"), root)
            check("%s: these packages are not restored by PackageReference and are not in this report; run: config %s"
                  % (rel, rel))
    pkgs, graphs = load_packages(root)
    cache = {}

    def via(name):
        c = chain(graphs, cache, name.split("/")[0])
        if c:
            print("  via " + c)
    if not pkgs:
        if graphs:
            print("restored %d project(s); none of them resolves a NuGet package" % len(set(g[0] for g in graphs)))
            return 1 if len(FINDINGS) > start else 0
        print("restore passed, but it wrote no project.assets.json inside the scratch copy "
              "(BaseIntermediateOutputPath or ArtifactsPath outside the repository?)")
        return 2
    used = lambda r: "; used by " + ", ".join(sorted(r["projects"]))
    groups = {}
    for name, r in pkgs.items():
        elfs = []
        for f in r["files"]:
            if f.startswith("runtimes/") or f.endswith("/"):
                continue
            p = locate(r, f)
            h = head(p) if p else b""
            if h[:4] == b"\x7fELF" and len(h) >= 20:
                elfs.append((ELF_ARCH.get(struct.unpack_from("<H", h, 18)[0], "other"), f))
        if elfs:
            g = groups.setdefault(base_name(name.split("/")[0]).lower(), {"names": [], "elfs": [], "r": r})
            g["names"].append(name)
            g["elfs"] += elfs
    family = {}  # (family, RID) -> a package of that family with natives for the RID
    for name, r in pkgs.items():
        for t in args.target_rid:
            if r["rids"].get(t):
                family.setdefault((base_name(name.split("/")[0]).lower(), t), name)
    native_pkgs = other = managed = 0
    for name in sorted(pkgs, key=str.lower):
        r = pkgs[name]
        if not any(r["rids"].get(x) for x in [args.source_rid] + args.target_rid):
            if any(f.startswith("runtimes/") and "/native/" in f for f in r["files"]):
                other += 1
            else:
                managed += 1
            continue
        native_pkgs += 1
        folders = sorted(set(f.split("/")[1] for f in r["files"] if f.startswith("runtimes/") and "/native/" in f))
        src_names = set(os.path.basename(f) for f in r["rids"].get(args.source_rid, ()))
        for t in args.target_rid:
            got = sorted(r["rids"].get(t, ()))
            if not got:
                sibling = family.get((base_name(name.split("/")[0]).lower(), t))
                if sibling:
                    print("OK %s %s: no native of its own; %s, of the same family, provides it" % (t, name, sibling))
                    continue
                finding("no %s native: %s (%s has %d; runtimes/ folders: %s)%s" % (
                    t, name, args.source_rid, len(src_names), ", ".join(folders) or "none", used(r)))
                via(name)
                continue
            missing = sorted(src_names - set(os.path.basename(f) for f in got))
            if missing:
                print("NOTE %s gets %d native file(s) of %s, %s gets %d; only on %s: %s" % (
                    t, len(got), name, args.source_rid, len(src_names), args.source_rid, ", ".join(missing)))
            # Builds for both C libraries in one RID folder (librdkafka.redist ships librdkafka.so and
            # alpine-librdkafka.so): the package's loader picks one at run time, so a build for the other
            # C library is only a finding when no build for the target's C library is present.
            libcs = set()
            for f in got:
                fp = locate(r, f)
                if fp and head(fp)[:4] == b"\x7fELF":
                    fi = elf_info(read_all(fp))
                    if fi["arch"] == "aarch64":
                        libcs.add(fi["libc"])
            want = "musl" if "musl" in t else "glibc"
            for f in got:
                p = locate(r, f)
                if p is None:
                    print("NOTE %s native %s of %s is not in the package folder" % (t, f, name))
                    continue
                b = read_all(p)
                if b[:8] == b"!<arch>\n":  # static library, used when linking (Native AOT), judged by its objects
                    arches = ar_arches(b)
                    if arches == {"aarch64"}:
                        print("OK %s %s: %s (static library, aarch64 objects)" % (t, name, f))
                    else:
                        finding("%s native %s of %s is a static library with %s objects%s" % (
                            t, f, name, ", ".join(sorted(arches)) or "no ELF", used(r)))
                        via(name)
                    continue
                if b[:4] != b"\x7fELF":
                    if b[:2] == b"MZ" or b[:4] in MACHO:
                        finding("%s native %s of %s is a Windows or macOS binary%s" % (t, f, name, used(r)))
                        via(name)
                    else:
                        print("NOTE %s native %s of %s is not a binary (ignored)" % (t, f, name))
                    continue
                i = elf_info(b)
                probs = elf_problems(i, args, t)
                other_libc = i["arch"] == "aarch64" and i["libc"] in ("glibc", "musl") and i["libc"] != want
                if other_libc and want in libcs and len(probs) == 1:
                    print("NOTE %s native %s of %s is a %s build; the package also has a %s build for this RID, and its "
                          "loader picks one at run time (confirm in Phase 3)" % (t, f, name, i["libc"], want))
                elif probs:
                    finding("%s native %s of %s %s%s" % (t, f, name, "; ".join(probs), used(r)))
                    via(name)
                else:
                    print("OK %s %s: %s (%s)" % (t, name, f, "; ".join(x for x in (describe(i), needs(i)) if x)))
    for g in sorted(groups.values(), key=lambda g: g["names"][0].lower()):
        arches = sorted(set(a for a, _ in g["elfs"]))
        sample = ", ".join(f for _, f in g["elfs"][:3])
        if "aarch64" in arches:
            print("OK ELF files outside runtimes/ in %s: %s" % (", ".join(g["names"]), ", ".join(arches)))
        else:
            check("ELF files outside runtimes/ in %s are %s only (they fail only if a build target copies them to the "
                  "output or a tool runs them), e.g. %s%s" % (", ".join(g["names"]), ", ".join(arches), sample, used(g["r"])))
            via(g["names"][0])
    if getattr(args, "tree", None):
        tree = {}
        for proj, key, entries, byname, roots in graphs:
            prev = shortest_paths(entries, byname, roots)
            tree.setdefault(proj, {})[key] = dict(
                (label(entries, k), {"type": entries[k].get("type"), "via": path_to(entries, prev, k)[:-1]})
                for k in sorted(entries, key=str.lower) if k in prev)
        with open(args.tree, "w") as f:
            json.dump(tree, f, indent=1, sort_keys=True)
        print("dependency tree: %d projects written to %s" % (len(tree), args.tree))
    print("packages: %d; with native files for these RIDs: %d; natives for other platforms only: %d; managed only: %d; "
          "findings: %d; checks: %d" % (len(pkgs), native_pkgs, other, managed, len(FINDINGS) - start, len(CHECKS) - cstart))
    return 1 if len(FINDINGS) > start else 0


def cmd_assets(args):
    src = os.path.abspath(args.dir)
    if args.tree:
        args.tree = os.path.abspath(args.tree)
    with tempfile.TemporaryDirectory(prefix="gv-assets-") as tmp:
        work = os.path.join(tmp, "src")
        shutil.copytree(src, work, symlinks=True,
                        ignore=shutil.ignore_patterns("bin", "obj", ".git", ".vs", "node_modules", "graviton-validation"))
        for d, dirs, files in os.walk(work):  # read only the assets files this restore writes
            for f in files:
                if f in ("project.assets.json", "project.nuget.cache"):
                    os.remove(os.path.join(d, f))
        if not restore(work, [args.source_rid] + args.target_rid, args.timeout):
            return 2
        return report_assets(work, args)


def cmd_probe(args):
    with tempfile.TemporaryDirectory(prefix="gv-probe-") as tmp:
        for c in ("NuGet.config", "nuget.config", "NuGet.Config"):
            if os.path.isfile(c):
                shutil.copy(c, tmp)
        proj = os.path.join(tmp, "probe", "probe.csproj")
        os.makedirs(os.path.dirname(proj))
        with open(proj, "w") as f:
            f.write('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <TargetFramework>%s</TargetFramework>\n'
                    '    <ManagePackageVersionsCentrally>false</ManagePackageVersionsCentrally>\n'
                    '    <NuGetAuditMode>all</NuGetAuditMode>\n  </PropertyGroup>\n'
                    '  <ItemGroup>\n    <PackageReference Include="%s" Version="[%s]" />\n  </ItemGroup>\n</Project>\n'
                    % (args.framework, args.id, args.version))
        if not restore(tmp, [args.source_rid] + args.target_rid, args.timeout):
            return 2
        return report_assets(tmp, args)


def cmd_config(args):
    entries = [(p.get("id"), p.get("version")) for p in ET.parse(args.file).getroot().iter("package")]
    errors = 0
    for pid, ver in entries:
        print("--- %s %s" % (pid, ver))
        a = argparse.Namespace(**vars(args))
        a.id, a.version = pid, ver
        errors += cmd_probe(a) == 2
    print("packages.config entries: %d; restore errors: %d; findings: %d; checks: %d" % (len(entries), errors, len(FINDINGS), len(CHECKS)))
    return 1 if FINDINGS else (2 if errors else 0)


# ---------- scan ----------

def deps_check(path, rel, chain, source):
    """For outputs built without a RID: native assets listed per RID in the .deps.json."""
    try:
        d = json.load(open(path))
    except ValueError:
        return
    rt = d.get("runtimeTarget", {}).get("name", "")
    print("deps.json %s: runtime target %s" % (rel, rt or "-"))
    rid = rt.split("/", 1)[1] if "/" in rt else ""
    if rid and rid not in chain:
        finding("%s was built for %s" % (rel, rid))
    for libs in d.get("targets", {}).values():
        def native_rids(e):
            return set(v.get("rid") for v in e.get("runtimeTargets", {}).values() if v.get("assetType") == "native")
        family = {}  # family name -> [(package, RIDs with a native)]
        for lib, e in libs.items():
            family.setdefault(base_name(lib.split("/")[0]).lower(), []).append((lib, native_rids(e)))
        for lib, e in libs.items():
            rids = native_rids(e)
            if source in rids and not rids & set(chain):
                sib = [x for x, r in family.get(base_name(lib.split("/")[0]).lower(), []) if r & set(chain)]
                if sib:
                    print("OK %s: %s has no %s native of its own; %s, of the same family, provides it" % (
                        rel, lib, chain[0], sib[0]))
                else:
                    finding("%s lists a %s native for %s but none for %s (RIDs: %s)" % (
                        rel, source, lib, chain[0], ", ".join(sorted(rids))))


def deps_owners(root):
    """Native file (relative to root) -> package, from the .deps.json files in root."""
    owners = {}
    for n in sorted(os.listdir(root)):
        if not n.endswith(".deps.json"):
            continue
        try:
            d = json.load(open(os.path.join(root, n)))
        except ValueError:
            continue
        for libs in d.get("targets", {}).values():
            for lib, e in libs.items():
                for k in e.get("native", {}):
                    owners.setdefault(k, lib)
                    owners.setdefault(os.path.basename(k), lib)  # RID-specific outputs copy natives to the root
                for k, v in e.get("runtimeTargets", {}).items():
                    if v.get("assetType") == "native":
                        owners.setdefault(k, lib)
    return owners


def cmd_scan(args):
    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print("ERROR: %s is not a folder" % args.dir)
        return 2
    for target in args.target_rid:
        if len(args.target_rid) > 1:
            print("== target %s" % target)
        scan_one(root, args, target)
    print("findings: %d" % len(FINDINGS))
    return 1 if FINDINGS else 0


def scan_one(root, args, target):
    """Every check of scan for one target RID."""
    chain = RID_CHAIN.get(target, [target, "linux", "unix", "any"])
    want = "musl" if "musl" in target else "glibc"
    owners = deps_owners(root)
    pkg_libcs = {}  # package -> C libraries of its aarch64 natives present in this output
    arm_names = {}  # file name -> an aarch64 build of it in this output (outside runtimes/ of other RIDs)
    for d0, dirs0, files0 in os.walk(root):
        parts0 = os.path.relpath(d0, root).split(os.sep)
        if "runtimes" in parts0:
            k0 = parts0.index("runtimes")
            if len(parts0) > k0 + 1 and parts0[k0 + 1] not in chain:
                dirs0[:] = []
                continue
        for n0 in files0:
            p0 = os.path.join(d0, n0)
            if not os.path.islink(p0) and os.path.isfile(p0) and head(p0, 4) == b"\x7fELF":
                if elf_info(read_all(p0))["arch"] == "aarch64":
                    arm_names.setdefault(n0, os.path.relpath(p0, root))
    for rel_o, lib in owners.items():
        po = os.path.join(root, rel_o)
        if os.path.isfile(po) and head(po, 4) == b"\x7fELF":
            io = elf_info(read_all(po))
            if io["arch"] == "aarch64":
                pkg_libcs.setdefault(lib, set()).add(io["libc"])
    counts, other_rid, ignored = {}, 0, 0
    skip = (".git", ".vs", "bin", "obj", "node_modules", "graviton-validation") if args.source_tree else (".git",)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in skip)
        parts = os.path.relpath(d, root).split(os.sep)
        if "runtimes" in parts:
            k = parts.index("runtimes")
            if len(parts) > k + 1 and parts[k + 1] not in chain:
                other_rid += sum(len(fs) for _, _, fs in os.walk(d))
                dirs[:] = []
                continue
        for n in sorted(files):
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            if n.endswith(".runtimeconfig.json"):
                try:
                    c = json.load(open(p))["runtimeOptions"]
                except (ValueError, KeyError):
                    continue
                fw = [x["name"] for x in c.get("frameworks", [c.get("framework")]) if x]
                print("runtimeconfig %s: %s" % (rel, ", ".join(fw) or "self-contained"))
                if "Microsoft.WindowsDesktop.App" in fw:
                    finding("%s needs Microsoft.WindowsDesktop.App, which exists only on Windows" % rel)
                continue
            if n.endswith(".deps.json"):
                deps_check(p, rel, chain, args.source_rid)
                continue
            h = head(p, 8)
            if h == b"!<arch>\n":
                arches = ar_arches(read_all(p))
                kind = "static library " + (", ".join(sorted(arches)) or "no ELF")
                if arches != {"aarch64"}:
                    finding("%s is a %s" % (rel, kind))
            elif h[:4] == b"\x7fELF":
                i = elf_info(read_all(p))
                kind = "ELF " + i["arch"]
                probs = elf_problems(i, args, target)
                print("%-12s %-40s %s%s" % (kind, describe(i), rel, "  (%s)" % needs(i) if needs(i) else ""))
                lib = owners.get(rel)
                if (lib and len(probs) == 1 and i["arch"] == "aarch64" and i["libc"] in ("glibc", "musl")
                        and i["libc"] != want and want in pkg_libcs.get(lib, ())):
                    print("NOTE %s is a %s build; %s also ships a %s build here, and its loader picks one at run time "
                          "(confirm in Phase 3)" % (rel, i["libc"], lib, want))
                elif i["arch"] != "aarch64" and n in arm_names:
                    print("NOTE %s is %s; an aarch64 build of the same file is at %s, so the code that loads it must "
                          "choose by architecture (confirm at startup, Phase 3.3)" % (rel, i["arch"], arm_names[n]))
                elif probs:
                    finding("%s %s" % (rel, "; ".join(probs)))
            elif h[:2] == b"MZ":
                kind = pe_kind(read_all(p)) or "PE (unreadable)"
                if kind.startswith("native PE"):
                    ignored += 1
                elif kind not in ("managed AnyCPU", "managed arm64", "managed ReadyToRun linux-arm64"):
                    finding("%s is %s" % (rel, kind))
            elif h[:4] in MACHO:
                kind = "Mach-O"
                ignored += 1
            else:
                continue
            counts[kind] = counts.get(kind, 0) + 1
    print("files by kind: " + (", ".join("%s %d" % kv for kv in sorted(counts.items())) or "none"))
    if ignored or other_rid:
        print("not loaded on %s, ignored: %d native PE or Mach-O, %d under runtimes/ for other RIDs" % (target, ignored, other_rid))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    for name in ("assets", "scan", "probe", "config"):
        p = sub.add_parser(name)
        p.add_argument("--source-rid", default="linux-x64")
        p.add_argument("--target-rid", action="append", help="repeatable; default linux-arm64 (add linux-musl-arm64 for Alpine)")
        p.add_argument("--glibc", help="target glibc version, for example 2.34; natives needing a newer GLIBC_ are findings")
        p.add_argument("--glibcxx", help="highest GLIBCXX_ version of the glibc target's libstdc++, for example 3.4.30; "
                       "natives needing a newer one are findings (musl RIDs ignore it)")
        p.add_argument("--page-size", type=int, help="target kernel page size in bytes, for example 65536")
        p.add_argument("--timeout", type=int, default=900, help="seconds per dotnet command")
        if name == "assets":
            p.add_argument("dir", nargs="?", default=".")
            p.add_argument("--tree", help="also write every resolved package and its shortest reference chain (JSON)")
        elif name == "scan":
            p.add_argument("dir")
            p.add_argument("--source-tree", action="store_true", help="skip .git, .vs, bin, obj, node_modules, graviton-validation")
        elif name == "probe":
            p.add_argument("id")
            p.add_argument("version")
        else:
            p.add_argument("file")
        if name in ("probe", "config"):
            p.add_argument("--framework", default="net8.0")
    args = ap.parse_args()
    if not args.command:
        ap.print_help()
        return 2
    args.target_rid = args.target_rid or ["linux-arm64"]
    args.glibcxx = (args.glibcxx or "").replace("GLIBCXX_", "")
    if args.glibcxx and not re.match(r"^[0-9]+(\.[0-9]+)*$", args.glibcxx):
        print("ERROR: --glibcxx takes a version such as 3.4.30, not %s" % args.glibcxx)
        return 2
    return {"assets": cmd_assets, "scan": cmd_scan, "probe": cmd_probe, "config": cmd_config}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
EOF
python3 "$GV_CHECK" --help | head -n 2
```
