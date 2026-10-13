# Phase 3: ARM64 Validation & Testing

Build and test on ARM64 architecture. Supported platforms: Linux, macOS, WSL.

## Container Runtime Detection

Before skipping build validation, check for local container runtimes. A `linux/arm64` container runs natively on a Graviton host, under QEMU emulation on an x86 Linux host, and in a Linux VM on an Apple Silicon Mac's own cores. Only a run on Graviton passes a check ("Match the production hosts" below).

> **Skill config:** If `skill-config.md` defines `container.runtime`, pin `CONTAINER_CMD` to that value instead of running the auto-detection cascade below — but only after verifying it is installed; if the pinned runtime is not present, fall back to the auto-detection cascade. If `container.runtime` is absent, auto-detect as below. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

```bash
# Detect available container runtimes
CONTAINER_CMD=""
if command -v finch &>/dev/null; then
  CONTAINER_CMD="finch"
elif command -v docker &>/dev/null; then
  CONTAINER_CMD="docker"
elif command -v nerdctl &>/dev/null; then
  CONTAINER_CMD="nerdctl"
elif command -v podman &>/dev/null; then
  CONTAINER_CMD="podman"
fi

if [ -n "$CONTAINER_CMD" ]; then
  echo "Container runtime found: $CONTAINER_CMD"
else
  echo "No container runtime found"
fi

# Check host architecture
ARCH=$(uname -m)
echo "Host architecture: $ARCH"
```

**Decision logic:**
- **ARM64 host (aarch64/arm64) + container runtime:** Build and validate in containers using `$CONTAINER_CMD`. This is the ideal path.
- **ARM64 host (aarch64/arm64) + no container runtime:** Build and validate directly on host.
- **x86 host + container runtime with ARM64 support:** Use `--platform linux/arm64` to build and find failures early. On x86 Linux this runs under QEMU emulation, which is slower.
- **x86 host + no container runtime:** Static analysis only. Document that ARM64 build validation needs a Graviton host or the target, and recommend one.

**Do NOT skip the ARM64 container build if a container runtime is available.** Even on macOS, if Docker or Finch is installed, attempt it: it finds failures early. A pass there counts only after a run on Graviton (below).

**Match the production hosts.** A Phase 3 check passes only on a Graviton host with the production OS and page size, or on the target itself, such as the arm64 Lambda function. A `linux/arm64` run under emulation or on another arm64 machine finds failures early, but its CPU and kernel differ from Graviton's: QEMU on the x86 host used to validate this skill reported SVE with 512-bit vectors and SME, while Graviton2 has no SVE, Graviton3 has 256-bit SVE, Graviton4 and Graviton5 have 128-bit SVE and SVE2, and none has SME (measured on each; [processor table](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md#building-for-graviton)); Apple's M1 to M3 cores have no SVE, and the M4 has SME without SVE ([LLVM's processor definitions](https://github.com/llvm/llvm-project/blob/main/llvm/lib/Target/AArch64/AArch64Processors.td)); and a container uses its host's kernel, so a host whose page size is smaller than production's (an x86 host has 4KB pages; on a Mac, run `getconf PAGESIZE` in its VM) does not show the failures of 64KB pages. When the project ships native code it builds, run its tests on the oldest Graviton generation it deploys to: a newer generation does not show `Illegal instruction`. Record where each check ran in `06-build-test-results.md`.

Throughout Phase 3, replace `docker` with `$CONTAINER_CMD` in all commands (e.g., `$CONTAINER_CMD build`, `$CONTAINER_CMD run`). `CONTAINER_CMD` exists only in the shell that set it: if each command runs in a new shell, start a later block with `CONTAINER_CMD=<the detected runtime>`.

## 3.0 Build Environment Preparation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Environment sections)

### Java Runtime Alignment

Build-time tools (annotation processors, compiler plugins) may not support the latest Java compiler versions. Runtime compatibility != compile-time tooling compatibility.

**Common annotation processor sensitivities** (upper bound — the processor breaks on JDKs *newer* than this):
- **Lombok:** 1.18.20 needs build JDK ≤ **17** (fails on 21 *and* 25 with `NoSuchFieldError JCTree$JCImport.qualid`); ≥ 1.18.30 handles 21; < 1.18.36 fails on Java 25
- **MapStruct:** < 1.5.0 may fail with Java 17+
- **Dagger:** < 2.40 may fail with Java 16+

**If build fails with annotation processor errors:**
1. Identify processor from `<annotationProcessorPaths>` or `annotationProcessor` in build files
2. Check compatibility with current Java runtime
3. Apply session-scoped Java alignment below
4. Document the processor and version requiring alignment

**Choosing the build JDK — do NOT just pick the top of the "21 > 17 > 11" preference.** That preference is only a tiebreaker among JDKs the processor *supports*. Pick the **lowest installed LTS that is ≥ the project's declared target AND supported by the failing processor**; if the build still fails on it, **descend to the next lower LTS** and retry. Example: an app targeting Java 17 with Lombok 1.18.20 must build on JDK **17** — JDK 21 also fails, so blindly preferring 21 does not resolve it. This is a *build/validation* JDK choice only; the app's shipped Java version is unchanged (§1.5).

### Detect Project Target Version

Ask the build tool for the resolved value first; fall back to text extraction only when the project cannot build. Any text fallback must be POSIX-portable (`sed -nE` / `grep -oE`) — `grep -oP` (PCRE lookbehind) is GNU-only and silently returns empty on stock macOS/BSD, which this skill supports.

```bash
# Maven — ASK MAVEN FIRST. help:evaluate returns the fully resolved effective value, so it is
# immune to both tag-precedence ordering and to pretty-printed tags whose value sits on its own
# line. Do NOT anchor the match with ^...$ — Maven pads -DforceStdout output with whitespace.
PROJECT_TARGET=$(mvn help:evaluate -Dexpression=maven.compiler.release -q -DforceStdout 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)*' | head -1)
[ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(mvn help:evaluate -Dexpression=maven.compiler.target -q -DforceStdout 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)*' | head -1)

# Text fallback for when the project cannot build (or Maven is unavailable). Query each tag
# group in PRIORITY order with short-circuit fallback: release > target/source > java.version.
# Do NOT collapse these into one combined alternation + `head -1` — that returns whichever tag
# appears FIRST physically in the file (commonly <properties><java.version> before the <build>
# block), silently selecting the wrong build JDK (e.g. 21 when a <release>17 is authoritative).
# CAUTION: these patterns are line-based, so a multi-line <release>\n  17\n</release> is invisible
# to tier 1 and the chain then falls THROUGH to java.version and returns a confidently wrong
# number. That failure is silent — which is exactly why help:evaluate above is tried first.
if [ -z "$PROJECT_TARGET" ]; then
  mvn_tag() { sed -nE "s/.*<($1)>[[:space:]]*([0-9.]+)[[:space:]]*<.*/\2/p" pom.xml 2>/dev/null | head -1; }
  PROJECT_TARGET=$(mvn_tag 'maven\.compiler\.release|release')
  [ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(mvn_tag 'maven\.compiler\.target|target|maven\.compiler\.source|source')
  [ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(mvn_tag 'java\.version')
fi
# Maps legacy "1.8"/"1.5" to "8"/"5".
PROJECT_TARGET=${PROJECT_TARGET#1.}

# Gradle (Groovy)
if [ -z "$PROJECT_TARGET" ]; then
  PROJECT_TARGET=$(grep -oE '(sourceCompatibility|targetCompatibility)[[:space:]]*[=:][[:space:]]*['\''"]?(1\.)?[0-9]+' build.gradle 2>/dev/null | grep -oE '[0-9]+$' | head -1)
  [ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(grep -oE 'JavaVersion\.VERSION_(1_)?[0-9]+' build.gradle 2>/dev/null | grep -oE '[0-9]+$' | head -1)
  [ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(grep -oE 'jvmToolchain\([[:space:]]*[0-9]+' build.gradle 2>/dev/null | grep -oE '[0-9]+' | head -1)
fi

# Gradle (Kotlin DSL)
if [ -z "$PROJECT_TARGET" ]; then
  PROJECT_TARGET=$(grep -oE 'jvmToolchain\([0-9]+' build.gradle.kts 2>/dev/null | grep -oE '[0-9]+' | head -1)
  [ -z "$PROJECT_TARGET" ] && PROJECT_TARGET=$(grep -oE 'JavaLanguageVersion\.of\([0-9]+' build.gradle.kts 2>/dev/null | grep -oE '[0-9]+' | head -1)
fi

# gradle.properties fallback
if [ -z "$PROJECT_TARGET" ]; then
  PROJECT_TARGET=$(grep -oE 'javaVersion[[:space:]]*=[[:space:]]*[0-9]+' gradle.properties 2>/dev/null | grep -oE '[0-9]+$' | head -1)
fi

echo "Project targets Java: $PROJECT_TARGET"
```

### Session-Scoped Java Switching

If runtime significantly exceeds target (e.g., Java 25 with Java 17 target), use subshells:

```bash
# macOS
(
  export JAVA_HOME=$(/usr/libexec/java_home -v 21)
  export PATH="$JAVA_HOME/bin:$PATH"   # required: without this, `java`/`javac` still resolve to the shell-default JDK
  java -version                         # now reflects the switched JDK, not the default
  ${BUILD_CMD} clean install
)

# Linux
JAVA_21_HOME=$(find /usr/lib/jvm /usr/java -maxdepth 1 -type d \( -name "*java-21*" -o -name "*jdk-21*" -o -name "*corretto-21*" \) 2>/dev/null | head -1)
(
  export JAVA_HOME="$JAVA_21_HOME"
  export PATH="$JAVA_HOME/bin:$PATH"
  java -version
  ${BUILD_CMD} clean install
)

# SDKMAN
(
  source "$HOME/.sdkman/bin/sdkman-init.sh"
  sdk use java 21.0.9-amzn
  ${BUILD_CMD} clean install
)

# Single-command scope (any Unix)
JAVA_HOME=/path/to/java-21 ${BUILD_CMD} clean install
```

**ALLOWED:** `export JAVA_HOME` in subshells `()`, single-command env, `bash -c`, SDKMAN `sdk use`.

**FORBIDDEN:** Writing to `~/.zshrc`/`~/.bash_profile`/`~/.bashrc`, `update-alternatives --set`, `sdk default`, any persistent changes.

**Version preference:** Java 21 > 17 > 11. After transformation, user's `java -version` must match pre-transformation.

> **Skill config:** If `skill-config.md` defines `jdk.preferred_distribution` / `jdk.discovery_glob` / `jdk.version_select`, use them to locate the build/validation JDK instead of the defaults below. This selects only the JDK used to build and validate — the application's shipped distribution is unchanged. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

**If no compatible version found:** Document requirement, provide install commands, do NOT install automatically. Use `jdk.install_hint` from `skill-config.md` if defined; otherwise the defaults below:
```bash
# Amazon Corretto
# macOS: brew install --cask corretto@21
# Amazon Linux/RHEL: sudo yum install java-21-amazon-corretto-devel
# Ubuntu/Debian: see apt.corretto.aws setup
```

## 3.1 ARM64 Build Validation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Attempts, Test Failure Classification)

### Build Strategy

> **Skill config:** Substitute `build.maven_invocation` / `build.gradle_invocation` from `skill-config.md` for the `mvn` / `./gradlew` commands below if defined (e.g. `./mvnw`), falling back to the bare command if the specified wrapper is not present. Also applies to the `${BUILD_CMD}` used in §3.0 and the test commands in §3.2. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

1. **First attempt** - full build with tests:
   - Gradle: `./gradlew clean build`
   - Maven: `mvn clean install`

2. **If tests fail**, classify root cause:
   - `INFRA` - Missing DB, Docker, env vars (non-blocking)
   - `ARM64` - Architecture failure (blocking)
   - `PRE-EXISTING` - Existed before migration (non-blocking)

3. **INFRA or PRE-EXISTING failures:** Document, then build without tests:
   - Gradle: `./gradlew clean build -x test`
   - Maven: `mvn clean install -DskipTests`
   - This becomes the **final build**

4. **ARM64 failures:** Do NOT skip tests. Build fails, requires resolution.

The final build command determines the build score.

### Container Validation (if containerized)

**Docker ENTRYPOINT handling:** Override entrypoint for validation commands.
- Wrong: `$CONTAINER_CMD run app:arm64 java -version` (appends to entrypoint)
- Correct: `$CONTAINER_CMD run --entrypoint java app:arm64 -version`

```bash
# Build
$CONTAINER_CMD build --platform linux/arm64 -t app:arm64 .

# Validate architecture
$CONTAINER_CMD run --rm --platform linux/arm64 --entrypoint java app:arm64 -version
$CONTAINER_CMD run --rm --platform linux/arm64 --entrypoint java app:arm64 -XshowSettings:properties -version 2>&1 | grep os.arch
# Must show: os.arch = aarch64
```

Verify output shows the SAME JDK distribution and version as the original application.

### Host-Based Validation

```bash
java -version  # Verify same distribution and version
java -XshowSettings:properties -version | grep os.arch  # Must show aarch64

./gradlew build  # or mvn clean package
```

## 3.2 Functional Testing on ARM64

> **Output: update `graviton-validation/06-build-test-results.md`**

**Containerized:** the shippable runtime image (§2.4) is **JRE-only** — it contains `app.jar` but no `mvn`/`gradlew`, no sources, and no `pom.xml`/`build.gradle`. Running `--entrypoint mvn app:arm64 test` against it fails with `exec: "mvn": executable file not found` / `no POM in this directory`. Run the ARM64 test suite one of two ways instead:

```bash
# Option A — build the multi-stage builder target for linux/arm64 and let its RUN step run tests
# (add `RUN mvn test` / `RUN ./gradlew test` to the builder stage, or a test-only stage pinned
# to --platform=$TARGETPLATFORM so tests execute on aarch64, not the build host's arch).
$CONTAINER_CMD build --platform linux/arm64 --target builder -t app:builder-arm64 .

# Option B — run tests in a build-tool container on linux/arm64 with the source mounted
# (use the SAME distribution/version as the project's base image tag):
$CONTAINER_CMD run --rm --platform linux/arm64 -v "$PWD":/app -w /app \
  --entrypoint mvn maven:3.9-eclipse-temurin-17 clean test
# or Gradle:
$CONTAINER_CMD run --rm --platform linux/arm64 -v "$PWD":/app -w /app \
  --entrypoint ./gradlew gradle:8-jdk17 test
```

> Note (finch/lima on macOS): `-v` bind mounts only work for host paths shared into the VM (`$HOME`, `/private`, `/Volumes`). A project under `/tmp` resolves to the VM's own tmpfs → empty `/app`; use `/private/tmp` or a path under `$HOME`, or `$CONTAINER_CMD build` (which streams the context) instead.

**Host-based:**
```bash
./gradlew test  # or mvn test
```

Classify all failures (INFRA/ARM64/PRE-EXISTING). Test architecture-specific functionality: native library loading, crypto operations, file I/O, multi-threading.

**Final build determination:**
- All tests pass: test build is final build
- INFRA/PRE-EXISTING failures: `./gradlew clean build -x test` or `mvn clean install -DskipTests`
- ARM64 failures: failing build is final build (do not skip tests)

### Results That Change Without Failing

Some differences between x86 and Graviton change a number without failing a build, a test that only checks that the code runs, or a startup. Run the project's numeric outputs, the files it writes and any hash of its results on the x86 baseline and on Graviton (the generation it deploys to), with the same inputs, and compare every value with the tolerance the project accepts. The repository's [numerical validation sample](https://github.com/aws/aws-graviton-getting-started/tree/main/sample-code/numerical-validation) shows the method: it writes every result on both hosts and reports how many differ and by how much, in absolute, relative and ULP (units in the last place) terms. Measured on Graviton2 to Graviton5 against an x86 host, all on Amazon Linux 2023:

- `java.lang.Math` is not defined to return the same bits on every platform, only results within 1 ULP of the exact result for these functions, and on JDK 11, 17 and 21 `Math.exp`, `log`, `pow` and `tan` differed from x86 in 3.6% to 10% of 200,000 values, by 1 ULP, and `Math.sin` in 3.3% on JDK 11 and in 8.6% on JDK 17 and 21, which on Graviton return other `sin` values than JDK 11. `StrictMath` gave the same bits on every host and JDK, as its specification requires (the fdlibm algorithms): use it where results must match across platforms. Java does not fuse `a * b + c` itself (only `Math.fma` does), and the language defines conversions of out-of-range values to `int`, so those matched.
- The NaN that an invalid operation produces is `fff8000000000000` on x86 and `7ff8000000000000` on Graviton, so a hash of raw result bytes changes even when every number matches. Measured with `Double.doubleToRawLongBits(0.0 / 0.0)` on JDK 11 and 21.
- C or C++ the project builds for JNI ([c-c++.md](https://github.com/aws/aws-graviton-getting-started/blob/main/c-c%2B%2B.md#signed-vs-unsigned-char)): `char` is signed on x86 and unsigned on arm64: summing the bytes of `"a\xc3\xa9b"` through `char` gave 47 on x86 and 559 on Graviton, and a `char c; while ((c = fgetc(f)) != EOF)` loop stopped at a `0xff` byte on x86 and never stopped on Graviton; `-fsigned-char`, or `int8_t` and `uint8_t`, keep the x86 behavior. GCC fuses `a * b + c` into one fused multiply-add on arm64 by default, and the x86-64-v2 target that Amazon Linux 2023 builds for has no such instruction: the sample's pricer, built with GCC 11.5, changed 71% of its million prices (largest absolute difference 4.7e-10); built with `-ffp-contract=off` on both hosts, 4.6% still differed (largest 3.5e-10), which the sample attributes to the math library. A float converted to an integer out of range is undefined in C and the hardware decides: `(int)1e10` gave -2147483648 on x86 and 2147483647 on Graviton. `long double` is the x87 80-bit format on x86-64 and IEEE 128-bit on arm64 Linux, both 16 bytes: one written on x86 as raw bytes read back on Graviton as 1.96e-4942, with no error.

To see which cause a difference comes from, rebuild the native code on the same Graviton host with one flag changed (`-fsigned-char`, then `-ffp-contract=off`) and compare again. Record each compared output in `06-build-test-results.md` (Results Compared With x86). A difference within the project's tolerance is COMPATIBLE with that note. A larger one is an ARM64 finding, fixed at its cause: the C fixes above for JNI code; `StrictMath` where `Math` results must match across platforms; NaNs compared by value, not by raw bits. A test that compares floating-point values exactly and fails by such a difference goes under User Decisions Pending with the measured size and the Recommendation to change nothing until the project's owners accept a tolerance, which is also what an unattended run does.

## 3.3 Startup Validation

> **Output: update `graviton-validation/06-build-test-results.md`** (Startup Validation)

Verify:
1. Application starts without errors
2. The project's existing JVM options (start scripts, Dockerfile, `JAVA_TOOL_OPTIONS`) accepted without errors; an x86-only option such as `-XX:UseAVX=2` stops the JVM on ARM64 with `Unrecognized VM option`
3. No immediate runtime crashes
4. The native libraries the x86 baseline loads are loaded on ARM64 too, including the CHECK items from Phase 1.2 (the loaded check below)

```bash
# Loaded check (JDK 9 and later): the native libraries the JVM loaded, from its own log. Run the project's start
# command, or its tests, the same way on the x86 baseline and on ARM64, long enough to reach the code that loads them.
JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }-Xlog:os=info" timeout 120 java -jar target/app.jar \
  > "graviton-validation/raw/loaded-$(uname -m).txt" 2>&1
grep -E 'shared library load of .* was successful' "graviton-validation/raw/loaded-$(uname -m).txt" |
  sed -E 's#.* load of ##; s# was successful.*##; s#[0-9]{5,}#<n>#g' | sort -u
```

Compare the two lists without the JDK's own libraries (its `lib/` folder; the x86 JDK also loads `libjsvml.so`, which the ARM64 JDK does not have). A library the x86 run loads that the ARM64 run does not is a finding with its Phase 1.2 cause, or the user's recorded decision to keep the pure Java path. Executed with netty-transport-native-epoll 4.1.138: with only the `linux-x86_64` classifier JAR, the x86 run listed `/tmp/libnetty_transport_native_epoll_x86_<n>.so` and the arm64 run no Netty library; with the `linux-aarch_64` classifier JAR the arm64 run listed `/tmp/libnetty_transport_native_epoll_aarch_<n>.so`. In a container, pass the option with `-e JAVA_TOOL_OPTIONS=-Xlog:os=info`. JDK 8 has no `-Xlog` (`Unrecognized option: -Xlog:os=info`); there, list the files the running JVM has mapped with `grep -oE '/[^ ]+\.so[^ ]*( \(deleted\))?$' /proc/<pid>/maps | sort -u`, where a library its loader extracted and then deleted, as Netty does, ends in `(deleted)`.

> **macOS-host false FAIL.** When running host-based startup/tests on an Apple-Silicon Mac (`os.name=Mac, os.arch=aarch64`), a runtime-extracting native lib may load its `Linux/aarch64` binary fine on Graviton yet throw on macOS because the resolved JAR has no *Mac*/aarch64 binary (e.g. snappy-java added `Mac/aarch64/libsnappyjava.dylib` only in 1.1.8.2; the minimal Graviton floor 1.1.2.2 has `Linux/aarch64` but not Mac). A native-load failure on the macOS host is a **host-dev artifact, not a Graviton verdict** when the JAR contains a verified `Linux/aarch64` binary (per §1.2.1); check in a `linux/arm64` container instead, and settle the check on a Graviton host ("Match the production hosts"), rather than marking the migration FAILED. Same principle as the JNA darwin-aarch64 case in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md).

Recommend to user for independent testing: performance benchmarking, load testing, resource utilization measurement.

## Write Summary

> **Output: `graviton-validation/00-summary.md`**

After all phases complete, write the summary using the template from [../document_references/documentation-standards.md](../document_references/documentation-standards.md). This file consolidates exit criteria status and references (not duplicates) detail in files 01-06.
