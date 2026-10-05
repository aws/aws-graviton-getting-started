# Package Management Mapping

> How the version of a NuGet package is decided in each project layout, and how to change it so that a Phase 2 fix lands where restore reads it. Read with [nuget-native-assets.md](nuget-native-assets.md), which says which version to choose; this file says where to write it. Every result below was executed with SDK 8.0.425 or 10.0.401 on scratch projects.

## 1. Detection

```bash
# Which package-management mechanisms the repository uses
find . \( -name .git -o -name bin -o -name obj -o -name node_modules \) -prune -o -type f \( -name 'Directory.Packages.props' -o -name 'packages.lock.json' \
  -o -name 'packages.config' -o -name 'paket.dependencies' -o -name 'paket.lock' -o -name 'paket.references' -o -iname 'nuget.config' \
  -o -name 'global.json' -o -name 'dotnet-tools.json' \) -print | sort
grep -rlE --include='*.props' --include='*.targets' --include='*.csproj' --include='*.fsproj' --include='*.vbproj' \
  'ManagePackageVersionsCentrally|CentralPackageTransitivePinningEnabled|RestorePackagesWithLockFile|RestoreLockedMode|VersionOverride' . 2>/dev/null || true
```

| Marker | Mechanism | Where a version is decided |
|---|---|---|
| `<PackageReference Include="X" Version="1.2.3" />` in project files | PackageReference | the project file (§2.1) |
| `Directory.Packages.props` with `ManagePackageVersionsCentrally` set to `true` | central package management | `<PackageVersion>` items in that file; `VersionOverride` on one project's reference (§2.2) |
| `packages.lock.json`, `RestorePackagesWithLockFile` | lock files | regenerated from the above (§2.3) |
| `packages.config` | .NET Framework style | the file itself; moves to PackageReference in the port (§2.4) |
| `paket.dependencies`, `paket.lock`, `paket.references` | Paket | `paket.dependencies` (§2.5) |
| `NuGet.config` | feeds and package source mapping | where packages come from, not which version (§2.6) |
| `global.json` | SDK selection | which SDK runs restore and build (§2.7) |
| `dotnet-tools.json` | local tools | tool versions, run on the build host (§2.8). SDK 8.0.425 wrote it to `.config/`, SDK 10.0.401 to the current folder |

To read which version restore actually resolved for a package, after a restore of the project:

```bash
PROJECT_DIR=src/Fixture.Core          # the project folder
PACKAGE=SkiaSharp.NativeAssets.Linux  # the package
python3 - "$PROJECT_DIR/obj/project.assets.json" "$PACKAGE" <<'EOF'
import json, sys
a = json.load(open(sys.argv[1]))
for target, entries in sorted(a["targets"].items()):
    for key in entries:
        name, version = key.split("/")
        if name.lower() == sys.argv[2].lower():
            print("%s: %s %s" % (target, name, version))
EOF
```

## 2. Inline Tier: Command Matrix

### 2.1 PackageReference with versions in project files

- **Direct reference:** change `Version=` on the `<PackageReference>`.
- **Transitive package:** add a direct `<PackageReference>` with the fixed version; the direct reference wins. Executed: Confluent.Kafka 1.5.3 resolved librdkafka.redist 1.5.3, which has no linux-arm64 file. With `<PackageReference Include="librdkafka.redist" Version="1.6.1" />` added, it resolved 1.6.1.
- **A direct reference cannot go below what a parent requires:** `<PackageReference Include="SQLitePCLRaw.lib.e_sqlite3" Version="2.1.4" />` next to Microsoft.Data.Sqlite 8.0.31 (which requires 2.1.12 or later) failed with `error NU1605: Warning As Error: Detected package downgrade: SQLitePCLRaw.lib.e_sqlite3 from 2.1.12 to 2.1.4.` In that case change the parent's version instead.

### 2.2 Central package management

- **Direct reference:** change the `<PackageVersion Include="X" Version="..." />` item in `Directory.Packages.props`. Executed: the Linux test solution's fixes (SkiaSharp, ONNX Runtime, Selenium, AWSSDK.S3) were all one-line changes there.
- **One project only:** `VersionOverride` on its `<PackageReference>` (`<PackageReference Include="SkiaSharp.NativeAssets.Linux" VersionOverride="2.80.0" />` resolved 2.80.0 while the central version stayed 1.68.3). Use it only when one project must differ; one central version is the default.
- **`Version=` on a `<PackageReference>` is an error here:** `error NU1008: Projects that use central package version management should not define the version on the PackageReference items but on the PackageVersion items`.
- **Transitive package:** a `<PackageVersion>` for a package no project references directly is ignored unless `<CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled>` is set. Executed with Confluent.Kafka 1.5.3 and `<PackageVersion Include="librdkafka.redist" Version="1.6.1" />`: 1.5.3 resolved without the property and 1.6.1 with it, and the per-RID check then printed `OK linux-arm64 librdkafka.redist/1.6.1`. Enabling the property is a change to the whole solution's resolution, so prefer a direct reference in the one project that needs it when only one does.
- **Pinning below a parent's requirement fails:** `error NU1109: Detected package downgrade: SQLitePCLRaw.lib.e_sqlite3 from 2.1.12 to centrally defined 2.1.4.`

### 2.3 Lock files

`packages.lock.json` records the RIDs it was resolved for. After a version change or a new RID, run `dotnet restore --force-evaluate` and commit every changed lock file; a locked restore for a RID the lock file lacks fails with NU1004. The executed sequence is in [nuget-native-assets.md §8](nuget-native-assets.md#8-lock-files).

### 2.4 packages.config

.NET Framework projects list exact versions in `packages.config`, and the SDK on Linux cannot restore them for Linux RIDs. Check each listed version with the `config` command ([nuget-native-assets.md §3](nuget-native-assets.md#projects-that-still-use-packagesconfig)). The packages move to `<PackageReference>` items in the port to modern .NET ([windows-to-linux.md](windows-to-linux.md)); at that point choose versions that have linux-arm64 files and drop packages whose function is built into modern .NET (Microsoft.AspNet.WebApi and Microsoft.AspNet.WebApi.Core, for example, become ASP.NET Core).

### 2.5 Paket

Executed with Paket 10.3.1 as a local tool:
- **Install:** `dotnet tool install paket` worked under SDK 10.0.401 and failed under SDK 8.0.425 with `Settings file 'DotnetToolSettings.xml' was not found in the package.` Run Paket commands with an SDK that can install it (Phase 3.0, session-scoped).
- **The per-RID check works:** `dotnet paket install` wrote `paket.lock`, a restore produced `obj/project.assets.json` with `net8.0/linux-arm64` targets, and `assets` printed `FINDING no linux-arm64 native: SkiaSharp.NativeAssets.Linux/1.68.3`.
- **Change a version:** edit the line in `paket.dependencies` (`nuget SkiaSharp.NativeAssets.Linux 2.80.0`) and run `dotnet paket install`; `assets` then printed `OK linux-arm64 SkiaSharp.NativeAssets.Linux/2.80.0`. `dotnet paket update SkiaSharp.NativeAssets.Linux --version 2.80.0` against the exact pin failed: `Version 2.80.0 doesn't match the version requirement 1.68.3 ... that was specified in paket.dependencies`.
- **Transitive versions differ from NuGet:** Paket resolved SkiaSharp 4.153.1 for SkiaSharp.NativeAssets.Linux 1.68.3's `SkiaSharp (>= 1.68.3)` dependency, where NuGet picks the lowest version that satisfies the range. Read `paket.lock`, not the dependency ranges, before deciding what resolved.

### 2.6 NuGet.config: feeds and package source mapping

`NuGet.config` decides where packages come from. With package source mapping, a package is fetched only from the sources mapped to its ID. Two executed behaviors matter:
- **A warm package cache hides feed gaps.** With `*` mapped to an empty internal feed and only `Microsoft.*` mapped to nuget.org, restore and `probe` both succeeded, because SkiaSharp.NativeAssets.Linux 2.80.0 was already in the global packages folder.
- **With an empty cache, the gap shows.** The same restore failed: `error NU1101: Unable to find package SkiaSharp.NativeAssets.Linux. No packages exist with this id in source(s): internal. PackageSourceMapping is enabled, the following source(s) were not considered: nuget.org.` `probe` exited 2 with the same error.

So when a fix must come from an internal feed, probe it with an empty cache, from the repository root so that its `NuGet.config` applies:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
cache=$(mktemp -d)
NUGET_PACKAGES="$cache" python3 "$GV_CHECK" probe SkiaSharp.NativeAssets.Linux 2.80.0; echo "exit status $?"
rm -rf "$cache"
```

A version that probes clean on nuget.org but not through the repository's feeds is an INFRA finding for the feed owner. Never edit sources or mappings to make a check pass.

### 2.7 global.json: which SDK runs

`global.json` in the folder or a parent picks the SDK; `rollForward` decides how far it may move. Executed with SDKs 8.0.425 and 10.0.401 installed:

| `version` | `rollForward` | SDK used |
|---|---|---|
| 8.0.100 | latestFeature | 8.0.425 |
| 8.0.100 | latestPatch | none: `A compatible .NET SDK was not found.` |
| 8.0.400 | latestPatch | 8.0.425 |
| 8.0.100 | latestMajor | 10.0.401 |
| 9.0.100 | latestFeature | none |
| 9.0.100 | latestMajor | 10.0.401 |
| 10.0.100 | latestFeature | 10.0.401 |
| 10.0.100 | latestPatch | none |
| no global.json | | 10.0.401 (the newest) |

Do not edit `global.json` to make a build pass: install the SDK it asks for, session-scoped (Phase 3.0). The SDK matters for arm64 in two ways: the target framework it can build (SDK 8 cannot build `net10.0`), and the solution formats it reads (SDK 8.0.425 rejected an `.slnx` file).

### 2.8 Local tools: dotnet-tools.json

Local tools are NuGet packages that run on the build host, so they matter on an arm64 build host or CI runner, not in the application. After `dotnet tool restore`, scan the restored tool's folder by content (`scan "$NUGET_PACKAGES/<tool id in lower case>/<version>"`). Executed: Amazon.Lambda.Tools 7.0.0 held `managed AnyCPU 30, native PE x86 5` (Windows-only native files, ignored on Linux) and no findings.

## 3. Mapped Tier: Assemblies Outside NuGet

Assemblies referenced by path (`<Reference Include="..."><HintPath>lib/...</HintPath></Reference>`) or committed to the repository have no package metadata: no RID folders, no lock file. The repository scan (Phase 1.2.1, `scan --source-tree`) judges them by content, including managed assemblies built for x64 or x86. A committed `packages/` folder from a `packages.config` restore is scanned the same way.

## 4. Rules That Apply to Every Mechanism

1. **One version per package for the whole solution.** Change the place every project reads (the central file, the shared props file, `paket.dependencies`), not each project, unless only one project uses the package.
2. **The lowest version that probes clean** ([nuget-native-assets.md §5](nuget-native-assets.md#5-finding-the-lowest-version-that-works)), never the latest by default.
3. **Fix a transitive package by raising it, or by changing its parent.** Pinning below what a parent requires fails (NU1605, NU1109). When the version that works on the target is below what the parent requires (for example a glibc limit, [nuget-native-assets.md §6](nuget-native-assets.md#6-target-os-libc-glibc-version-page-size)), the choice is the parent's version or the target OS: a user decision.
4. **Regenerate lock files** with `dotnet restore --force-evaluate` after any version or RID change, and commit them with the change.
5. **Probe through the repository's feeds with an empty cache** before calling a version available.
6. **Keep the mechanism.** Do not move a solution to or from central package management, Paket or lock files: that is a tooling change, out of scope ([agent-scope-boundaries.md](agent-scope-boundaries.md)).
