# Phase 3: ARM64 Validation & Testing

Build, publish and test for ARM64. Supported platforms: Linux, macOS, WSL.

## Contents

- Container Runtime Detection
- 3.0 Build Environment Preparation: .NET SDK Alignment; Detect Project Target Version; Session-Scoped .NET Switching
- 3.1 ARM64 Build Validation: Build Strategy; Container Validation; Host-Based Validation
- 3.2 Functional Testing on ARM64: Results That Change Without Failing
- 3.3 Startup Validation
- Write Summary

## Container Runtime Detection

Before skipping validation, check for a container runtime that can run `linux/arm64` images. Graviton hosts run them natively, x86 Linux hosts through QEMU emulation, and an Apple Silicon Mac in a Linux VM on Apple's own cores. Only a run on Graviton passes a check ("Match the production hosts" below).

> **Skill config:** If `skill-config.md` defines `container.runtime`, pin `CONTAINER_CMD` to that value instead of running the auto-detection cascade below, but only after verifying it works; if the pinned runtime does not respond, fall back to the cascade. See [skill-configuration.md](skill-configuration.md).

```bash
# Host-side time limit: GNU timeout where it exists (Linux, WSL, Homebrew coreutils), else gtimeout, else Python.
host_timeout() {  # usage: host_timeout <seconds> <command...>; exit code 124 on timeout, like timeout(1)
  if command -v timeout >/dev/null 2>&1; then timeout -k 10 "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout -k 10 "$@"
  else python3 -c 'import subprocess, sys
try: sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired: sys.exit(124)' "$@"
  fi
}
typeset -f host_timeout > "${TMPDIR:-/tmp}/graviton-dotnet-host_timeout.sh"   # later blocks, perhaps in a new shell, load it from here

# Detect a WORKING container runtime. Being on PATH is not enough: a runtime can be installed
# but unusable (no daemon, no VM, missing permissions), so ask each one for `info`; one that has not answered in 20 seconds counts as unusable.
CONTAINER_CMD=""
for c in finch docker nerdctl podman; do
  if command -v "$c" >/dev/null 2>&1 && host_timeout 20 "$c" info >/dev/null 2>&1; then
    CONTAINER_CMD="$c"; break
  fi
done
echo "Container runtime: ${CONTAINER_CMD:-none}"

ARCH=$(uname -m)
echo "Host architecture: $ARCH"

# On an x86 host, confirm arm64 images actually run (QEMU/binfmt must be registered)
if [ -n "$CONTAINER_CMD" ] && [ "$ARCH" = "x86_64" ]; then
  $CONTAINER_CMD run --rm --init --platform linux/arm64 mcr.microsoft.com/dotnet/runtime-deps:8.0 timeout 30 uname -m   # must print aarch64
fi
```

A `command -v` cascade can pick a runtime that cannot run anything: on the x86 host used to validate this skill, `finch` was on PATH but `finch info` failed. After a reboot of that host, before QEMU was registered again, the same container printed `[FATAL tini (6)] exec timeout failed: Exec format error` and the block exited 1: the runtime works but has no ARM64 support. Registering emulation is a privileged change to the host that lasts until the next reboot, so ask the user before doing it; until then, follow the x86 host + no container runtime case below.

**Decision logic:**
- **ARM64 host (aarch64/arm64) + container runtime:** Publish, test and validate in containers using `$CONTAINER_CMD`. This is the ideal path.
- **ARM64 host (aarch64/arm64) + no container runtime:** Validate directly on the host with an SDK of the right version (§3.0).
- **x86 host + container runtime with ARM64 support:** Publish for linux-arm64 natively on the host and run the output with `--platform linux/arm64`. On x86 Linux this runs under QEMU emulation (see "Emulation limits" below).
- **x86 host + no container runtime:** Static analysis and native publishes with output scans only (Phase 1, §3.1). Document that ARM64 runtime validation needs a Graviton host or the target, and recommend one.

**Match the production hosts.** A Phase 3 check passes only on a Graviton host with the production OS and page size (Phase 1.1), or on the target itself, such as the arm64 Lambda function. A `linux/arm64` run under emulation or on another arm64 machine finds failures early, but its CPU and kernel differ from Graviton's: QEMU on an x86 host can report SVE with 512-bit vectors and SME, while Graviton2 has no SVE, Graviton3 has 256-bit SVE, Graviton4 and Graviton5 have 128-bit SVE and SVE2, and none has SME (measured on each); Apple's M1 to M3 cores have no SVE, and the M4 has SME without SVE ([LLVM's processor definitions](https://github.com/llvm/llvm-project/blob/main/llvm/lib/Target/AArch64/AArch64Processors.td)); and a container uses its host's kernel, so a host whose page size is smaller than production's (an x86 host has 4KB pages; on a Mac, run `getconf PAGESIZE` in its VM) does not show the failures of 64KB pages (a library aligned for 4KB pages failed on a 64KB-page AlmaLinux 8 host and loaded on a 4KB-page Graviton4 host; [nuget-native-assets.md](nuget-native-assets.md) §6). When the project ships native code it builds, run its tests on the oldest Graviton generation it deploys to: a newer generation does not show `Illegal instruction`. Record where each check ran, with the host's page size, in `06-build-test-results.md`.

**Do NOT skip validation if a working container runtime is available.** Only recommend external validation as a last resort.

Throughout Phase 3, replace `docker` with `$CONTAINER_CMD` in all commands. `CONTAINER_CMD` exists only in the shell that set it: if each command runs in a new shell, start a later block with `CONTAINER_CMD=<the detected runtime>`. `host_timeout` and `run_arm64` (below) are saved by their defining blocks to files under `${TMPDIR:-/tmp}`, and a later block that calls one loads it in its first line.

**Emulation limits (x86 host).** Microsoft's supported-OS lists say "The QEMU emulator is not supported to run .NET apps" ([.NET 8](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md)), so an emulated run is a smoke test, and the verdict for anything it cannot show comes from Graviton. Observed while validating this skill with Docker and QEMU registered through binfmt_misc:

- **Bound every container run, inside the container,** and remove the container afterwards (each `timeout` value in the blocks is an upper bound, so a stuck command fails instead of holding the session; raise it when a project needs longer):
  ```bash
  if . "${TMPDIR:-/tmp}/graviton-dotnet-host_timeout.sh"; then
    run_arm64() {  # usage: run_arm64 <seconds> <image> <command...>; extra docker options go in RUN_ARM64_OPTS (a string)
      local limit="$1" img="$2" name="graviton-check-$$"; shift 2
      # The options go through $(printf) so that zsh splits them too (zsh does not split ${RUN_ARM64_OPTS}).
      # shellcheck disable=SC2046
      host_timeout "$((limit + 20))" $CONTAINER_CMD run --rm --init --name "$name" --platform linux/arm64 $(printf '%s' "${RUN_ARM64_OPTS:-}") \
        --entrypoint timeout "$img" "$limit" sh -c "$*"
      local rc=$?
      $CONTAINER_CMD rm -f "$name" >/dev/null 2>&1   # no-op if the container already exited
      return $rc
    }
    typeset -f run_arm64 > "${TMPDIR:-/tmp}/graviton-dotnet-run_arm64.sh"   # later blocks, perhaps in a new shell, load it from here
  else echo "CHECK: run the Container Runtime Detection block first: it writes ${TMPDIR:-/tmp}/graviton-dotnet-host_timeout.sh"; fi
  ```
  The `--entrypoint timeout` form also works with images whose entrypoint is the application.
- **Do not compile under emulation.** `dotnet test` of a test project inside the arm64 SDK image was killed (`exit 137`) during its restore and build. Build and publish natively for linux-arm64 on the host (the SDK cross-targets managed code), and run only the result in the container.
- **x86-64 executables do not fail the way they fail on Graviton.** On an x86 host, the kernel runs an x86-64 executable directly even inside an arm64 container: Selenium Manager 4.48.0's x86-64 binary ran there, and an image whose apphost was x86-64 stopped with `exec ./Fixture.Api failed: No such file or directory` (the x86-64 loader is missing), not with an architecture error. On Graviton4 the same Selenium Manager binary did not start: bash reported `cannot execute binary file` (exit 126), and `execve` from a program failed with errno 8, `Exec format error`. Judge executables by content (§3.1) and on Graviton.

## 3.0 Build Environment Preparation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Environment sections)

### .NET SDK Alignment

The SDK compiles for any architecture, so the build host's architecture does not matter for managed code; the SDK version does. The SDK that `global.json` selects (Phase 1.1) must:
- **build the target frameworks:** SDK 8.0.425 stopped at `NETSDK1045: The current .NET SDK does not support targeting .NET 10.0.` for a `net10.0` project;
- **read the solution format:** SDK 8.0.425 rejected an `.slnx` solution (``Invalid solution `Orders.slnx`. Expected file header not found.``), which SDK 10.0.401 listed;
- **install the repository's tools:** Paket 10.3.1 installed under SDK 10.0.401 and failed under SDK 8.0.425.

The runtime the application runs on is a separate choice: an arm64 runtime image or host with the same major version as the target framework (`mcr.microsoft.com/dotnet/aspnet:8.0` for `net8.0`).

Build-time tools may not support the newest SDK or compiler; runtime compatibility != build-time tooling compatibility.

**If a build fails because of the SDK:**
1. Read the error code: `NETSDK1045` (target framework too new for the SDK), a `global.json` that names an SDK that is not installed (`A compatible .NET SDK was not found.`), or a solution or tool that needs a newer SDK
2. Find the SDK the repository expects (`global.json`, the CI configuration)
3. Apply the session-scoped switch below
4. Document the SDK used and why in `06-build-test-results.md`

### Detect Project Target Version

```bash
# The target frameworks the projects build (Phase 1.1), the SDK this repository selects, and the installed SDKs
grep -oE 'TargetFrameworks?=[^,]+' graviton-validation/raw/project-properties.txt | sort | uniq -c
find . \( -name .git -o -name node_modules \) -prune -o -name global.json -print | while IFS= read -r f; do echo "== $f"; cat "$f"; echo; done
echo "selected SDK: $(dotnet --version 2>&1 | head -n 1)"
dotnet --list-sdks
```

How `rollForward` chooses is in [package-management-mapping.md](package-management-mapping.md) §2.7.

### Session-Scoped .NET Switching

If the repository needs an SDK that is not installed, install it into a temporary folder with Microsoft's install script and use it in a subshell:

```bash
script="${TMPDIR:-/tmp}/dotnet-install.sh"
curl -fsSL -o "$script" https://dot.net/v1/dotnet-install.sh
SDK_DIR="${TMPDIR:-/tmp}/dotnet-sdk-8.0.425"
bash "$script" --version 8.0.425 --install-dir "$SDK_DIR"   # the version global.json asks for
(
  export DOTNET_ROOT="$SDK_DIR" PATH="$SDK_DIR:$PATH"
  dotnet --list-sdks          # now lists only the SDK in $SDK_DIR
  dotnet build -c Release     # the build, test and publish steps of 3.1 and 3.2
)
```

`bash "$script" --version 8.0.425 --install-dir "$SDK_DIR" --dry-run` prints the download URL without installing. The SDK image (`mcr.microsoft.com/dotnet/sdk:<version>`) is the other session-scoped option: run it on the host's own platform, not under emulation (see "Emulation limits"). On fresh Amazon Linux 2023 and AlmaLinux 8 instances, the installed SDK stopped at `Couldn't find a valid ICU package installed on the system. Please install libicu (or icu-libs) using your package manager and try again.`, and `dnf install libicu` fixed it.

**ALLOWED:** an SDK in a temporary folder used through `PATH` and `DOTNET_ROOT` in a subshell `()`, single-command environment variables, `bash -c`, the SDK container image.

**FORBIDDEN:** writing to `~/.zshrc`/`~/.bash_profile`/`~/.bashrc`, changing or deleting `global.json`, system-wide installs or package-manager installs without asking, any persistent change.

> **Skill config:** If `skill-config.md` defines `dotnet.sdk_select`, use that source for the validation SDK (an installed SDK, the install script, or the container image). This selects only the SDK used to build and validate; the repository's `global.json` and target frameworks are unchanged. See [skill-configuration.md](skill-configuration.md).

**If no matching SDK can be installed:** document the requirement and surface the install command; do NOT install automatically outside a temporary folder. Use `dotnet.install_hint` from `skill-config.md` if defined; otherwise point to Microsoft's install script above or the distribution's packages ([Install .NET on Linux](https://learn.microsoft.com/en-us/dotnet/core/install/linux)).

## 3.1 ARM64 Build Validation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Attempts, Test Failure Classification) and **`graviton-validation/raw/output-scan.txt`**

### Build Strategy

1. **First attempt** - restore, build and test as the repository does, natively on the host:
   - `dotnet restore <solution>` (with `--locked-mode` when the repository has `packages.lock.json` files)
   - `dotnet build <solution> -c Release --no-restore`
   - `dotnet test <solution> -c Release --no-build`

   For a solution that still contains Windows-only projects (Windows Forms, WPF), build the projects that move to Linux one by one: the whole solution stops at `NETSDK1100` on Linux.

2. **Publish every executable project for each target RID and scan the output by content.** A successful publish is not evidence: it exited 0 with native files missing and for a Windows Forms project (Phase 1). The scan is:

```bash
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
RID=linux-arm64   # each target RID from Phase 1.1 (for Alpine, also linux-musl-arm64)
mkdir -p graviton-validation/raw
# Keep tracked lock files as they are: locked mode when the repository has them (a RID they lack then fails with NU1004)
LOCK=false; [ -n "$(find . -name packages.lock.json -not -path '*/obj/*' -print 2>/dev/null | head -n 1)" ] && LOCK=true
# Executable projects from Phase 1.1 (OutputType Exe); test projects are covered in 3.2
grep -E 'OutputType=Exe' graviton-validation/raw/project-properties.txt | cut -d: -f1 |
  while IFS= read -r p; do
    name=$(basename "$p" | sed 's/\.[a-z]*proj$//')
    out="${TMPDIR:-/tmp}/graviton-publish/$RID/$name"
    rm -rf "$out"; mkdir -p "$out"
    dotnet publish "$p" -c Release -r "$RID" --self-contained false -p:RestoreLockedMode=$LOCK -o "$out" < /dev/null > "$out.log" 2>&1; rc=$?
    echo "== $name: publish exit $rc (log: $out.log)"
    if [ "$rc" -ne 0 ]; then
      grep -oE '(error|warning) [A-Z]+[0-9]+: [^[]{0,200}|error : [^[]{0,200}' "$out.log" | sort -u | head -n 3
      echo "NOT SCANNED: publish failed"; continue
    fi
    python3 "$GV_CHECK" scan --target-rid "$RID" "$out"
  done | tee graviton-validation/raw/output-scan.txt
```

A Native AOT project cross-published from x64 fails with `error : unrecognized command-line option ‘--target=aarch64-linux-gnu’` and is reported `NOT SCANNED: publish failed`: publish it on arm64 hardware (Phase 2.4), or record it as NOT RUN with the reason when none is available.

A Windows Forms tool (`OutputType=WinExe`) is a blocker and is not published.

The lock-file guard matters: an earlier validation publish for `linux-musl-arm64` without locked mode added that RID to three tracked `packages.lock.json` files, so they no longer matched the projects' `RuntimeIdentifiers`, a mismatch that locked mode rejects (`NU1004: The project's runtime identifiers have changed from ...`). A target RID enters the lock files in Phase 2.2, deliberately, or not at all.

3. **If tests fail**, classify root cause:
   - `INFRA` - Missing DB, services, credentials, feeds, OS packages in the test environment (non-blocking)
   - `ARM64` - Architecture failure (blocking)
   - `PRE-EXISTING` - Existed before migration (non-blocking)

4. **INFRA or PRE-EXISTING failures:** a failure is INFRA only with a cause that does not depend on the architecture: it fails the same way on the x86 baseline, or its message names a missing service, credential, feed or OS package. Document them, rerun the tests with only those excluded (`dotnet test <solution> --filter "FullyQualifiedName!~InfraTests"`), and list them under CHECK Items; that run, with the §3.1 publish and scan, becomes the **final build**. A build without tests is never the final build.

5. **ARM64 failures:** Do NOT skip tests. Build fails, requires resolution.

The final build command determines the build score.

**Errors that point away from the cause** (each seen while validating this skill):

| Symptom | Real cause |
|---|---|
| `DllNotFoundException: Unable to load shared library 'libSkiaSharp' or one of its dependencies` | no linux-arm64 native in the package (Phase 1.3), or a dependency of the native missing from the image: read the rest of the message (`libfontconfig.so.1: cannot open shared object file` was an OS package missing from the SDK image, an INFRA failure) |
| `FileNotFoundException: Could not load file or assembly 'Fixture.Legacy, Version=1.0.0.0, ...'` with the file present | the assembly was built for x64 (`PlatformTarget`) |
| `PlatformNotSupportedException: Operation is not supported on this platform.` | an x86 intrinsic (`Avx2.Add`) called without an `IsSupported` check, or DPAPI (`ProtectedData`), which is Windows only |
| `NETSDK1032: The RuntimeIdentifier platform 'linux-arm64' and the PlatformTarget 'x64' must be compatible.` | `PlatformTarget` pinned to x64 (Phase 2.4) |
| `You must install or update .NET to run this application.` with `Framework: 'Microsoft.WindowsDesktop.App'` | a Windows Forms or WPF project: a blocker, not a missing runtime |
| `TypeInitializationException: The type initializer for 'Microsoft.Data.Sqlite.SqliteConnection' threw an exception.` | a native that needs a newer glibc than the host has: the innermost exception is `DllNotFoundException: Unable to load shared library 'e_sqlite3'`, and `ldd` on the library names the missing `GLIBC_` version (Phase 1.1, target glibc) |
| `DllNotFoundException` with `ELF load command alignment not page-aligned` (glibc 2.34 and earlier) or `ELF load command address/offset not page-aligned` (glibc 2.35 and later) | a native linked for 4KB pages on a 64KB-page kernel (`scan --page-size 65536`) |
| `Platform linker ('clang' or 'gcc') not found in PATH` | the Native AOT prerequisites are missing on the build host (Phase 2.4) |
| `Couldn't find a valid ICU package installed on the system.` | the host or image has no ICU: install `libicu`, or use invariant globalization for the application ([windows-to-linux.md](windows-to-linux.md) §5) |
| `exec ./<app> failed: No such file or directory` in an arm64 image on an x86 host | an x86-64 apphost (its loader, `/lib64/ld-linux-x86-64.so.2`, is not in the arm64 image): the publish used `-r linux-x64` (Phase 2.4) |

### Container Validation (if containerized)

**Docker ENTRYPOINT handling:** Override entrypoint for validation commands.
- Wrong: `$CONTAINER_CMD run app:arm64 dotnet --info` (appends to the entrypoint)
- Correct: `$CONTAINER_CMD run --entrypoint dotnet app:arm64 --info`

```bash
# Build
$CONTAINER_CMD build --platform linux/arm64 -t app:arm64 .

# Validate the architecture INSIDE the image: the runtime, then every file the application ships
$CONTAINER_CMD run --rm --platform linux/arm64 --entrypoint timeout app:arm64 150 dotnet --info | grep -E 'Architecture|RID'
cid=$($CONTAINER_CMD create --platform linux/arm64 app:arm64)
rm -rf "${TMPDIR:-/tmp}/graviton-image-app"
$CONTAINER_CMD cp "$cid":/app "${TMPDIR:-/tmp}/graviton-image-app"
$CONTAINER_CMD rm -f "$cid" > /dev/null
GV_CHECK="${TMPDIR:-/tmp}/dotnet_graviton_check.py"
python3 "$GV_CHECK" scan "${TMPDIR:-/tmp}/graviton-image-app"   # the path the Dockerfile copies the application to
# Must show: Architecture: arm64, RID: linux-arm64, and no FINDING
```

An image built from a Dockerfile that pins the SDK stage to amd64 was reported by `docker image inspect` as `arm64 linux`, but the scan listed an x86-64 apphost, x64 assemblies and x86-64 natives: never accept image metadata as proof of architecture.

Verify the output shows the SAME .NET runtime major version and base image as the original application.

### Host-Based Validation

On a Graviton host (or in a linux/arm64 container on an arm64 host):

```bash
uname -m                                         # must show aarch64
dotnet --info | grep -E 'Architecture|RID'       # must show arm64 and linux-arm64
```

then the §3.1 build, publish and scan, and the tests in §3.2. The `dotnet --info` lines above came from the arm64 runtime image (`Architecture: arm64`, `RID: linux-arm64`).

## 3.2 Functional Testing on ARM64

> **Output: update `graviton-validation/06-build-test-results.md`**

**ARM64 host:** run the repository's tests as they are (`dotnet test <solution>`, or `dotnet.test_command` from `skill-config.md`).

**x86 host:** build the test project natively for linux-arm64 and run only the tests in the arm64 SDK image (Debian 12, glibc 2.36) or, for a target of another distribution, in its image with its .NET SDK package (Amazon Linux 2023: `dnf install -y dotnet-sdk-8.0`), with the OS packages the runtime image installs (Phase 1.2.2): a native library is judged by the target's glibc. A test stage in the Dockerfile pinned to `$TARGETPLATFORM` compiles under emulation, which was killed, so use it only on arm64 hosts.

```bash
if . "${TMPDIR:-/tmp}/graviton-dotnet-host_timeout.sh" && . "${TMPDIR:-/tmp}/graviton-dotnet-run_arm64.sh"; then
  TEST_PROJECT=tests/Fixture.Tests     # each test project
  OS_PACKAGES="libfontconfig1"         # what the runtime image installs (Phase 1.2.2); the SDK image lacks them
  out="${TMPDIR:-/tmp}/graviton-tests-arm64"
  rm -rf "$out"; mkdir -p "$out"
  LOCK=false; [ -n "$(find . -name packages.lock.json -not -path '*/obj/*' -print 2>/dev/null | head -n 1)" ] && LOCK=true
  # Native build for linux-arm64 (no emulation): compiling under emulation was killed (exit 137)
  dotnet build "$TEST_PROJECT" -c Release -r linux-arm64 --self-contained false -p:RestoreLockedMode=$LOCK -o "$out" < /dev/null > "$out.log" 2>&1; echo "build -r linux-arm64: exit $?"
  # Emulated on an x86 host, native on an arm64 host: only the tests run in the container (480 seconds bounds the
  # package install and the test run)
  RUN_ARM64_OPTS="-v $out:/t:ro -w /tmp" run_arm64 480 mcr.microsoft.com/dotnet/sdk:8.0 \
    "apt-get update -qq > /dev/null && apt-get install -y -qq --no-install-recommends $OS_PACKAGES > /dev/null && dotnet test /t/$(basename "$TEST_PROJECT").dll --results-directory /tmp/results"
  echo "tests on arm64: exit $?"
else echo "CHECK: run the Container Runtime Detection and Emulation limits blocks first: they write ${TMPDIR:-/tmp}/graviton-dotnet-host_timeout.sh and ${TMPDIR:-/tmp}/graviton-dotnet-run_arm64.sh"; fi
```

`run_arm64` and `host_timeout` come from "Container Runtime Detection" and "Emulation limits" above; the block's first line loads them. Without the OS package the thumbnail test failed with `DllNotFoundException` naming `libfontconfig.so.1` (INFRA: the test environment lacked a package the runtime image has).

**Code coverage.** Microsoft's [dotnet-coverage](https://learn.microsoft.com/en-us/dotnet/core/additional-tools/dotnet-coverage) page says "Dynamic instrumentation is available on Windows (x86, x64 and Arm64), Linux (x64), and macOS (x64)" and "Static instrumentation is available on all platforms", and the per-RID check reports Microsoft.CodeCoverage's x86-64 instrumentation libraries as a `CHECK` (Phase 1.3). On Graviton4 with Microsoft.CodeCoverage 17.11.1, `dotnet test <project> --collect "Code Coverage"` wrote a `.coverage` file with data, and `--collect "Code Coverage;Format=cobertura"` counted 227 of 3,369 lines covered, against 233 on x64; the only lines that differed were the architecture branches (the resolver's X64 and Arm64 arms, the AVX2 loops on x64, the Vector128 loop on arm64). So the `CHECK` closes when coverage runs this way on Graviton; record the result in `06-build-test-results.md`. Running a built test assembly (`dotnet test <dll>`) does not load the collector on any architecture (`Unable to find a datacollector with friendly name 'Code Coverage'` on x64 too), so it cannot answer this.

Classify all failures (INFRA/ARM64/PRE-EXISTING). Test architecture-specific functionality: native library loading, vectorized code, file paths, time zones and globalization in the target image, cryptography.

**Final build determination:**
- All tests pass: test build is final build
- INFRA/PRE-EXISTING failures: the test run with only those tests excluded (step 4), plus the §3.1 publish and scan
- ARM64 failures: failing build is final build (do not skip tests)

### Results That Change Without Failing

Apply this only when the project builds C or C++ code it calls through P/Invoke or writes raw floating-point bytes, or compares or hashes numeric results exactly. These differences change a value without an error:

- Out-of-range conversions from floating point to integers differ in C, C++ and .NET 8: a `double` that holds 1e10 at run time converts to `int` as -2147483648 on x64 and 2147483647 on Arm64 (in C and C++ the conversion is undefined, and a compiler folds a constant such as `(int)1e10` to a value of its own; in C# that constant does not compile, `CS0221`); .NET 9 and later make x64 saturate as Arm64 does ([breaking change](https://learn.microsoft.com/en-us/dotnet/core/compatibility/jit/9.0/fp-to-integer)).
- The NaN an invalid operation produces has other bits (`fff8000000000000` on x86, `7ff8000000000000` on Graviton): compare NaNs by value, not by raw bytes or hashes.
- In C or C++ called through P/Invoke: `char` is signed on x86 and unsigned on arm64, so code that relies on its sign (a `char c; while ((c = fgetc(f)) != EOF)` loop never ends on arm64) needs `-fsigned-char`, or `int8_t` and `uint8_t`; GCC fuses `a * b + c` into one multiply-add on arm64 by default, which an x86-64 build without FMA (x86-64-v3 adds it) cannot do, so build with `-ffp-contract=off` on both when results must keep x86's rounding (`-ffast-math` and `-Ofast` allow more such changes); and `long double` is the x87 80-bit format on x86-64 and IEEE 128-bit on arm64 Linux, both 16 bytes, so raw values written on one read back as other numbers on the other: regenerate such files on Graviton, or store `double` or text.

A test that compares floating-point values exactly and fails by such a difference goes under User Decisions Pending, with the Recommendation to change nothing until the project's owners accept a tolerance; an unattended run does the same.

## 3.3 Startup Validation

> **Output: update `graviton-validation/06-build-test-results.md`** (Startup Validation)

Verify:
1. Application starts without errors on linux/arm64 (`RuntimeInformation.ProcessArchitecture` reports `Arm64`)
2. Every native library the application uses loads (exercise the code paths that load them: a self-check command, health checks, the first requests)
3. No immediate runtime crashes, `DllNotFoundException`, `PlatformNotSupportedException` or `TypeInitializationException`
4. Where the application ships both architectures of a native file (an output-scan `NOTE`), the aarch64 one is the one loaded
5. On EC2 targets that require IMDSv2 (Amazon Linux 2023 by default), the AWS SDK obtains instance-role credentials
6. Lambda functions: deploy the arm64 function with the tool the project already uses (for example `dotnet lambda deploy-function` from Amazon.Lambda.Tools, or `sam deploy`) and invoke it

> **macOS-host false FAIL.** On an Apple Silicon Mac, a host-based run (outside containers) uses the `osx-arm64` RID: a package with a verified linux-arm64 native file (Phase 1.3) can still fail to load there because it has no osx-arm64 build. That is a host-development artifact, not a Graviton verdict; check in a `linux/arm64` container instead, and settle the check on a Graviton host ("Match the production hosts").

Recommend to user for independent testing: performance benchmarking, load testing, resource utilization measurement.

## Write Summary

> **Output: `graviton-validation/00-summary.md`**

After all phases complete, write the summary using the template from [documentation-standards.md](documentation-standards.md). This file consolidates exit criteria status and references (not duplicates) detail in files 01-06.
