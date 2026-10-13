# Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues identified in Phase 1. Update ONLY what is required for ARM64 compatibility. Findings that need a user decision are listed with their options and a recommendation under User Decisions Pending (`03-dependency-compatibility-report.md`) and left unchanged until the user chooses. In an unattended run, where no one can answer (an automated transformation, or a brief that says not to ask), apply the option the decision's Recommendation names instead of waiting, list it under User Decisions Pending as applied, with how to reverse it, and continue; a `skill-config.md` value that rules the change out still wins, and an item no option fixes stays unchanged and listed.

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

PRESERVE the current base image distribution and version. Do NOT change JDK distribution or version. One tag change is in scope: a tag or repository that names one architecture (`public.ecr.aws/lambda/java:21-x86_64`, `amd64/eclipse-temurin:21-jre`) becomes the same image's multi-architecture tag (`public.ecr.aws/lambda/java:21`, `eclipse-temurin:21-jre`); the distribution and version stay.

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

**x86-only JVM options (§1.4):** remove each one where an ARM64 JVM reads it, or set it only on x86 (a start script can test `uname -m`). This is an ARM64-required change, not a tuning recommendation: a JVM that refuses the option does not start. Executed: with `JAVA_TOOL_OPTIONS=-XX:UseAVX=2`, arm64 JDK 8, 11, 17 and 21 stopped with `Unrecognized VM option 'UseAVX=2'`; without it they started.

**Lambda functions (only if the project already ships the template):** set `Architectures: [arm64]` on each function in the SAM or CloudFormation template (`Architecture.ARM_64` in a CDK app, `architectures = ["arm64"]` in Terraform; a function that names none runs on x86_64). Do not add a template the project does not have, and do not change the runtime. The JAR the function deploys must pass §1.2 for Linux aarch64 like any other build. [Lambda instruction set architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html) documents the `arm64` value.

**Deployment manifests (only if the project already ships them):**

If the project contains Kubernetes/Helm manifests (or similar deployment descriptors), ensure they can schedule onto ARM64 nodes. Only touch node selection, image registry, and ingress vocabulary — do NOT restructure manifests or add resources the project does not already have. If no manifests are present, skip this step.

> **Skill config:** If `skill-config.md` defines `deploy.arch_selector` / `deploy.nodepool_label` / `deploy.registry` / `deploy.ingress_convention`, use those values for the node selector, nodepool label, image registry, and ingress convention respectively. If absent, use a generic `kubernetes.io/arch: arm64` node selector and leave the existing registry/ingress unchanged. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Change a node selector, a node affinity or the `cpuArchitecture` of an ECS task on EC2 capacity to arm64 only together with arm64 capacity in the files the project ships (a node group, NodePool, capacity provider or instance type): a pod whose selector no node matches stays `Pending`. Without that capacity, allow both architectures (a node affinity on `kubernetes.io/arch` with `operator: In` and the values `amd64` and `arm64`) and ship a multi-architecture image, so the workload keeps its x86 nodes until arm64 nodes exist. An instance type in those files gets the same family, suffix and size in the newest Graviton generation the region offers, recorded under User Decisions Pending because sizing is the team's call (an unattended run applies it). With AWS credentials, list the candidates for `m5.xlarge`:

```bash
aws ec2 describe-instance-type-offerings --region us-west-2 --location-type region \
  --filters 'Name=instance-type,Values=m*g.xlarge' --query 'InstanceTypeOfferings[].InstanceType' --output text
```

Executed in us-west-2, it listed `m6g.xlarge`, `m7g.xlarge`, `m8g.xlarge` and `m9g.xlarge`, so the default is `m9g.xlarge`.

**CI pipelines (only if the project already ships them):** apply the changes that only add or switch an architecture, and leave the rest of the pipeline as it is: add `linux/arm64` to the platforms an image build publishes (`docker buildx build --platform linux/amd64,linux/arm64`, or the `platforms` input of `docker/build-push-action`; Docker Engine 29.0 and later and Docker Desktop build multi-platform images by default, and older engines need the containerd image store or a `docker-container` builder, which `docker/setup-buildx-action` creates), or add an arm64 job beside the x86 one (a GitHub-hosted `ubuntu-24.04-arm` runner, a CodeBuild `ARM_CONTAINER` environment). Record each change in `04-code-scan-findings.md`. Anything else the pipeline needs (credentials, deployment steps, triggers, tool versions) is a recommendation in `00-summary.md`; with `ci.changes: recommend` in `skill-config.md`, the architecture changes are recommendations too.

## 2.5 Graviton-Specific JVM Recommendations

> **Output: `graviton-validation/05-jvm-configuration.md`**

Do NOT apply JVM flags automatically. Graviton runs well with default JVM settings. Document recommendations in the report for the team to evaluate during performance testing.

**JDK 21+:** No flags to recommend unless performance testing shows a specific issue. AES and AES-CTR intrinsics need no flag on JDK 11 and later: on Graviton2 to Graviton5, `-XX:+PrintFlagsFinal` showed `UseAESIntrinsics` and `UseAESCTRIntrinsics` true by default on Corretto 11, 17 and 21; check an older JDK build the same way.

**JDK 11-17:** Document the following as recommendations to try if performance testing shows a regression:

| Flag | Workload type | Notes |
|------|---------------|-------|
| `-XX:-TieredCompilation` | Long-running services (not latency-sensitive startup) | Trades startup time for steady-state throughput |
| `-XX:ReservedCodeCacheSize=64M` | Large apps with many classes | Only if code cache pressure observed |

The report should note the project's JDK version and which recommendations (if any) are relevant to its workload type.
