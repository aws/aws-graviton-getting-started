# Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues identified in Phase 1. Update ONLY what is required for ARM64 compatibility. Findings that need a user decision are listed with their options and a recommendation under User Decisions Pending (`03-dependency-compatibility-report.md`) and left unchanged until the user chooses. In an unattended run, where no one can answer (an automated transformation, or a brief that says not to ask), apply the option the decision's Recommendation names instead of waiting, list it under User Decisions Pending as applied, with how to reverse it, and continue; a `skill-config.md` value that rules the change out still wins, and an item no option fixes, or whose options all lie outside the skill (such as the OS or the base image), stays unchanged and listed.

## Contents

- 2.1 Native Library Resolution
- 2.2 Dependency Compatibility Updates
- 2.3 Architecture Detection Code Updates
- 2.4 Build Configuration Updates
- 2.5 Graviton-Specific JVM Recommendations

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

Update ONLY dependencies flagged as MUST UPGRADE (i.e. the resolved JAR was confirmed to lack the `linux/aarch64` binary; see the verification note in Phase 1.3). Do NOT upgrade compatible dependencies. Prefer the *lowest* version whose ARM64 binary works on the target, not the latest, to stay minimal: **confirm that candidate's JAR actually contains the aarch64 binary** (`scan_archive` from Phase 1.2.1 shows an `ARM aarch64` line) rather than trusting a remembered version number, and that the libraries the binary needs (`readelf -d` lists them) are in the target image (`netty-tcnative`'s `linux-aarch_64-fedora` builds need libraries the Amazon Linux 2023 images do not include (`libssl.so.1.1` up to at least 2.0.66, `libapr-1.so.0` in 2.0.84), while `netty-tcnative-boringssl-static` needs only glibc's libraries); the exact floor varies by library and some intermediate versions are unpublished.

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

After the updates, copy the dependencies again and re-run the Phase 1.2.1 scan; a MUST UPGRADE item still without an `ARM aarch64` build that suits the target comes back to this step, or goes under User Decisions Pending when no version has one.

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

> **Output: update `graviton-validation/04-code-scan-findings.md`** (Changes Applied)

**No Maven profile for ARM64.** A profile activated by `<os><arch>` matches the JVM that runs Maven, not the target, so an x86 build host never activates it for an arm64 image. Pass a setting the target needs explicitly (`-P<id>` or `-D<property>`); otherwise add none.

**Dockerfile updates (containerized deployments only):**

PRESERVE the current base image distribution and version. Do NOT change JDK distribution or version. One tag change is in scope: a tag or repository that names one architecture (`public.ecr.aws/lambda/java:21-x86_64`, `amd64/eclipse-temurin:21-jre`) becomes the same image's multi-architecture tag (`public.ecr.aws/lambda/java:21`, `eclipse-temurin:21-jre`); the distribution and version stay. An image with no arm64 build at its tag (Phase 1.4) moves to the lowest tag of the same image that lists `linux/arm64` (`mysql:5.7` lists only amd64, `mysql:8.0` lists arm64 too): a user decision, which an unattended run applies and records with how to reverse it. A library that starts such an image moves to its lowest version whose image has an arm64 build (MUST UPGRADE; Testcontainers for Java 1.15.2).

> **Skill config:** If `skill-config.md` defines `container.base_image_registry`, redirect the base image(s) to pull from that registry/namespace while keeping the SAME distribution and version (e.g. `eclipse-temurin:17-jdk` → `<registry>/eclipse-temurin:17-jdk`). If absent, leave the existing registry unchanged. **Verify the mirror is reachable before redirecting**: if the configured registry does not resolve or pull from the build host, do NOT rewrite the `FROM`; keep the original registry and record the skipped redirect in `01-project-assessment.md`. **If the project ships no Dockerfile/container assets**, record "container config supplied but not applicable (no container assets)" in `01-project-assessment.md`. An image Phase 3 builds for ARM64 validation uses the configured registry. See [skill-configuration.md](skill-configuration.md).

Single-stage (the whole image is the deployable artifact — it must be built for the target arch):
```dockerfile
# Omit --platform and let the build's --platform linux/arm64 drive it,
# or pin explicitly to the target. Do NOT use $BUILDPLATFORM here.
FROM <current-base-image>:<current-version>
```

A stage that runs GraalVM `native-image` builds an executable for the platform it runs on (`--target` defaults to the host's OS and architecture), so pin that stage to `$TARGETPLATFORM` and run it on an arm64 build host.

Multi-stage — **Maven** (builder produces `target/*.jar`):
```dockerfile
# Builder: $BUILDPLATFORM = run the build natively on the builder's arch (faster; a JAR's bytecode is arch-neutral)
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

**x86-only JVM options (§1.4):** remove each one where an ARM64 JVM reads it, or set it only on x86 (a start script can test `uname -m`). This is an ARM64-required change, not a tuning recommendation: a JVM that refuses the option does not start.

**Lambda functions (only if the project already ships the template):** set `Architectures: [arm64]` on each function in the SAM or CloudFormation template (`Architecture.ARM_64` in a CDK app, `architectures = ["arm64"]` in Terraform; a function that names none runs on x86_64). Do not add a template the project does not have, and do not change the runtime. The JAR the function deploys must pass §1.2 for Linux aarch64 like any other build. [Lambda instruction set architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html) documents the `arm64` value.

**Deployment manifests (only if the project already ships them):**

If the project contains Kubernetes/Helm manifests (or similar deployment descriptors), ensure they can schedule onto ARM64 nodes. Only touch node selection, image registry, and ingress vocabulary — do NOT restructure manifests or add resources the project does not already have. If no manifests are present, skip this step.

> **Skill config:** If `skill-config.md` defines `deploy.arch_selector` / `deploy.nodepool_label` / `deploy.registry` / `deploy.ingress_convention`, use those values for the node selector, nodepool label, image registry, and ingress convention respectively. If absent, use the generic `kubernetes.io/arch` label as the capacity rule below says, and leave the existing registry/ingress unchanged. See [skill-configuration.md](skill-configuration.md).

Change a node selector, a node affinity or the `cpuArchitecture` of an ECS task on EC2 capacity to arm64 only together with arm64 capacity in the files the project ships (a node group, NodePool, capacity provider or instance type): a pod whose selector no node matches stays `Pending`. Without that capacity, allow both architectures (a node affinity on `kubernetes.io/arch` with `operator: In` and the values `amd64` and `arm64`) and ship a multi-architecture image, so the workload keeps its x86 nodes until arm64 nodes exist. An instance type in those files gets the same series (`m`, `c`, `r`, ...) and size in the newest Graviton generation the region offers, with `g` for the processor letter (`m6i` and `m5a` become `m*g`) and its other letters kept (`m5d`, with instance store volumes, becomes `m*gd`); when no Graviton type keeps them, change nothing and list it. It goes under User Decisions Pending because sizing is the team's call (an unattended run applies it). With AWS credentials, list the candidates for `m5.xlarge`:

```bash
aws ec2 describe-instance-type-offerings --region us-west-2 --location-type region \
  --filters 'Name=instance-type,Values=m*g.xlarge' --query 'InstanceTypeOfferings[].InstanceType' --output text
```

**CI pipelines (only if the project already ships them):** apply the changes that only add or switch an architecture, and leave the rest of the pipeline as it is: add `linux/arm64` to the platforms an image build publishes (`docker buildx build --platform linux/amd64,linux/arm64`, or the `platforms` input of `docker/build-push-action`) with the two steps it needs on an x86 runner: QEMU (`docker/setup-qemu-action`; elsewhere `docker run --privileged --rm tonistiigi/binfmt --install all`; where no privileged container may run, use the arm64 job below), or an arm64 `RUN` step stops with `exec /bin/sh: exec format error`, and a builder for several platforms (`docker/setup-buildx-action`; elsewhere `docker buildx create --driver docker-container --use`), or an engine without the containerd image store, which Docker Engine 29.0 and later use by default only on a fresh installation, stops with `Multi-platform build is not supported for the docker driver`, or add an arm64 job beside the x86 one (a GitHub-hosted `ubuntu-24.04-arm` runner, a CodeBuild `ARM_CONTAINER` environment). Record each change in `04-code-scan-findings.md`. Anything else the pipeline needs (credentials, deployment steps, triggers, tool versions) is a recommendation in `00-summary.md`; with `ci.changes: recommend` in `skill-config.md`, the architecture changes are recommendations too.

## 2.5 Graviton-Specific JVM Recommendations

> **Output: `graviton-validation/05-jvm-configuration.md`**

Do NOT apply JVM flags automatically. Graviton runs well with default JVM settings. Document recommendations in the report for the team to evaluate during performance testing.

**JDK 21+:** No flags to recommend unless performance testing shows a specific issue. AES and AES-CTR intrinsics need no flag on JDK 11 and later: on Graviton2 to Graviton5, `-XX:+UnlockDiagnosticVMOptions -XX:+PrintFlagsFinal` showed `UseAESIntrinsics` and `UseAESCTRIntrinsics` true by default on Corretto 11, 17 and 21; check an older JDK build the same way.

**JDK 8:** has no AES-CTR option: `-XX:+UnlockDiagnosticVMOptions -XX:+UseAESCTRIntrinsics` stops it with `Unrecognized VM option 'UseAESCTRIntrinsics'`, and `UseAESIntrinsics` is on by default. Recommend a flag for JDK 8 only after `java <flag> -version` on the target JDK accepts it.

**JDK 11-17:** Document the following as recommendations to try if performance testing shows a regression:

| Flag | Workload type | Notes |
|------|---------------|-------|
| `-XX:-TieredCompilation` | Long-running services (not latency-sensitive startup) | Trades startup time for steady-state throughput |
| `-XX:ReservedCodeCacheSize=64M` | Large apps with many classes | Only if code cache pressure observed |

The report should note the project's JDK version and which recommendations (if any) are relevant to its workload type.
