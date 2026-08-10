# Phase 3: ARM64 Validation & Testing

Build and test on ARM64 architecture. Supported platforms: Linux, macOS, WSL.

## Container Runtime Detection

Before skipping build validation, check for local container runtimes. Apple Silicon Macs run ARM64 containers natively via Docker or Finch, making full ARM64 validation possible without a remote Graviton instance.

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
- **x86 host + container runtime with ARM64 support:** Use `--platform linux/arm64` to build and validate. Docker Desktop and Finch on Apple Silicon support this natively. On x86 Linux, `docker buildx` with QEMU emulation may work but is slower.
- **x86 host + no container runtime:** Static analysis only. Document that ARM64 build validation requires an ARM64 environment and recommend the user run validation on a Graviton instance or ARM64 Mac.

**Do NOT skip build validation if a container runtime is available.** Even on macOS, if Docker or Finch is installed, attempt the ARM64 container build. Only recommend external validation as a last resort when no container runtime is found.

Throughout Phase 3, replace `docker` with `$CONTAINER_CMD` in all commands (e.g., `$CONTAINER_CMD build`, `$CONTAINER_CMD run`).

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

## 3.3 Startup Validation

> **Output: update `graviton-validation/06-build-test-results.md`** (Startup Validation)

Verify:
1. Application starts without errors
2. JVM flags accepted without errors
3. No immediate runtime crashes

> **macOS-host false FAIL.** When running host-based startup/tests on an Apple-Silicon Mac (`os.name=Mac, os.arch=aarch64`), a runtime-extracting native lib may load its `Linux/aarch64` binary fine on Graviton yet throw on macOS because the resolved JAR has no *Mac*/aarch64 binary (e.g. snappy-java added `Mac/aarch64/libsnappyjava.dylib` only in 1.1.8.2; the minimal Graviton floor 1.1.2.2 has `Linux/aarch64` but not Mac). A native-load failure on the macOS host is a **host-dev artifact, not a Graviton verdict** when the JAR contains a verified `Linux/aarch64` binary (per §1.2.1) — confirm on a `linux/arm64` container, which is authoritative, rather than marking the migration FAILED. Same principle as the JNA darwin-aarch64 case in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md).

Recommend to user for independent testing: performance benchmarking, load testing, resource utilization measurement.

## Write Summary

> **Output: `graviton-validation/00-summary.md`**

After all phases complete, write the summary using the template from [../document_references/documentation-standards.md](../document_references/documentation-standards.md). This file consolidates exit criteria status and references (not duplicates) detail in files 01-06.
