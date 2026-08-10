# Phase 1: Static Compatibility Analysis

Analyze the project without making changes. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below runs `mvn` or `./gradlew`, substitute `build.maven_invocation` / `build.gradle_invocation` from `skill-config.md` if defined (e.g. `./mvnw`). If it specifies a Maven wrapper (`./mvnw`) that is not present, fall back to bare `mvn`. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`** and **`graviton-validation/raw/dependency-tree-full.txt`**

### Determine Deployment Type

- Dockerfile or container config present: **Containerized**
- systemd/init scripts or direct JAR/WAR: **Host-based**
- Some applications support both

### Detect Multi-Module Structure

- Maven: parent POM with `<modules>` section
- Gradle: `settings.gradle` / `settings.gradle.kts` with `include` directives
- If multi-module: enumerate all submodules, analyze each independently
- Native libraries may reside in child modules; do NOT limit to root build file

### Generate Dependency Tree

> **If this first build-tool call fails** because the default JVM is newer than the project's build tooling supports (annotation processors, old Maven/Gradle), apply the session-scoped JDK switch from [phase3-validation.md](phase3-validation.md) §3.0 *now* — that guidance is needed here at the first `mvn`/`gradle` invocation, not only in Phase 3.

```bash
# Maven — REDIRECT stdout (do NOT use -DoutputFile: in a multi-module reactor it writes a
# SEPARATE tree per module, leaving the root file with only the parent-pom line — a false
# all-clear). A redirect captures the aggregated reactor tree. Avoid `-q` (suppresses the tree).
mvn dependency:tree -DoutputType=text --no-transfer-progress \
  > graviton-validation/raw/dependency-tree-full.txt

# Gradle
./gradlew dependencies --configuration runtimeClasspath --console=plain \
  > graviton-validation/raw/dependency-tree-full.txt

# Sanity check: the tree must contain real dependency lines, not just the project/parent pom.
# A merely non-empty file is NOT sufficient (a reactor root or a failed build can produce a
# file with no actual dependencies) — assert at least one resolved artifact coordinate.
grep -q ':jar:\|:war:\|--- ' graviton-validation/raw/dependency-tree-full.txt \
  || echo "WARNING: dependency tree has no resolved artifacts — for a multi-module reactor run 'mvn install -DskipTests' first, and confirm the build succeeded (and that you did not pass -q or -DoutputFile)."
```

### Categorize Components by Risk

- **CRITICAL**: Native code (JNI/JNA), .so files, architecture-specific optimizations
- **HIGH**: Dependencies with known x86-only versions, crypto libraries
- **MEDIUM**: Build configs, deployment scripts, architecture detection code
- **LOW**: Pure Java code without architecture dependencies

## 1.2 Native Library Validation (.so File Analysis)

> **Output: `graviton-validation/02-native-library-report.md`**

Native libraries incompatible with ARM64 exist in two forms: **statically bundled** inside JARs and **dynamically extracted at runtime**. Both must be validated.

### 1.2.1 Statically Bundled .so Scanning

Native libraries live inside the **resolved dependency JARs**, not the project source tree. Those JARs are in the local repository cache (`~/.m2/repository` for Maven, `~/.gradle/caches` for Gradle), and in any built fat/uber JAR under `target/`/`build/`. **Do not restrict the scan to the project tree, and do NOT exclude `target/`/`build/`** — that is exactly where the shippable artifacts are.

**Preflight — the scan needs `unzip` and `file`.** Without them it silently emits nothing, which is indistinguishable from "no native libraries found" — a false all-clear. The Maven/Gradle base images this skill steers toward (`maven:3.9-eclipse-temurin-17`, `gradle:8-jdk17`, etc.) ship **neither**. Check first, and install them (`yum`/`apt`/`microdnf install unzip file`) if missing:

```bash
command -v unzip >/dev/null && command -v file >/dev/null \
  || echo "WARN: 'unzip' and/or 'file' missing — the native scan silently under-reports without them. Install both (yum/apt/microdnf) before trusting a 'no native libraries' result."
```

First, materialize the resolved dependencies so every JAR the app actually uses is in one place:

```bash
# Maven — copy all resolved dependency JARs into target/deps.
# Multi-module reactor: run `mvn install -DskipTests` first, or copy-dependencies fails on the
# first child that depends on a not-yet-installed sibling.
mvn -q dependency:copy-dependencies -DoutputDirectory=target/deps

# Gradle — resolve the runtime classpath into build/deps.
# Write the init script to a real temp FILE first — Gradle rejects `-I /dev/stdin`
# ("The specified initialization script /dev/stdin is not a file") on 8.x.
init=$(mktemp /tmp/graviton-init.XXXXXX.gradle)
cat > "$init" <<'EOF'
allprojects {
  tasks.register('copyGravitonDeps', Copy) {
    from configurations.findByName('runtimeClasspath')
    into "$buildDir/deps"
  }
}
EOF
./gradlew -q --console=plain -I "$init" copyGravitonDeps
rm -f "$init"
```

Then scan every resolved JAR — the materialized deps plus any built fat JAR under `target/`/`build/` — for native libraries of **any** extension, recursing into nested JARs, and validate each `.so`'s architecture. Run this with `bash` (the loops below are written to work under both `bash` and `zsh`; **do not** rely on `for jar in $jars` — unquoted word-splitting differs between shells and silently scans nothing under zsh, the macOS default):

```bash
#!/usr/bin/env bash
scan_archive() {  # $1 = path to a .jar/.war/.ear on disk
  local archive="$1" d; d=$(mktemp -d)
  unzip -q -o "$archive" -d "$d" 2>/dev/null
  # Native libs bundled directly (any platform extension)
  find "$d" \( -name "*.so" -o -name "*.dll" -o -name "*.dylib" -o -name "*.jnilib" \) -print0 |
    while IFS= read -r -d '' lib; do
      echo "  [native] $archive -> ${lib#"$d"/}"
      case "$lib" in *.so) file "$lib" | sed 's/^/           /';; esac
    done
  # Recurse into nested archives (Spring Boot BOOT-INF/lib jars, WAR WEB-INF/lib jars,
  # EAR-of-WAR, shaded jars). Match .jar AND .war so an EAR bundling a WAR is fully walked.
  find "$d" \( -name "*.jar" -o -name "*.war" \) -print0 |
    while IFS= read -r -d '' nested; do scan_archive "$nested"; done
  rm -rf "$d"
}

# Scan the materialized deps plus built artifacts in the project tree. Match .jar/.war/.ear —
# a shippable target/*.war or *.ear is itself an archive that bundles native libs and must be
# fed to scan_archive (matching only *.jar silently skips a WAR-packaged app → false all-clear).
# NUL-delimited find + `while read` is portable across bash and zsh; no -path exclusions
# (fat/uber JARs live in target/ and build/). This scopes to the app's real dependencies —
# scanning all of ~/.m2 / ~/.gradle would add thousands of unrelated jars and drown the finding.
# `. ` already covers target/deps and build/deps (they live under it), so don't list them again
# — doing so double-lists every JAR (differing path prefixes defeat `sort -u`).
find . \( -name "*.jar" -o -name "*.war" -o -name "*.ear" \) -print0 2>/dev/null |
  while IFS= read -r -d '' ar; do scan_archive "$ar"; done | sort -u
```

If a dependency could not be materialized (offline/blocked `copy-dependencies`), fall back to scanning its JAR directly in the cache: `find "$HOME/.m2/repository" "$HOME/.gradle/caches" -name '<artifact>-*.jar' -print0 | while IFS= read -r -d '' jar; do scan_archive "$jar"; done` for the specific coordinates from the dependency tree — rather than sweeping the entire cache.

Any line whose `file` output says `ELF ... ARM aarch64` is ARM64-ready; a `.so` that is only `x86-64` (with no aarch64 sibling in the same JAR) is a blocker. Match `.so` paths for both `x86_64`/`amd64` and `aarch64`/`arm64` directories to decide multi-arch vs single-arch.

**Fat/Uber JAR types:** Spring Boot fat JARs nest native libs in `BOOT-INF/lib/*.jar`; WARs in `WEB-INF/lib/*.jar`; Maven Shade / Gradle Shadow flatten them into one JAR. The recursive `scan_archive` above covers all of these — the earlier version only unzipped one level and missed nested JARs.

### 1.2.2 Runtime-Extracted Native Library Detection

Some libraries extract native code at runtime rather than bundling .so files.

```bash
# Source code patterns. Scan from the project root (.) — NOT a hardcoded `src/`, which does
# not exist at a multi-module reactor root (sources live in child-module/src/) and would
# silently match nothing. --include="*.java" already limits the walk to source files.
grep -rn "Native.load\|Native.loadLibrary\|System.loadLibrary\|System.load(" \
  --include="*.java" . || true

grep -rn "jnr\.\|LibraryLoader" --include="*.java" . || true

# Build file dependencies known to extract native code (fast-path hint only — the §1.2.1
# content scan is authoritative. Note artifactIds vary: net.jpountz.lz4 uses artifactId "lz4",
# not "lz4-java", so match both.) Recurse so child-module build files are included.
grep -rnE "netty-transport-native|netty-tcnative|io\.grpc.*netty|conscrypt|jnr-ffi|jnr-posix|leveldbjni|rocksdbjni|sqlite-jdbc|lz4|zstd-jni|snappy-java|jansi|hawtjni|commons-crypto" \
  --include="pom.xml" --include="build.gradle" --include="build.gradle.kts" . 2>/dev/null || true
```

**Common runtime-extracting libraries** (this list is a *prompt*, not an allowlist — any JAR containing a native lib qualifies, including ones not named here such as `jansi`/`hawtjni`, `commons-crypto`, `jansi-native`):
- **Netty** (`netty-transport-native-epoll`, `netty-tcnative`): Extracts .so based on `os.arch`
- **Conscrypt**: Native crypto libraries at runtime
- **RocksDB** (`rocksdbjni`): Platform-specific .so at first use
- **SQLite JDBC** (`sqlite-jdbc`): Bundles and extracts native SQLite
- **LZ4/Zstd/Snappy** (`lz4-java`, `zstd-jni`, `snappy-java`): Native compression accelerators
- **LevelDB** (`leveldbjni`): Native key-value store bindings

**Do not rely on the named list alone.** The authoritative signal is the §1.2.1 content scan: any resolved JAR that contains a `.so`/`.dll`/`.dylib`/`.jnilib` extracts or loads native code and must be checked for an `aarch64` binary — whether or not its name appears above. The grep is only a fast-path hint; the content scan is what actually determines the finding.

For each native-bearing JAR found: check whether it includes a `linux/aarch64` binary (verify the JAR per §1.2.1 — never infer from the version number). If missing, flag as MUST UPGRADE. If a pure Java fallback exists (e.g., Netty NIO vs native epoll), document it.

### 1.2.3 Tiered Validation Policy

**FAIL immediately if:**
- .so shows x86-64 only AND no ARM64 version in JAR AND no source code available AND user cannot provide ARM64 version

**WARN but proceed if:**
- Multi-arch JAR with both x86 and ARM64, OR pure Java fallback exists, OR source available for recompilation

**PASS if:**
- .so shows "ARM aarch64" OR JAR contains .so in both `/linux/amd64/` and `/linux/aarch64/`

For x86-only .so files: check for source in repo, document recompilation needs, or prompt user. Validate with:
```bash
file libname.so  # Must show "ARM aarch64"
```

## 1.3 Dependency ARM64 Compatibility Analysis

> **Output: `graviton-validation/03-dependency-compatibility-report.md`** and **`graviton-validation/raw/dependency-tree-native.txt`**

**IMPORTANT:** ARM64-incompatible native code can be introduced through transitive dependencies. A pure Java direct dependency may pull in a transitive with native code. Analyze the full tree.

### Generate Filtered Tree

The `-Dincludes` / grep filters below are a convenience view of *well-known* native artifacts. They are NOT the source of truth — a native lib whose coordinates are not listed (e.g. `jansi`, `commons-crypto`) will not appear here. The authoritative native inventory is the §1.2.1 content scan of the resolved JARs; cross-check the two and treat any JAR the content scan flagged as in scope even if it is absent from this filtered tree.

```bash
# Maven — REDIRECT stdout here too, for the same reason as the full tree above
# (-DoutputFile writes a separate per-module file in a reactor → false all-clear).
mvn dependency:tree -Dincludes=net.java.dev.jna,io.netty,org.xerial.snappy,org.lz4,com.github.luben,org.rocksdb,org.xerial,org.conscrypt,com.google.protobuf \
  --no-transfer-progress \
  > graviton-validation/raw/dependency-tree-native.txt

# Gradle
./gradlew dependencies --configuration runtimeClasspath | grep -E "jna|netty-transport-native|snappy|lz4|zstd|rocksdb|sqlite|conscrypt|protobuf|jnr|leveldbjni" \
  > graviton-validation/raw/dependency-tree-native.txt
```

### Classify Each Dependency

**MUST UPGRADE (Blocking):** Current version lacks ARM64 binaries, contains x86-only native code, or has known critical ARM64 bugs.

**RECOMMENDED UPGRADE (Non-blocking):** ARM64 works but has known performance issues or bug fixes in newer version.

**COMPATIBLE (No action):** Full ARM64 support, no known issues, or pure Java with no architecture dependencies.

For transitive dependencies: identify which direct dependency pulls it in. Resolution may require updating the parent.

### Document Findings

```
Dependency: org.xerial.snappy:snappy-java (transitive via org.apache.kafka:kafka-clients)
Current Version: 1.1.1.7
Status: MUST UPGRADE
Reason: JAR contains no org/xerial/snappy/native/Linux/aarch64/libsnappyjava.so
Evidence: unzip -l snappy-java-1.1.1.7.jar | grep aarch64  → (no output)
Minimum ARM64 Version: 1.1.2.2
Resolution: dependencyManagement override or exclusion+re-add
```

> ⚠️ **Verify the JAR, never the version number.** Do not infer "old version → missing ARM64 binary." Confirm by inspecting the *resolved* artifact: `unzip -l <jar> | grep -i aarch64`, then `file` the extracted `.so` to confirm `ARM aarch64`. Counter-examples that look old but are already fine on Graviton: **JNA 5.6.0** ships `linux-aarch64/libjnidispatch.so` (COMPATIBLE — 5.8.0 only adds macOS/Windows ARM), and **snappy-java 1.1.2.2** (2016) already ships `Linux/aarch64/libsnappyjava.so` — about fifteen releases below the 1.1.4 usually assumed to be the floor. Only versions whose JAR genuinely lacks the `linux/aarch64` binary are MUST UPGRADE.
>
> Also make a **missing** artifact fail loudly: `curl` without `--fail` saves the 404 body, and `unzip -l | grep aarch64` on that non-archive returns empty — identical to a genuine "no aarch64 binary" result, i.e. a false MUST UPGRADE. Fetch with `curl -sSL --fail` (check the exit status) or run `unzip -t` first, and confirm the version is actually listed in `maven-metadata.xml` before trusting any grep output.

### Build-Tool Artifacts with OS/Arch Classifiers

Some build-time tools download a **platform-specific executable** that never appears in `dependency:tree` (it is resolved by a plugin, not as a normal dependency), so the steps above miss it entirely. The classic case: `protoc` pulled by `protobuf-maven-plugin`/`os-maven-plugin` via a classifier like `exe:${os.detected.classifier}`. If the pinned version has no `linux-aarch_64` classifier published, the build fails on Graviton with "Could not resolve artifact ...:exe:linux-aarch_64" — but only at build time.

Grep the build files for plugins/extensions that carry an OS/arch classifier and check the pinned versions:

```bash
grep -nE 'os-maven-plugin|protobuf-maven-plugin|os\.detected\.classifier|protocArtifact|:exe:|javacpp|jni' \
  pom.xml build.gradle build.gradle.kts 2>/dev/null || true
```

For each hit, verify on Maven Central that the *pinned* version actually publishes the classifier it will be asked for, before declaring it compatible. There is no local artifact to inspect here — the plugin resolves it at build time, so it is absent from both `dependency:tree` and the §1.2.1 content scan. Query the repository directly:

```bash
# Usage: central_has_classifier <group> <artifact> <version> <classifier>
# e.g.   central_has_classifier com.google.protobuf protoc 3.11.0 linux-aarch_64
central_has_classifier() {
  listing=$(curl -sS --max-time 20 \
    "https://repo1.maven.org/maven2/$(echo "$1" | tr '.' '/')/$2/$3/" 2>/dev/null)
  # Distinguish "query failed" from "classifier absent" — an empty listing is NOT evidence.
  if ! printf '%s' "$listing" | grep -q "$2-$3"; then
    echo "UNKNOWN — could not list $1:$2:$3 on Maven Central (network/proxy?). Do NOT record a verdict."
    return 2
  fi
  if printf '%s' "$listing" | grep -qE "href=\"$2-$3-$4\.(exe|jar|so|zip)\""; then
    echo "PRESENT — $1:$2:$3 publishes $4"
  else
    echo "ABSENT — $1:$2:$3 does NOT publish $4"
  fi
}
```

Match the classifier to the *target*, not the dev laptop: **Graviton is Linux, so `linux-aarch_64` is the classifier that decides the migration verdict.** `osx-aarch_64` matters only for local Apple-Silicon builds and is never a Graviton blocker.

Verified floors for `com.google.protobuf:protoc` (checked against repo1.maven.org):

| Classifier | First version publishing it | Applies to |
|---|---|---|
| `linux-aarch_64` | **3.5.0** | Graviton — this is the blocking floor |
| `osx-aarch_64` | **3.17.3** | Local Apple-Silicon builds only, non-blocking |

So **protoc ≥ 3.5.0 is already fine on Graviton**; 3.5.0 through 3.16.x all ship `linux-aarch_64`. Only 3.4.0 and earlier are genuinely x86-only (3.3.0 publishes just `linux/osx/windows-x86_32|x86_64`) → MUST UPGRADE, and per the minimality rule the target is **3.5.0**, not the latest. Do not treat "< 3.17" as the Linux floor — that is the macOS floor and using it forces ~12 needless minor-version bumps.

Also check **os-maven-plugin**: older releases mis-detect aarch64 → confirm it emits `linux-aarch_64` for `os.detected.classifier`. Bumping `protoc` via a shared `${protobuf.version}` property may also move `protobuf-java` — document that as a consequence of the required fix, not independent modernization.

## 1.4 Architecture-Specific Code Detection

> **Output: `graviton-validation/04-code-scan-findings.md`**

Scan the source tree for architecture-sensitive patterns:

Scan from the project root (`.`), NOT a hardcoded `src/` — at a multi-module reactor root `src/` does not exist (sources live in child-module/src/), so a `src/`-scoped grep silently finds nothing. `--include` limits the walk to source files.

```bash
# Locate every architecture/native touch-point with file:line
grep -rnE 'System\.getProperty\("os\.(arch|name)"\)|Native\.load|System\.loadLibrary|System\.load\(' \
  --include="*.java" --include="*.kt" . 2>/dev/null || true

# Flag the risky shape: a file that COMPARES against x86 but has no aarch64 COMPARISON.
# Match the token in a string/comparison context ("aarch64") rather than the bare word — a
# file with a genuine x86-only branch plus a comment like `// no aarch64 handling` would
# otherwise be wrongly cleared. This remains a heuristic: always eyeball the os.arch hits
# from the first grep, which is the authoritative signal.
grep -rlE '"(amd64|x86_64)"' --include="*.java" --include="*.kt" . 2>/dev/null \
  | xargs grep -LE '"aarch64"|"arm64"' 2>/dev/null   # files comparing amd64/x86_64 but NOT aarch64
```

Flag code that checks for "amd64" or "x86_64" without "aarch64" handling, loads native libraries without architecture-aware paths, or contains x86-specific assumptions.

## 1.5 Java Version Compatibility Check

> **Output: `graviton-validation/01-project-assessment.md`** (Java Environment section)

1. Document current Java version AND JDK distribution (e.g., "OpenJDK 21", "Corretto 17")
2. JDK 8: Supported with limitations. JDK 11+: Fully supported.
3. Flag known Graviton compatibility issues
4. **DO NOT change** the JDK distribution or Java version
5. All major distributions support ARM64 for Java 8+
