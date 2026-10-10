# Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues identified in Phase 1. Update ONLY what is required for ARM64 compatibility (findings labelled MUST UPGRADE in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md)). Findings labelled user decision are presented with their options and left unchanged until the user chooses.

For a .NET Framework or Windows starting point (Phase 1.1), the approved move to modern .NET on Linux comes first, following [../document_references/windows-to-linux.md](../document_references/windows-to-linux.md); the steps below then apply to the moved projects.

## 2.1 Native Library Resolution

> **Output: update `graviton-validation/02-native-library-report.md`** (Resolution Details)

For each x86-only native file committed to the repository (Phase 1.2.1):

**If source code available:**

Build the aarch64 file with the project's own native build, on aarch64 hardware (a Graviton host or an ARM64 CI runner, directly or in a `linux/arm64` container, which runs natively there). On an x86 host the same container runs under emulation, where compiling is slow and unsupported (Phase 3, "Emulation limits"), so do not compile there. A plain C library can instead be cross-compiled on the x86 host with no emulation; Ubuntu 24.04 packages the cross compiler as `gcc-aarch64-linux-gnu`:

```bash
mkdir -p src/Fixture.Core/native/arm64   # the folder for the aarch64 build, next to the x64 one
$CONTAINER_CMD run --rm --init --platform linux/amd64 -v "$PWD":/w -w /w -e HOST_IDS="$(id -u):$(id -g)" ubuntu:24.04 timeout 600 sh -c \
  'apt-get update && apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu libc6-dev-arm64-cross && aarch64-linux-gnu-gcc -shared -fPIC -O2 -o src/Fixture.Core/native/arm64/libfastsum.so native/fastsum.c && chown "$HOST_IDS" src/Fixture.Core/native/arm64/libfastsum.so'
echo "cross-compile: exit $?"   # must be 0 before the scan below means anything
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" scan src/Fixture.Core/native/arm64   # the file's line must start with "ELF aarch64", and no FINDING may follow
```

Executed on the Linux solution (`$CONTAINER_CMD` from Phase 3, here `docker`): the scan's line for `libfastsum.so` began with `ELF aarch64  align 0x10000`, the scan printed `findings: 0`, and the file belonged to the host user. The block is for x86 hosts: on Graviton4 the x86-64 image could not start (`[FATAL tini (8)] exec timeout failed: Exec format error`), and the scan of the then empty folder printed `files by kind: none` with `findings: 0`, so check the `cross-compile` exit status before reading the scan. On an arm64 host, compile natively instead: `clang -shared -fPIC -O2 -o src/Fixture.Core/native/arm64/libfastsum.so native/fastsum.c` gave `ELF aarch64  glibc GLIBC_2.17 align 0x10000`. `HOST_IDS` hands the file the container writes back to your user: on a Linux host, files written through a bind mount otherwise belong to root. A library that links other native libraries needs their aarch64 builds too; build it on aarch64 hardware.

Ship the aarch64 file the way the project ships the x64 one. The Linux solution copies its native files to the output from project items, so the change is one more item next to the existing one:

```xml
<!-- src/Fixture.Core/Fixture.Core.csproj -->
<None Include="native/x64/libfastsum.so" CopyToOutputDirectory="PreserveNewest" CopyToPublishDirectory="PreserveNewest" />
<None Include="native/arm64/libfastsum.so" CopyToOutputDirectory="PreserveNewest" CopyToPublishDirectory="PreserveNewest" />
```

**If source unavailable:** ask the user for an aarch64 build of the library, or confirm that a managed fallback is acceptable (record that the fallback is slower, not that the migration passed). A native file that really comes from a NuGet package, copied into the repository by hand, is replaced by a package reference to a version with a linux-arm64 build (§2.2).

**Update native library loading logic** to handle ARM64. A resolver that maps the process architecture to a folder needs an Arm64 branch (the Linux solution's resolver, from Phase 1.4):

```csharp
// Before
string arch = RuntimeInformation.ProcessArchitecture switch
{
    Architecture.X64 => "x64",
    _ => throw new PlatformNotSupportedException($"fastsum is not built for {RuntimeInformation.ProcessArchitecture}"),
};

// After
string arch = RuntimeInformation.ProcessArchitecture switch
{
    Architecture.X64 => "x64",
    Architecture.Arm64 => "arm64",
    _ => throw new PlatformNotSupportedException($"fastsum is not built for {RuntimeInformation.ProcessArchitecture}"),
};
return NativeLibrary.Load(Path.Combine(AppContext.BaseDirectory, "native", arch, "libfastsum.so"));
```

Executed: with both changes, the linux-arm64 publish held `native/arm64/libfastsum.so` (aarch64) beside `native/x64/libfastsum.so`; the output scan reported the x64 file as a `NOTE` (an aarch64 build of the same file is present), and the self-check in a linux/arm64 container loaded the aarch64 library (`PASS fast sum (vendored libfastsum): 6.5`). `RuntimeInformation.ProcessArchitecture` returned `Arm64` in every linux/arm64 container used to validate this skill.

## 2.2 Dependency Compatibility Updates

> **Output: update `graviton-validation/03-dependency-compatibility-report.md`**

Update ONLY dependencies flagged as MUST UPGRADE in Phase 1.3. Do NOT upgrade compatible dependencies. Prefer the *lowest* version whose native files probe clean for every target RID, not the latest: probe the candidates upward from the version in use and **probe the exact candidate** before writing it ([../document_references/nuget-native-assets.md](../document_references/nuget-native-assets.md) §5). Floors are not always monotonic.

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" probe SkiaSharp.NativeAssets.Linux 2.80.0 --target-rid linux-arm64 --glibc 2.34; echo "exit status $?"
```

> **Skill config:** If `skill-config.md` defines `dotnet.target_rids`, the candidate must probe clean for each of those RIDs. Probes use the repository's `NuGet.config`; if the repository's feeds lack the candidate, record an INFRA item ("the feed needs SkiaSharp.NativeAssets.Linux 2.80.0") rather than choosing a different version. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

**Read the NuGet audit lines of each probe.** `probe` prints the NU1901 to NU1904 warnings of the probed package and of its dependencies as `NOTE NuGet audit:` lines, each naming its package (its scratch project sets `NuGetAuditMode` to `all`; `assets` keeps the repository's own setting). If the candidate has a warning that the current version does not have, present the floor and the lowest version without the warning as one user decision. Executed: SkiaSharp 1.68.3 had no audit warning; 2.80.0, the arm64 floor, reported `warning NU1903: Package 'SkiaSharp' 2.80.0 has a known high severity vulnerability, https://github.com/advisories/GHSA-j7hp-h8jx-5ppr`; 2.88.6 was the lowest release without it and probed clean for linux-arm64 (GLIBC_2.17). An advisory that the current version already has stays out of scope.

**Where to write the version** depends on how the solution manages packages ([../document_references/package-management-mapping.md](../document_references/package-management-mapping.md)):

| Mechanism | Direct reference | Transitive package | Then |
|---|---|---|---|
| PackageReference with versions | `Version=` on the `<PackageReference>` | a direct `<PackageReference>` in the project that needs it | `dotnet restore --force-evaluate` if lock files exist |
| central package management | `<PackageVersion>` in `Directory.Packages.props` | a direct reference, or a `<PackageVersion>` with `CentralPackageTransitivePinningEnabled` | same |
| Paket | the line in `paket.dependencies` | a line in `paket.dependencies` | `dotnet paket install` |

**Direct dependencies:** the Linux solution keeps versions centrally, so each fix was one line in `Directory.Packages.props`:

```xml
<!-- Directory.Packages.props -->
<PackageVersion Include="SkiaSharp" Version="2.80.0" />                      <!-- was 1.68.3: no linux-arm64 native -->
<PackageVersion Include="SkiaSharp.NativeAssets.Linux" Version="2.80.0" />   <!-- 2.80.0 depends on SkiaSharp 2.80.0 -->
<PackageVersion Include="Microsoft.ML.OnnxRuntime" Version="1.11.0" />       <!-- was 1.10.0: arm64 build in a folder NuGet never selects -->
<PackageVersion Include="Selenium.WebDriver" Version="4.49.0" />             <!-- was 4.48.0: one x86-64 Selenium Manager for every Linux RID -->
<PackageVersion Include="AWSSDK.S3" Version="3.3.107.2" />                   <!-- was 3.3.107.1: AWSSDK.Core without IMDSv2 support -->
```

**Transitive dependencies:** when a parent pulls in a native package without an arm64 build, raise the parent if a version of it brings a working one (Confluent.Kafka 1.5.3 to 1.6.1 brings librdkafka.redist 1.6.1); otherwise reference the transitive package directly. Executed: a direct `<PackageReference Include="librdkafka.redist" Version="1.6.1" />` next to Confluent.Kafka 1.5.3 resolved 1.6.1, and so did a central `<PackageVersion>` with `CentralPackageTransitivePinningEnabled`. A version below the parent's requirement fails restore (`NU1605`, or `NU1109` with central management).

**Packages with no linux-arm64 build in any release:** these need a substitute, and substitutions change behavior, so present the evidence and wait for the user. Example from the Linux solution: System.Data.SQLite.Core (through Stub.System.Data.SQLite.Core.NetStandard, no linux-arm64 file up to 1.0.119) replaced by Microsoft.Data.Sqlite, which the solution already used:

```csharp
// Before (System.Data.SQLite)
using var connection = new SQLiteConnection("Data Source=:memory:");
connection.Open();
using var command = new SQLiteCommand("select sqlite_version()", connection);
return (string)command.ExecuteScalar()!;

// After (Microsoft.Data.Sqlite, with Dapper as elsewhere in the solution)
using var connection = new SqliteConnection("Data Source=:memory:");
connection.Open();
return connection.ExecuteScalar<string>("select sqlite_version()")!;
```

Remove the `<PackageReference>` and the `<PackageVersion>` of the replaced package. Executed: the self-check in a linux/arm64 container returned the SQLite version (`3.53.3`) through Microsoft.Data.Sqlite. Its SQLitePCLRaw native needs GLIBC_2.34, so check the target's glibc (Phase 1.1) before choosing it for an Amazon Linux 2 target.

**Lock files and RIDs:** add the target RID wherever the source RID is listed, regenerate the lock files, and confirm that a locked restore passes:

```xml
<!-- Directory.Build.props -->
<RuntimeIdentifiers>linux-x64;linux-arm64</RuntimeIdentifiers>
```

```bash
dotnet restore Fixture.sln --force-evaluate   # the solution from Phase 1.1
dotnet restore Fixture.sln --locked-mode; echo "locked restore: exit $?"
```

Executed on a clone of the Linux solution: `--force-evaluate` rewrote all 9 lock files, and the locked restore then exited 0 ([../document_references/nuget-native-assets.md](../document_references/nuget-native-assets.md) §8). Commit the lock files with the change.

**Target framework changes:** follow `dotnet.framework_bump` (Phase 1.5): `ask` presents the options and waits; `approved=<tfm>` applies the change to every project that needs it and records it in `01-project-assessment.md`; `never` documents the blocker and changes nothing. The Linux solution's Lambda function needed one: `dotnetcore3.1` blocks updates, so its move to arm64 includes a move to `net10.0` and the `dotnet10` runtime (§2.4); `net8.0` and `dotnet8` reach end of support on November 10, 2026 (Phase 1.5). The solution pins SDK 8.0.400 in `global.json`, so the same approval covers the pin: with it, the build stopped at `NETSDK1045: The current .NET SDK does not support targeting .NET 10.0`, and with `10.0.100` (`latestFeature`) it passed. Executed on a copy of the solution with both changes: `restore --force-evaluate` rewrote the Lambda project's lock file, the Lambda project and the whole solution built with SDK 10.0.401, `publish -r linux-arm64` produced a `net10.0` runtimeconfig, and the function's packages (Amazon.Lambda.Core 2.3.0, Amazon.Lambda.Serialization.SystemTextJson 2.4.4) did not change. When a package does not support the approved framework, choose its lowest version that does and probe it.

After the changes, keep the Phase 1 evidence that `03-dependency-compatibility-report.md` cites, then re-run the Phase 1.1 check:

```bash
cp graviton-validation/raw/native-assets.txt graviton-validation/raw/native-assets-phase1.txt
cp graviton-validation/raw/dependency-tree.json graviton-validation/raw/dependency-tree-phase1.json
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" assets --source-rid linux-x64 --target-rid linux-arm64 --glibc 2.34 \
  --tree graviton-validation/raw/dependency-tree.json > graviton-validation/raw/native-assets.txt; rc=$?
cat graviton-validation/raw/native-assets.txt; echo "exit status $rc (0 no findings, 1 findings, 2 restore failed or wrote no project.assets.json)"
```

Executed on the fixed Linux solution: `packages: 38; with native files for these RIDs: 4; natives for other platforms only: 1; managed only: 33; findings: 0; checks: 1` (the remaining `CHECK` is Microsoft.CodeCoverage, confirmed in Phase 3.2). Newtonsoft.Json 12.0.3 and Dapper 2.0.123 were not touched.

## 2.3 Architecture Detection Code Updates

> **Output: update `graviton-validation/04-code-scan-findings.md`** (Changes Applied)

Add Arm64 handling to all architecture detection (the resolver in §2.1 is one case). For x86 hardware intrinsics, check `IsSupported` before every call and keep a portable path; `Vector128` is accelerated on Arm64:

```csharp
// Before: throws PlatformNotSupportedException on Arm64
var acc = Vector256<int>.Zero;
int i = 0;
for (; i + Vector256<int>.Count <= data.Length; i += Vector256<int>.Count)
{
    acc = Avx2.Add(acc, Vector256.Create(data, i));
}

// After: the AVX2 path where it exists, Vector128 elsewhere, then the scalar tail
int sum = 0;
int i = 0;
if (Avx2.IsSupported)
{
    var acc = Vector256<int>.Zero;
    for (; i + Vector256<int>.Count <= data.Length; i += Vector256<int>.Count)
    {
        acc = Avx2.Add(acc, Vector256.Create(data, i));
    }

    for (int k = 0; k < Vector256<int>.Count; k++)
    {
        sum += acc.GetElement(k);
    }
}
else if (Vector128.IsHardwareAccelerated)
{
    var acc = Vector128<int>.Zero;
    for (; i + Vector128<int>.Count <= data.Length; i += Vector128<int>.Count)
    {
        acc += Vector128.Create(data, i);
    }

    sum += Vector128.Sum(acc);
}

for (; i < data.Length; i++)
{
    sum += data[i];
}
```

Executed: the unchanged method threw `System.PlatformNotSupportedException: Operation is not supported on this platform.` in a linux/arm64 container; the changed one returned `5050` for 1 to 100 there and on x64. A method that is already guarded and only lacks an Arm64 path is not a blocker: it runs its fallback, and a faster path is a recommendation (§2.5).

**Tests that assert an x64 environment** are test defects: fix the test, not the code.

```csharp
// Before
public void Runs_on_the_build_fleet() => Assert.Equal("linux-x64", RuntimeInformation.RuntimeIdentifier);

// After
public void Runs_on_the_build_fleet() => Assert.Contains(RuntimeInformation.RuntimeIdentifier, new[] { "linux-x64", "linux-arm64" });
```

Shell scripts get the same treatment; map `uname -m` to the artifact naming the vendor uses:

```bash
case "$(uname -m)" in
  x86_64 | aarch64) ARCH=$(uname -m) ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
curl -sSL -o /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip"
```

The AWS CLI names its installers by `uname -m`, and `awscli-exe-linux-aarch64.zip` answered HTTP 200. Change only the architecture handling. If a vendor publishes no arm64 asset, the item stays a user decision.

For Windows-only APIs, apply the replacements in [../document_references/windows-to-linux.md](../document_references/windows-to-linux.md) §2.

## 2.4 Build Configuration Updates

**Project settings:**
- Remove `<PlatformTarget>x64</PlatformTarget>` (and `x86`) where a file sets it: the default AnyCPU runs on both architectures. An evaluated `x64` with no such element comes from `RuntimeIdentifier` (next item). Executed: with it, `publish -r linux-arm64` stopped at `NETSDK1032: The RuntimeIdentifier platform 'linux-arm64' and the PlatformTarget 'x64' must be compatible.`, and a build without a RID ran until arm64 failed to load the assembly.
- Remove a `<RuntimeIdentifier>linux-x64</RuntimeIdentifier>` (or a Windows RID) that only exists to pick the build fleet's architecture; pass the RID at publish time (`-r linux-arm64`, or `-a` in a Dockerfile). Executed: with it in the API project, a publish without `-r` produced an x86-64 apphost and x86-64 natives.
- Add the target RID to `<RuntimeIdentifiers>` and regenerate lock files (§2.2).
- **Native AOT** (`<PublishAot>true</PublishAot>`): the compiler and linker run on the build host. Publishing linux-arm64 from x64 without a cross toolchain failed with `gcc : error : unrecognized command-line option ‘--target=aarch64-linux-gnu’`; Microsoft documents cross-compiling "As long as the necessary native toolchain is installed" ([Native AOT cross-compilation](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/cross-compile)). Publish Native AOT binaries for arm64 on arm64 hardware; nothing in the project file changes. On Graviton4 (Amazon Linux 2023), the publish first failed with `error : Platform linker ('clang' or 'gcc') not found in PATH. Ensure you have all the required prerequisites documented at https://aka.ms/nativeaot-prerequisites.`; Microsoft lists `clang zlib-devel zlib-ng-devel zlib-ng-compat-devel` for RHEL ([Native AOT prerequisites](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/#prerequisites)), Amazon Linux 2023 has the first two, and after `dnf install clang zlib-devel` the publish succeeded and the aarch64 executable ran. For Lambda, AWS documents compiling Native AOT functions on Amazon Linux 2023 with the function's architecture ([Lambda Native AOT](https://docs.aws.amazon.com/lambda/latest/dg/dotnet-native-aot.html)).

**Dockerfile updates (containerized deployments only):**

PRESERVE the current base image distribution and version. Do NOT change the .NET version or the image tag.

> **Skill config:** If `skill-config.md` defines `container.base_image_registry`, redirect the base image(s) to pull from that registry/namespace while keeping the SAME distribution and version (e.g. `mcr.microsoft.com/dotnet/aspnet:8.0` → `<registry>/dotnet/aspnet:8.0`). If absent, leave the existing registry unchanged. **Verify the mirror is reachable before redirecting**: if the configured registry does not resolve or pull from the build host, do NOT rewrite the `FROM`; keep the original registry and record the skipped redirect in `01-project-assessment.md`. **If the project ships no Dockerfile/container assets**, record "container config supplied but not applicable (no container assets)" in `01-project-assessment.md`. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Single-stage (the whole image is the deployable artifact):
```dockerfile
# Omit --platform and let the build's --platform linux/arm64 drive it.
FROM <current-base-image>:<current-version>
```

Multi-stage (an SDK stage publishes, the runtime stage copies the output):
```dockerfile
# Builder: $BUILDPLATFORM, because dotnet publish compiles IL and copies the RID's package files;
# -a $TARGETARCH selects the RID (Docker passes amd64 or arm64)
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:8.0 AS build
ARG TARGETARCH
WORKDIR /src
COPY . .
RUN dotnet publish src/Fixture.Api/Fixture.Api.csproj -c Release -a $TARGETARCH --self-contained false -o /app

# Runtime: no --platform pin
FROM mcr.microsoft.com/dotnet/aspnet:8.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
ENTRYPOINT ["./Fixture.Api"]
```

This is Microsoft's pattern: "Use $BUILDPLATFORM and $TARGETARCH environment variables in your Dockerfile to get the SDK to run natively and cross-compile/publish" ([.NET Blog](https://devblogs.microsoft.com/dotnet/improving-multiplatform-container-support/)). `dotnet publish -a amd64` was accepted, so the same Dockerfile builds both architectures. Executed with `docker build --platform linux/arm64` on the x86 host:
- **Before** (`FROM --platform=linux/amd64 ... AS build` and `-r linux-x64`): the build exited 0 in 27 seconds (the runtime stage's `apt-get` ran under emulation) and `docker image inspect` reported `arm64 linux`, but a scan of the image's `/app` found an x86-64 apphost, x64 assemblies and x86-64 natives, and the container stopped at once: `[FATAL tini (7)] exec ./Fixture.Api failed: No such file or directory` (exit 127). The x86-64 apphost looks for the x86-64 dynamic loader, which an arm64 image does not have. On an arm64 build host without emulation (Graviton4, Docker 25.0.16 with BuildKit), the same Dockerfile did not build: the amd64 SDK stage stopped at `exec /bin/sh: exec format error`.
- **After:** the build took 10 seconds (it reused the runtime layer), the scan found only aarch64 natives and AnyCPU or arm64 assemblies (plus the x64 `libfastsum.so` reported as a `NOTE` beside its aarch64 build), and `GET /health` answered `{"status":"ok","arch":"Arm64"}`.

Key rules:
- **An SDK stage on `$BUILDPLATFORM` is valid only while it compiles managed code and copies package files.** Anything that compiles native code (Native AOT, `RUN gcc`, a native build script) or runs the published application must run on the target platform.
- **Never pin `-r linux-x64` (or `--platform=linux/amd64`) in a stage whose output ships.** Never accept image metadata as proof of architecture; check inside the image (Phase 3.1).
- **Tests in a builder stage run on the builder's platform.** On an x86 build host they run on x86 and prove nothing about arm64; run them as described in Phase 3.2.
- Keep OS packages the runtime stage installs; Phase 1.2.2 checked that they exist for arm64.

Host-based deployments skip Docker steps.

**Lambda functions (only if the project already ships the template or tool defaults):** set the architecture to arm64 in both places the Linux solution uses, and the runtime when Phase 1.5 found that the current one blocks updates:

```yaml
# template.yaml
      Runtime: dotnet10         # was dotnetcore3.1 (updates blocked since May 3, 2023)
      Architectures:
        - arm64                 # was x86_64
```

```json
"function-runtime": "dotnet10",
"function-architecture": "arm64",
```

(the second block is the two changed lines of `aws-lambda-tools-defaults.json`). Do not add a template the project does not have. [Lambda instruction set architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html) documents the `arm64` value. The deployment itself is confirmed on AWS Lambda in Phase 3.3. Amazon.Lambda.Tools 7.0.0 publishes with `--runtime linux-arm64` for an `arm64` function, so a `<PlatformTarget>x64</PlatformTarget>` left in a referenced project stops `dotnet lambda package` at `NETSDK1032`.

**Deployment manifests (only if the project already ships them):**

If the project contains Kubernetes/Helm manifests (or similar deployment descriptors), ensure they can schedule onto ARM64 nodes. Only touch node selection, image registry, and ingress vocabulary; do NOT restructure manifests or add resources the project does not already have. If no manifests are present, skip this step.

> **Skill config:** If `skill-config.md` defines `deploy.arch_selector` / `deploy.nodepool_label` / `deploy.registry` / `deploy.ingress_convention`, use those values for the node selector, nodepool label, image registry, and ingress convention respectively. If absent, use a generic `kubernetes.io/arch: arm64` node selector and leave the existing registry/ingress unchanged. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

The Linux solution's `deploy/k8s/deployment.yaml` changed one line, `kubernetes.io/arch: amd64` to `kubernetes.io/arch: arm64`; the image it names must be built for linux/arm64 (or as a multi-architecture image) before the deployment can run.

**CI pipelines:** a CI system that publishes for `linux-x64` only, runs on Windows, or builds one image architecture is recorded with the change it needs (for example a `linux-arm64` publish, an arm64 runner for Native AOT, `docker buildx build --platform linux/amd64,linux/arm64`) as a recommendation in `00-summary.md`; the skill makes no CI changes itself (SKILL.md "User Responsibility").

## 2.5 Graviton-Specific Runtime Recommendations

> **Output: `graviton-validation/05-runtime-configuration.md`**

Do NOT apply runtime settings automatically. Document recommendations in the report for the team to evaluate during performance testing, each with its evidence level from the validation ladder in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md) and the exact source. Include only rows that apply to the project.

| Recommendation | Applies when | Level | Source |
|---|---|---|---|
| .NET 10 (LTS) for new Graviton workloads, or .NET 8 or 9 when an earlier supported release is needed; .NET 5, 6 and 7 are out of support | always (record the project's target frameworks; any change goes through `dotnet.framework_bump`) | A | [dotnet.md](https://github.com/aws/aws-graviton-getting-started/blob/main/dotnet.md#recommended-versions) and the README's [software updates table](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md#recent-software-updates-relevant-to-graviton) |
| A `Vector128` (or `Vector<T>`) path for code that has only an x86 intrinsics path and a scalar fallback: Microsoft calls `Vector128<T>` "the common denominator across every platform that supports vectorization" | code found by Phase 1.4 that runs its scalar fallback on Arm64 (on arm64, `Vector128` was accelerated and `Vector256` was not) | B, measure before adopting | [Microsoft Learn: SIMD](https://learn.microsoft.com/en-us/dotnet/standard/simd) |

Nothing else is recommended without a written source. In particular, do not recommend garbage collector modes, thread pool settings, tiered compilation or ReadyToRun changes for Graviton unless the project's own documentation or a cited source covers them.

The report should note the project's target frameworks and which rows apply; a project with no vectorized code gets the version row and "Not Applicable" for the rest.
