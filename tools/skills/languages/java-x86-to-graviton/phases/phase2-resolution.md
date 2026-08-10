# Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues identified in Phase 1. Update ONLY what is required for ARM64 compatibility.

## 2.1 Native Library Resolution

> **Output: update `graviton-validation/02-native-library-report.md`** (Resolution Details, Pure Java Fallbacks)

For each x86-only .so identified in Phase 1:

**If source code available:**
```bash
# Cross-compilation
CC=aarch64-linux-gnu-gcc make

# Or on ARM64 machine (distro defaults are correct for Graviton)
make

# Verify
file libname.so  # Should show "ARM aarch64"
```

**If source unavailable:** Prompt user for ARM64-compatible version or confirm pure Java fallback.

**Update native library loading logic** to handle ARM64:
```java
String arch = System.getProperty("os.arch");
String libName;

if ("aarch64".equals(arch)) {
    libName = "libchatbot-arm64.so";
} else if ("amd64".equals(arch) || "x86_64".equals(arch)) {
    libName = "libchatbot-amd64.so";
} else {
    throw new UnsupportedOperationException("Unsupported architecture: " + arch);
}

try {
    nativeLib = (NativeLib) Native.load(libName, NativeLib.class);
} catch (UnsatisfiedLinkError e) {
    logger.warn("Native library not available, using Java fallback", e);
}
```

## 2.2 Dependency Compatibility Updates

> **Output: update `graviton-validation/03-dependency-compatibility-report.md`**

Update ONLY dependencies flagged as MUST UPGRADE (i.e. the resolved JAR was confirmed to lack the `linux/aarch64` binary — see the verification note in Phase 1.3). Do NOT upgrade compatible dependencies. Prefer the *lowest* version that includes the ARM64 binary, not the latest, to stay minimal — and **confirm that candidate's JAR actually contains the aarch64 binary** (`unzip -l | grep aarch64`) rather than trusting a remembered version number; the exact floor varies by library and some intermediate versions are unpublished.

**Direct dependencies (Maven):** e.g. snappy-java confirmed lacking `Linux/aarch64/libsnappyjava.so`:
```xml
<dependency>
    <groupId>org.xerial.snappy</groupId>
    <artifactId>snappy-java</artifactId>
    <version>1.1.2.2</version> <!-- a version verified to ship Linux/aarch64/libsnappyjava.so (confirm the chosen version's JAR) -->
</dependency>
```

**Transitive dependencies (Maven):** e.g. an old snappy-java pulled in via kafka-clients:
```xml
<!-- Option A: dependencyManagement override -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.xerial.snappy</groupId>
            <artifactId>snappy-java</artifactId>
            <version>1.1.2.2</version>
        </dependency>
    </dependencies>
</dependencyManagement>

<!-- Option B: Exclude and re-add -->
<dependency>
    <groupId>org.apache.kafka</groupId>
    <artifactId>kafka-clients</artifactId>
    <version>${kafka.version}</version>
    <exclusions>
        <exclusion>
            <groupId>org.xerial.snappy</groupId>
            <artifactId>snappy-java</artifactId>
        </exclusion>
    </exclusions>
</dependency>
<dependency>
    <groupId>org.xerial.snappy</groupId>
    <artifactId>snappy-java</artifactId>
    <version>1.1.2.2</version>
</dependency>
```

**Transitive dependencies (Gradle):**
```groovy
configurations.all {
    resolutionStrategy {
        force 'org.xerial.snappy:snappy-java:1.1.2.2'
    }
}
```

## 2.3 Architecture Detection Code Updates

> **Output: update `graviton-validation/04-code-scan-findings.md`** (Changes Applied)

Add `aarch64` handling to all architecture detection:
```java
// Before
if (System.getProperty("os.arch").equals("amd64")) {
    // x86-specific code
}

// After
String arch = System.getProperty("os.arch");
if ("aarch64".equals(arch)) {
    // ARM64-specific code path
} else if ("amd64".equals(arch) || "x86_64".equals(arch)) {
    // x86-specific code
} else {
    // Generic fallback
}
```

## 2.4 Build Configuration Updates

**Maven ARM64 profile:**
```xml
<profiles>
    <profile>
        <id>arm64</id>
        <activation>
            <os><arch>aarch64</arch></os>
        </activation>
        <properties>
            <native.arch>aarch64</native.arch>
        </properties>
    </profile>
</profiles>
```

**Dockerfile updates (containerized deployments only):**

PRESERVE the current base image distribution and version. Do NOT change JDK distribution or version.

> **Skill config:** If `skill-config.md` defines `container.base_image_registry`, redirect the base image(s) to pull from that registry/namespace while keeping the SAME distribution and version (e.g. `eclipse-temurin:17-jdk` → `<registry>/eclipse-temurin:17-jdk`). If absent, leave the existing registry unchanged. **Verify the mirror is reachable before redirecting** — like the `./mvnw` wrapper fallback, this is verify-then-apply: if the configured registry does not resolve/pull (e.g. an internal mirror unreachable from the build host, `no such host`), do NOT rewrite the `FROM` — an unconditional redirect turns a compatibility migration into a hard build failure. Keep the original registry (same distro/version) and record the skipped redirect in `01-project-assessment.md`. **If the project ships no Dockerfile/container assets** (host-based or library project), `container.base_image_registry` / `container.runtime` have nothing to apply to — record "container config supplied but not applicable (no container assets)" in `01-project-assessment.md` rather than silently ignoring it. If Phase 3 later synthesizes an image purely for ARM64 validation, honor the configured registry there. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Single-stage (the whole image is the deployable artifact — it must be built for the target arch):
```dockerfile
# Omit --platform and let the build's --platform linux/arm64 drive it,
# or pin explicitly to the target. Do NOT use $BUILDPLATFORM here.
FROM <current-base-image>:<current-version>
```

Multi-stage — **Maven** (builder produces `target/*.jar`):
```dockerfile
# Builder: $BUILDPLATFORM = run the build natively on the builder's arch (faster; Java bytecode is arch-neutral)
FROM --platform=$BUILDPLATFORM <current-builder-image>:<current-version> AS builder
WORKDIR /app
COPY . .
RUN mvn clean package -DskipTests

# Runtime: $TARGETPLATFORM = the arch the image will actually run on (Graviton)
FROM --platform=$TARGETPLATFORM <current-runtime-image>:<current-version>
COPY --from=builder /app/target/*.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

Multi-stage — **Gradle** (differs from Maven: output is `build/libs/`, and a plain `application`-plugin jar has no `Main-Class` manifest, so `java -jar` on it fails with "no main manifest attribute"):
```dockerfile
FROM --platform=$BUILDPLATFORM <current-gradle-builder-image>:<current-version> AS builder
WORKDIR /app
COPY . .
# Use the Shadow/fat-jar task if the project has one (produces a runnable uber-jar):
RUN ./gradlew clean shadowJar -x test     # or: bootJar (Spring Boot) / build if a runnable jar is produced

FROM --platform=$TARGETPLATFORM <current-runtime-image>:<current-version>
COPY --from=builder /app/build/libs/*.jar app.jar   # Gradle output dir is build/libs, not target/
ENTRYPOINT ["java", "-jar", "app.jar"]
```
> If the project only produces a **plain** (non-fat) Gradle jar via the `application` plugin, `java -jar` won't work — either add the Shadow plugin, use Spring Boot's `bootJar`, or launch via `installDist`'s generated start script (`COPY --from=builder /app/build/install/<app> /app` then `ENTRYPOINT ["/app/bin/<app>"]`).

Key rules:
- **`$BUILDPLATFORM` is only valid on a *builder* stage.** Any stage that produces the shippable image — the single-stage `FROM`, or the multi-stage runtime `FROM` — must use `$TARGETPLATFORM` (or no `--platform`, letting the CLI `--platform linux/arm64` decide). Using `$BUILDPLATFORM` on a deployable image pins it to the *builder's* architecture, so an x86 CI builder would ship an x86 image even though `--platform linux/arm64` was requested — the opposite of the migration goal. If the original Dockerfile has no `--platform` annotations, the simplest correct change is to leave them off and drive arch via the build command.
- **Builder-stage tests run on `$BUILDPLATFORM`, not the target.** If you run the test suite inside the builder stage (`RUN mvn test` / `RUN ./gradlew test`) and build on an **x86** host/CI, those tests execute on x86 — an ARM64-only native failure would pass there, a **false PASS**. To validate on the target arch, either run tests in a stage pinned to `$TARGETPLATFORM`, or run them separately against a `linux/arm64` container (see phase3 §3.2). Building on an arm64 host masks this (builder = arm64), so don't rely on the builder stage alone for ARM64 test validation.

Host-based deployments skip Docker steps.

**Deployment manifests (only if the project already ships them):**

If the project contains Kubernetes/Helm manifests (or similar deployment descriptors), ensure they can schedule onto ARM64 nodes. Only touch node selection, image registry, and ingress vocabulary — do NOT restructure manifests or add resources the project does not already have. If no manifests are present, skip this step.

> **Skill config:** If `skill-config.md` defines `deploy.arch_selector` / `deploy.nodepool_label` / `deploy.registry` / `deploy.ingress_convention`, use those values for the node selector, nodepool label, image registry, and ingress convention respectively. If absent, use a generic `kubernetes.io/arch: arm64` node selector and leave the existing registry/ingress unchanged. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

## 2.5 Graviton-Specific JVM Recommendations

> **Output: `graviton-validation/05-jvm-configuration.md`**

Do NOT apply JVM flags automatically. Graviton runs well with default JVM settings. Document recommendations in the report for the team to evaluate during performance testing.

**JDK 21+:** Most Graviton optimizations are already enabled by default (AES-CTR intrinsics, improved tiered compilation). No flags to recommend unless performance testing shows a specific issue.

**JDK 11-17:** Document the following as recommendations to try if performance testing shows a regression:

| Flag | Workload type | Notes |
|------|---------------|-------|
| `-XX:+UnlockDiagnosticVMOptions -XX:+UseAESCTRIntrinsics` | Crypto-heavy (TLS termination, encryption) | Enabled by default in 21+ |
| `-XX:-TieredCompilation` | Long-running services (not latency-sensitive startup) | Trades startup time for steady-state throughput |
| `-XX:ReservedCodeCacheSize=64M` | Large apps with many classes | Only if code cache pressure observed |

The report should note the project's JDK version and which recommendations (if any) are relevant to its workload type.
