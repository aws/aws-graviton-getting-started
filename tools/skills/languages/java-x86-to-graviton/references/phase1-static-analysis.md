# Phase 1: Static Compatibility Analysis

Analyze the project without changing its source or build files. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below runs `mvn` or `./gradlew`, substitute `build.maven_invocation` / `build.gradle_invocation` from `skill-config.md` if defined (e.g. `./mvnw`). If it specifies a Maven wrapper (`./mvnw`) that is not present, fall back to bare `mvn`. See [skill-configuration.md](skill-configuration.md).

Phase 1 runs on any host, including x86. Besides the reports in `graviton-validation/`, it writes build output inside the project: §1.2.1 copies the resolved dependency JARs into `target/deps` (Maven) or into each project's `build/deps` (Gradle). In a multi-module Maven reactor, §1.1 and §1.2.1 need `mvn install -DskipTests` first, which builds every module and installs it into the local repository, `~/.m2/repository` by default ([lifecycle](https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html), [settings](https://maven.apache.org/settings.html)). Three kinds of step run code:
- the build tool, in §1.1, §1.2.1 and §1.3, with the project's build files and the plugins and repositories they name. Gradle evaluates the settings file and the build file of every project, which are code ([build lifecycle](https://docs.gradle.org/current/userguide/build_lifecycle.html)), and runs the init script that §1.2.1 writes; Maven loads the extensions that the project declares in `.mvn/extensions.xml` or in the POM ([extensions](https://maven.apache.org/guides/mini/guide-using-extensions.html)). `./gradlew` and `./mvnw` are scripts from the repository that download the Gradle or Maven version their wrapper properties name ([Gradle Wrapper](https://docs.gradle.org/current/userguide/gradle_wrapper.html), [Maven Wrapper](https://maven.apache.org/tools/wrapper/));
- the OS package lookups of §1.2.2, which run each target image's package tools (`apt-get`, `dnf`) in a container, natively on this host;
- on a host without Python 3.6 or later, the check program, in a `python:3-slim` container with no network.

The libc check of §1.1 copies files out of a container that it never starts; the files that §1.2.2 downloads are unpacked and read, never run; and the check program, `scripts/java_graviton_check.py`, only reads files. For a repository you do not trust, run Phase 1 in a disposable container or VM. No test or application of the project runs until Phase 3.

## Contents

- 1.1 Project Structure Analysis: Determine Deployment Type; Detect Multi-Module Structure; Determine Target OS and libc; Generate Dependency Tree; Categorize Components by Risk
- 1.2 Native Library Validation: 1.2.1 Statically Bundled .so Scanning; 1.2.2 Runtime-Extracted Native Library Detection; 1.2.3 Tiered Validation Policy
- 1.3 Dependency ARM64 Compatibility Analysis: Generate Filtered Tree; Classify Each Dependency; Document Findings; Build-Tool Artifacts with OS/Arch Classifiers
- 1.4 Architecture-Specific Code Detection
- 1.5 Java Version Compatibility Check

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`** and **`graviton-validation/raw/dependency-tree-full.txt`**

### Determine Deployment Type

```bash
# Deployment files (read every hit)
find . \( -name .git -o -name .venv -o -name node_modules -o -name cdk.out \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' \
  -o -name 'Containerfile*' -o -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' -o -name 'template.y*ml' -o -name 'serverless.yml' \
  -o -name 'cdk.json' -o -name '*.tf' -o -name '*.service' -o -name 'Procfile' \) -print | sort
# Dockerfiles under any name: by name, plus the files a build's -f or --file, Compose dockerfile: and
# docker/build-push-action file: name. A file is kept when it has a FROM line; a name that is no file
# here is printed: find that file by hand and add it to the list.
mkdir -p graviton-validation/raw
{ find . \( -name .git -o -name .venv -o -name target -o -name node_modules -o -name cdk.out \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' -o -name 'Containerfile*' \) -print
  grep -rnoE --exclude-dir=.git --exclude-dir=.venv --exclude-dir=target --exclude-dir=node_modules --include='*.sh' --include=Makefile --include='*.mk' --include='*.y*ml' --include='Jenkinsfile*' -- \
    "(build|bud)[[:space:]][^;|&#]*(-f[[:space:]]+|--file[[:space:]=]+)[\"']?[^[:space:];|&\"')]+|(dockerfile|file):[[:space:]]*[\"']?[^[:space:]#\"']+" . |
    while IFS= read -r hit; do
      src=${hit%%:*}; ref=$(printf '%s\n' "${hit#*:*:}" | sed -E "s/^.*(-f[[:space:]]+|--file[[:space:]=]+|file:[[:space:]]*)[\"']?//")
      if [ -f "$ref" ]; then printf './%s\n' "${ref#./}"
      elif [ -f "${src%/*}/$ref" ]; then printf '%s/%s\n' "${src%/*}" "${ref#./}"
      else printf 'not found: %s names %s\n' "$src" "$ref" >&2; fi
    done
} | while IFS= read -r f; do grep -qiE '^[[:space:]]*FROM[[:space:]]' "$f" && printf '%s\n' "$f"; done |
  sort -u > graviton-validation/raw/dockerfiles.txt
cat graviton-validation/raw/dockerfiles.txt
```

- Dockerfile or container config present, under any name (`Dockerfile*`, `*.Dockerfile`, `Containerfile`; `docker build -f` and Compose `dockerfile:` accept any name; the block lists them all in `raw/dockerfiles.txt`): **Containerized**
- systemd/init scripts or direct JAR/WAR: **Host-based**
- A CDK app (`cdk.json`) or Terraform files define the infrastructure, and its architecture settings, in code (§1.4)
- A SAM, CloudFormation, CDK or Terraform function with a `java` runtime: **Lambda**. The architecture is a function setting (§1.4)
- Some applications support more than one

### Detect Multi-Module Structure

- Maven: parent POM with `<modules>` section
- Gradle: `settings.gradle` / `settings.gradle.kts` with `include` directives
- If multi-module: enumerate all submodules, analyze each independently
- Native libraries may reside in child modules; do NOT limit to root build file

### Determine Target OS and libc

Native files depend on the OS the workload runs on as well as the CPU: glibc or musl, the glibc version, libstdc++, and the kernel's page size. Read them for each target into `01-project-assessment.md` (Target OS and libc). For an image (the last `FROM` of each file in `raw/dockerfiles.txt`, or a Lambda container image), copy its loaders and libraries into a folder with this block, which never starts the container. The check reads the C library from that folder, and passes a file only when the image has every library it needs from glibc, libstdc++ and libgcc_s and those define every version it needs, as the image's loader does (Amazon Linux 2023 reports glibc 2.34, yet its `libc.so.6` defines `GLIBC_2.35` and its `libm.so.6` does not).

> **Skill config:** `target.hosts` and `target.images` in `skill-config.md` add targets to the ones the repository names; a host's `page=` and `kernel=` count only when they were not measured there. The C library and its versions still come from each target's files.

```bash
IMG=public.ecr.aws/lambda/java:21   # the image the application runs on
GV_CLI=${CONTAINER_CMD:-docker}   # the CLI that Phase 3's detection found, else Docker
GV_CPL=(-L); case "$GV_CLI $("$GV_CLI" --version 2> /dev/null)" in *podman*) GV_CPL=();; esac   # docker, Finch and nerdctl copy a symbolic link's target with -L; podman cp has no -L and refuses it, also behind a docker command
GV_TAG=$(printf '%s' "$IMG" | tr -c 'A-Za-z0-9._-' '_')   # names this target's output files (raw/...-$GV_TAG.txt)
GV_IMG_ID=$("$GV_CLI" image inspect --format '{{.Id}}' "$IMG" 2> /dev/null)   # the image the tag names now: create --platform moves a local tag to the arm64 image
GV_IMGS=$("$GV_CLI" images -a -q --no-trunc 2> /dev/null) && GV_IMGS="listed: $GV_IMGS"; case $("$GV_CLI" --version 2> /dev/null) in "Docker version"*|"podman version"*) ;; *) GV_IMGS=;; esac   # the images here before the pull: the cleanup removes only one the pull added, and nothing if this listing fails or the CLI is neither docker nor podman (others may list image IDs in another form)
command -v timeout > /dev/null 2>&1 || timeout() { while [ $# -gt 1 ]; do case $1 in -k|-s|--kill-after|--signal) shift 2;; -*) shift;; *) break;; esac; done; shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit, dropping the options and the duration
GV_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/graviton-target-root.XXXXXX") || GV_ROOT=   # a new, empty folder, or nothing: the copies below never run without it
[ -n "$GV_ROOT" ] || echo "ERROR: mktemp -d made no folder under ${TMPDIR:-/tmp}; set TMPDIR to a writable folder and rerun"
# The image's loaders and libraries, from a container that is created and never started (no emulation, and no
# shell needed in the image); timeout 300 bounds the image pull that create does
if [ -n "$GV_ROOT" ] && cid=$(timeout 300 "$GV_CLI" create --platform linux/arm64 "$IMG" none); then
  for f in /etc/os-release /usr/lib/os-release /lib/apk/db/installed; do
    mkdir -p "$GV_ROOT${f%/*}" && "$GV_CLI" cp "${GV_CPL[@]}" "$cid:$f" "$GV_ROOT$f" 2> /dev/null
  done
  for dir in /lib /lib64 /usr/lib /usr/lib64 /lib/aarch64-linux-gnu /usr/lib/aarch64-linux-gnu; do
    mkdir -p "$GV_ROOT$dir"
    for lib in ld-musl-aarch64.so.1 ld-linux-aarch64.so.1 libc.so.6 libm.so.6 libpthread.so.0 libdl.so.2 librt.so.1 \
        libresolv.so.2 libutil.so.1 libanl.so.1 libmvec.so.1 libnsl.so.1 libstdc++.so.6 libgcc_s.so.1; do
      "$GV_CLI" cp "${GV_CPL[@]}" "$cid:$dir/$lib" "$GV_ROOT$dir/$lib" 2> /dev/null
    done
  done
  for l in $(find "$GV_ROOT" -type l 2> /dev/null); do   # a copy without -L (podman) is the link itself: copy its target
    t=$(readlink "$l"); case $t in /*) ;; *) t=$(dirname "${l#"$GV_ROOT"}")/$t;; esac
    hops=0; while [ "$hops" -lt 40 ] && case $t in */../*) true;; *) false;; esac; do t=$(printf '%s' "$t" | sed -E 's#/[^/]+/\.\./#/#; s#^/\.\./#/#'); hops=$((hops + 1)); done   # /etc/../usr/lib/os-release; a leading /../ is /
    rm -f "$l"; "$GV_CLI" cp "$cid:$t" "$l" 2> /dev/null
  done
  { timeout 300 "$GV_CLI" export "$cid" 2> /dev/null || : > "$GV_ROOT/gv-export-failed"; } | tar -tf - 2> /dev/null | awk -F/ '$NF ~ /\.so(\.[0-9]+)*$/ {print $NF}' | sort -u > "$GV_ROOT/gv-image-libs.txt"   # every shared library's name in the image, read without starting it
  [ ! -e "$GV_ROOT/gv-export-failed" ] || rm -f "$GV_ROOT/gv-image-libs.txt" "$GV_ROOT/gv-export-failed"   # no list from an export that failed or was cut off: the check then says so
  "$GV_CLI" rm "$cid" > /dev/null
  n=$("$GV_CLI" image inspect --format '{{.Id}}' "$IMG" 2> /dev/null); [ -z "$GV_IMG_ID" ] || [ "$n" = "$GV_IMG_ID" ] || "$GV_CLI" tag "$GV_IMG_ID" "$IMG"   # a moved tag goes back to the image it named
  case $GV_IMGS in "") ;; *"${n#sha256:}"*) [ -n "$GV_IMG_ID" ] || [ -z "$n" ] || echo "NOTE: $IMG now names the arm64 image that was already here, so the tag stays (removing it could remove that image)";; *) "$GV_CLI" rmi "$n" > /dev/null 2>&1;; esac   # an image the pull added goes; one that was here, by tag or by digest, stays
  os=$(sed -n 's/^PRETTY_NAME=//p' "$GV_ROOT/etc/os-release" "$GV_ROOT/usr/lib/os-release" 2> /dev/null | head -n 1 | tr -d '"')
  c=$(find "$GV_ROOT" -name libc.so.6 -type f | head -n 1); x=$(find "$GV_ROOT" -name 'libstdc++.so.6' -type f | head -n 1)
  if [ -e "$GV_ROOT/lib/ld-musl-aarch64.so.1" ]; then
    m=$(awk '/^P:musl$/{f=1; next} f && /^V:/{print substr($0, 3); exit}' "$GV_ROOT/lib/apk/db/installed" 2> /dev/null)
    libc="musl${m:+ $m}"; [ -e "$GV_ROOT/lib/ld-linux-aarch64.so.1" ] && libc="$libc, with a glibc loader"
  else
    v=$(grep -ao 'release version 2\.[0-9]*' "$c" 2> /dev/null | head -n 1 | cut -d' ' -f3); libc="glibc ${v:-(no libc.so.6 found)}"
  fi
  if [ -n "$x" ]; then
    cxx=$(grep -ao 'GLIBCXX_3\.4\.[0-9][0-9]*' "$x" | sort -u -t. -k3,3n | tail -n 1); cxx=${cxx:-"libstdc++ with no GLIBCXX_ versions"}
  else cxx="no libstdc++.so.6"; fi
  echo "$IMG: ${os:-no os-release}; $libc; $cxx; files in $GV_ROOT"
  mkdir -p graviton-validation/raw && printf '%s\t%s\n' "$GV_TAG" "$GV_ROOT" >> graviton-validation/raw/target-roots.txt   # Phase 3 reads the folder here when this shell is gone
  # The later checks run once for each target that raw/target-roots.txt records, in this shell or a new one. Remove the
  # folder by that exact path (rm -rf "$GV_ROOT"), never by a wildcard, once the report is written.
else [ -z "$GV_ROOT" ] || rmdir "$GV_ROOT"; echo "$IMG: no arm64 container was created (no arm64 variant of the image, or the pull failed: see the error above)"; fi   # nothing is recorded for it, so no check runs for this image
```

- **Images:** a tag can move to a newer OS release, so read the image the project deploys (`public.ecr.aws/lambda/java:17` is Amazon Linux 2 with glibc 2.26, `:21` Amazon Linux 2023 with glibc 2.34).
- **Lambda managed runtimes:** the runtime identifier sets the OS, as the runtimes table shows ([Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)): Amazon Linux 2023 has glibc 2.34, Amazon Linux 2 glibc 2.26. The same Java version can have an identifier on each, for example `java17` on Amazon Linux 2 and `java17.al2023` on Amazon Linux 2023. AWS publishes a base image for each runtime, listed with its OS ([AWS base images for Java](https://docs.aws.amazon.com/lambda/latest/dg/java-image.html)): read the one for the function's runtime as for a container image; if it cannot be read, pass `--glibc` with that OS's version and leave `--glibcxx` out. arm64 functions on both reported a page size of 4096.
- **EC2 hosts:** the AMI's distribution; on the instance, `ldd --version | head -n 1` prints the glibc version.
- **Page size:** a container uses its host's kernel, so it comes from the EC2 hosts or Kubernetes nodes: run `getconf PAGESIZE` there (AlmaLinux 8 reported 65536; AlmaLinux 9 and Amazon Linux 2023, 4096). If no host can be reached, leave it out; the check then lists the files a kernel with 64 KB pages refuses.

§1.2.1 runs the check once for each target that `raw/target-roots.txt` records, and writes `raw/native-check-<target>.txt` for each. For a target with no image, record a name of its own (letters, digits, `.`, `_` and `-`: the name becomes part of the output file names) and its lowest glibc version, such as `printf '%s\tglibc=%s\n' al2023-host 2.34 >> graviton-validation/raw/target-roots.txt` for an Amazon Linux 2023 host. Set `GV_PAGE=65536` to add a measured page size.

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

Native libraries live inside the **resolved dependency JARs** (in the local repository cache, `~/.m2/repository` or `~/.gradle/caches`) and the built fat JARs, WARs and EARs under `target/` and `build/`, not in the project source tree: never exclude `target/` or `build/` from the check.

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

Then judge every native file by its content with the check program, `scripts/java_graviton_check.py`, which the block runs from the skill folder on its first line (the folder that Documentation Setup in SKILL.md printed). It reads JARs, WARs and EARs in memory, with the archives nested in them (Spring Boot `BOOT-INF/lib`, WAR `WEB-INF/lib`, EARs of WARs, shaded JARs), and native files on disk, whatever their names, and judges each for the target of §1.1. Without Python 3.6 or later (`maven:3-eclipse-temurin-21` and `eclipse-temurin:21` ship no `python3`) the block runs it in a Python image, with the project and the target folder mounted read-only:

```bash
GV_JAVA_SKILL_DIR=   # the skill folder that the Documentation Setup block in SKILL.md printed
GV_CHECK=$GV_JAVA_SKILL_DIR/scripts/java_graviton_check.py
if case $GV_JAVA_SKILL_DIR in /?*) [ -f "$GV_CHECK" ];; *) false;; esac; then   # only the skill's own program: never a path read from the project
# Without python3 3.6 or later, run the program in a Python image, with the project, the program, the targets' folders
# and the local Maven and Gradle repositories mounted read-only (braces: zsh reads "$GV_CHECK:r" as a modifier)
GV_MNT=(-v "${PWD}:${PWD}:ro" -v "${GV_CHECK}:${GV_CHECK}:ro")
while IFS= read -r t; do case $t in glibc=*|"") continue;; esac   # only the folders the §1.1 block made: the list is a file in the project
  case ${t#"${TMPDIR:-/tmp}/graviton-target-root."} in "$t"|""|*/*) echo "CHECK: $t not mounted: not a folder that the §1.1 block made";;
    *) [ -d "$t" ] && [ -O "$t" ] && GV_MNT+=(-v "${t}:${t}:ro");; esac
done < <(cut -f2 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u)
for d in "$HOME/.m2" "$HOME/.gradle"; do [ -d "$d" ] && GV_MNT+=(-v "${d}:${d}:ro"); done   # §1.3 checks JARs in the local repositories too
if python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 6))' 2> /dev/null; then GV_PY=(python3)
else GV_PY=("${CONTAINER_CMD:-docker}" run --rm --network none "${GV_MNT[@]}" -w "$PWD" public.ecr.aws/docker/library/python:3-slim python3); fi
mkdir -p graviton-validation/raw
for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one run per target that §1.1 recorded; with none, one run named target
case $GV_TAG in *[!A-Za-z0-9._-]*) echo "CHECK: target $GV_TAG skipped: a name in raw/target-roots.txt names output files, so it holds only letters, digits, '.', '_' and '-'"; continue;; esac
GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
case $GV_TDIR in ""|glibc=*) ;; *) case ${GV_TDIR#"${TMPDIR:-/tmp}/graviton-target-root."} in "$GV_TDIR"|""|*/*) false;; *) [ -d "$GV_TDIR" ] && [ -O "$GV_TDIR" ];; esac || { echo "CHECK: target $GV_TAG skipped: $GV_TDIR is not a folder that the skill made for a target image"; continue; };; esac   # only a folder from the image-copy block (mktemp in ${TMPDIR:-/tmp}, yours): the list is a file in the project
GV_T=(); case $GV_TDIR in "") ;; glibc=*) GV_T=(--libc glibc --glibc "${GV_TDIR#glibc=}");; *) GV_T=(--target-root "$GV_TDIR");; esac; GV_T+=(${GV_PAGE:+--page-size} ${GV_PAGE:+"$GV_PAGE"})
# The check judges the files of one run as one classpath, so it runs once for each module's build output (target/ or
# build/: its resolved dependencies and its JAR, WAR or EAR), then once for the repository's own files
{ find . \( -name .git -o -name node_modules \) -prune -o -type d \( -name target -o -name build \) -prune -print | sort |
    while IFS= read -r out; do echo "== $out"; "${GV_PY[@]}" "$GV_CHECK" "${GV_T[@]}" "$out"; done
  echo "== repository files"; "${GV_PY[@]}" "$GV_CHECK" "${GV_T[@]}" --source-tree .
} | tee "graviton-validation/raw/native-check-$GV_TAG.txt"   # one file per target, named for it
done
else echo "ERROR: set GV_JAVA_SKILL_DIR on the first line to the skill folder that the Documentation Setup block in SKILL.md printed"; fi
```

If a dependency could not be materialized (offline or blocked `copy-dependencies`), run the check on its JARs in `~/.m2/repository` or `~/.gradle/caches`, for the coordinates in the dependency tree only.

Each run prints the target, one line per native file (worst first) and `findings: N, checks: M`; it exits 1 when it prints a `FINDING`. Read the runs of the deployed modules, and decide from these lines, never from a path:
- `FINDING`: the target's loader refuses the file by its own rule: not aarch64 (`is x86-64`), an Android build, a build for the other C library, a `GLIBC_` or `GLIBCXX_` version the target does not define, or a LOAD alignment below the target's page size. With the image's files, a glibc, libstdc++ or libgcc_s library the file needs that the image does not have is also a `FINDING`, and so is a glibc symbol it imports that nothing in a musl image provides. When the x86-64 build needs the same version or library, the line says so: x86-64 hosts with this OS fail as well.
- `CHECK`: the files cannot decide, and the line says what settles it: a glibc build for a musl target that needs no glibc library musl's loader lacks, judged without the image's files (with the image's files, the check resolves the file's glibc imports against the image's libraries, and a symbol the image does not define is a `FINDING`: the load passes, and a call that reaches that symbol stops the process), an object file or static library with no aarch64 code, or an archive the check could not read. A file that needs another library the image does not have, one the scanned files do not ship, is also a `CHECK`: the image the project deploys may install it.
- `OK`: a Linux aarch64 build that suits the target. `OTHER`: a file the target does not load, such as a build for macOS, Windows or FreeBSD, or another build of a library whose build for this target is there.
- Builds of one library are judged together: files in one folder, or in folders named for each platform (`linux-aarch64` and `linux-x86-64`), whose names match once the architecture and C library parts are removed, such as netty's `libnetty_transport_native_epoll_x86_64.so` and `libnetty_transport_native_epoll_aarch_64.so` in two classifier JARs. A `NOTE` names the build for this target, and the Phase 3.3 loaded check confirms the JVM loads it. A `FINDING` means no build suits (§1.2.2).
- A fat or shaded JAR carries the native builds of the JARs it bundles, whichever host builds it (except files a classifier or profile picks for the build host's OS or architecture, §1.3 and Phase 2.4): do not call it architecture-neutral while its run has a `FINDING`.
- Without `--page-size`, one `NOTE` lists the aarch64 files linked for 4 KB pages only.
- With `--target-root`, the target line ends with `read from <folder> (<os-release name>)`, and a version finding names the library: `needs GLIBC_2.35 from libm.so.6; the target's libm.so.6 defines up to GLIBC_2.32`. On a musl image with gcompat, a symbol that only gcompat's library defines is a `CHECK`: musl's loader gives it to the file only when that library is preloaded (`LD_PRELOAD`).

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
# check is authoritative. Note artifactIds vary: net.jpountz.lz4 uses artifactId "lz4",
# not "lz4-java", so match both.) Recurse so child-module build files are included.
grep -rnE "netty-transport-native|netty-tcnative|io\.grpc.*netty|conscrypt|jnr-ffi|jnr-posix|leveldbjni|rocksdbjni|sqlite-jdbc|lz4|zstd-jni|snappy-java|jansi|hawtjni|commons-crypto" \
  --include="pom.xml" --include="build.gradle" --include="build.gradle.kts" . 2>/dev/null || true
```

Downloads in scripts, Dockerfiles and CI bring native code in outside the build. List every one, then fetch each into a scratch folder and run the §1.2.1 check on what it holds, whatever its URL says (resolve the script's variables in the URL first):

```bash
GV_JAVA_SKILL_DIR=   # the skill folder that the Documentation Setup block in SKILL.md printed
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --exclude-dir=node_modules --include='*.sh' --include='Dockerfile*' --include='*.[Dd]ockerfile' \
  --include='Containerfile*' --include='Makefile' --include='*.y*ml' --include='Jenkinsfile*' '(curl|wget|Invoke-WebRequest|iwr|Start-BitsTransfer)[[:space:]]|^[[:space:]]*ADD([[:space:]]+--[^[:space:]]+)*[[:space:]]+https?:|releases/(latest/)?download/' . 2>/dev/null || true
URL='https://github.com/jqlang/jq/releases/download/jq-1.6/jq-linux64'   # one download from the list
GV_CHECK=$GV_JAVA_SKILL_DIR/scripts/java_graviton_check.py; d=
if case $GV_JAVA_SKILL_DIR in /?*) [ -f "$GV_CHECK" ];; *) false;; esac; then   # only the skill's own program: never a path read from the project
  d=$(mktemp -d "${TMPDIR:-/tmp}/graviton-download.XXXXXX") && mkdir "$d/x" || { d=; echo "ERROR: mktemp -d made no folder under ${TMPDIR:-/tmp}; set TMPDIR to a writable folder and rerun"; }
else echo "ERROR: set GV_JAVA_SKILL_DIR on the first line to the skill folder that the Documentation Setup block in SKILL.md printed"; fi
# Without python3 3.6 or later, the program runs in a Python image with the download, the program and the targets'
# folders mounted read-only (braces: zsh reads "$d:r" as a modifier)
if python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 6))' 2> /dev/null; then GV_PY=(python3)
else GV_PY=("${CONTAINER_CMD:-docker}" run --rm --network none -v "${d}:${d}:ro" -v "${GV_CHECK}:${GV_CHECK}:ro")
  while IFS= read -r t; do case $t in glibc=*|"") continue;; esac   # only the folders the §1.1 block made: the list is a file in the project
    case ${t#"${TMPDIR:-/tmp}/graviton-target-root."} in "$t"|""|*/*) echo "CHECK: $t not mounted: not a folder that the §1.1 block made";;
      *) [ -d "$t" ] && [ -O "$t" ] && GV_PY+=(-v "${t}:${t}:ro");; esac
  done < <(cut -f2 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u)
  GV_PY+=(public.ecr.aws/docker/library/python:3-slim python3); fi
if [ -n "$d" ] && curl -fsSL --max-time 300 -o "$d/download" "$URL"; then
  # Unpack by the first bytes, not the name: a .deb (an ar archive), an .rpm, a zip or a tar archive
  case "$(od -An -tx1 -N4 "$d/download" | tr -d ' \t\n')" in
    213c6172) if head -c 64 "$d/download" | grep -q debian-binary; then   # another ar archive is a static library, which the scan reads
                (cd "$d/x" && ar x ../download && for t in data.tar.*; do tar -xf "$t"; done) && rm "$d/download" \
                  || echo "CHECK: $URL is a .deb this host cannot unpack (needs ar, and tar with xz or zstd)"
              fi ;;
    edabeedb) { if command -v bsdtar > /dev/null 2>&1; then bsdtar -xf "$d/download" -C "$d/x"   # bsdtar keeps every path inside the folder
                else (cd "$d/x" && rpm2cpio ../download | cpio -idm --quiet --no-absolute-filenames); fi; } && rm "$d/download" \
                || echo "CHECK: $URL is an .rpm this host cannot unpack (needs bsdtar, or rpm2cpio and GNU cpio)" ;;
    *) tar -xf "$d/download" -C "$d/x" 2> /dev/null ;;   # a zip, such as a JAR, the check reads as it is
  esac
  for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one scan per target that §1.1 recorded; with none, one scan named target
  case $GV_TAG in *[!A-Za-z0-9._-]*) echo "CHECK: target $GV_TAG skipped: a name in raw/target-roots.txt names output files, so it holds only letters, digits, '.', '_' and '-'"; continue;; esac
  GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
  case $GV_TDIR in ""|glibc=*) ;; *) case ${GV_TDIR#"${TMPDIR:-/tmp}/graviton-target-root."} in "$GV_TDIR"|""|*/*) false;; *) [ -d "$GV_TDIR" ] && [ -O "$GV_TDIR" ];; esac || { echo "CHECK: target $GV_TAG skipped: $GV_TDIR is not a folder that the skill made for a target image"; continue; };; esac   # only a folder from the image-copy block (mktemp in ${TMPDIR:-/tmp}, yours): the list is a file in the project
  GV_T=(); case $GV_TDIR in "") ;; glibc=*) GV_T=(--libc glibc --glibc "${GV_TDIR#glibc=}");; *) GV_T=(--target-root "$GV_TDIR");; esac; GV_T+=(${GV_PAGE:+--page-size} ${GV_PAGE:+"$GV_PAGE"})
  echo "== $GV_TAG"; "${GV_PY[@]}" "$GV_CHECK" "${GV_T[@]}" "$d" | sed "s#$d/##g"
  done
else [ -z "$d" ] || echo "CHECK: $URL did not download"; fi
[ -z "$d" ] || rm -rf "$d"
```

A download that cannot be fetched from here (credentials, a private network) stays CHECK until it is scanned where it can be.

Check that every OS package the images and scripts install exists for arm64 on the target OS, from a container that runs natively on this host. On an x86 host, asking the arm64 image itself runs under emulation:

```bash
# OS packages that images and scripts install (each must exist for arm64 on the target OS)
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --exclude-dir=node_modules --include='Dockerfile*' --include='*.[Dd]ockerfile' \
  --include='Containerfile*' --include='*.sh' '(apt-get|apt|dnf|yum|microdnf|apk|zypper)[[:space:]].*(install|add)[[:space:]]' . 2>/dev/null || true
```

```bash
# Debian or Ubuntu target: ask its package index for the arm64 builds, from a container that runs natively on this host
IMG=public.ecr.aws/docker/library/eclipse-temurin:21   # the runtime image (Determine Target OS and libc)
PKGS="fontconfig"                                      # the packages its Dockerfile installs
command -v timeout > /dev/null 2>&1 || timeout() { while [ $# -gt 1 ]; do case $1 in -k|-s|--kill-after|--signal) shift 2;; -*) shift;; *) break;; esac; done; shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit, dropping the options and the duration
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
ARM_PKGS=$(echo "$PKGS" | sed -E 's/([^ =]+)(=[^ ]*)?/\1:arm64\2/g')   # pkg:arm64, and pkg:arm64=VERSION for a pinned version
# On an amd64 Ubuntu image the x86 mirrors carry no arm64 files (apt-get update: "binary-arm64/Packages 404 Not
# Found"): keep the image's sources for amd64 and read arm64 from ports.ubuntu.com
PORTS='. /etc/os-release
if [ "$ID" = ubuntu ] && [ "$(dpkg --print-architecture)" = amd64 ]; then
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do [ -f "$f" ] && sed -i -E "s/^deb (https?:)/deb [arch=amd64] \1/" "$f"; done
  for f in /etc/apt/sources.list.d/*.sources; do [ -f "$f" ] && sed -i "/^Types:/a Architectures: amd64" "$f"; done
  for s in "" -updates -security; do
    echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports $VERSION_CODENAME$s main restricted universe multiverse"
  done > /etc/apt/sources.list.d/arm64-ports.list
fi
'
# 480 seconds inside the container stops apt-get; 600 outside stops the container if it does not exit
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "$PORTS dpkg --add-architecture arm64 && apt-get update -qq && apt-get install -s --no-install-recommends $ARM_PKGS 2>&1 | grep -E '^(Inst|E:)'"
```

```bash
# Amazon Linux 2023 (dnf) target: ask the aarch64 repositories, from a container that runs natively on this host
IMG=public.ecr.aws/amazoncorretto/amazoncorretto:21
PKGS="fontconfig"
command -v timeout > /dev/null 2>&1 || timeout() { while [ $# -gt 1 ]; do case $1 in -k|-s|--kill-after|--signal) shift 2;; -*) shift;; *) break;; esac; done; shift; "$@"; }   # no GNU timeout (macOS without coreutils): run without the host-side limit, dropping the options and the duration
NATIVE="linux/$(docker version -f '{{.Server.Arch}}')"
# 480 seconds inside the container stops dnf; 600 outside stops the container if it does not exit
timeout 600 docker run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 480 \
  sh -c "dnf -q --forcearch aarch64 repoquery --arch aarch64,noarch --latest-limit 1 $PKGS"; echo "repoquery exit status $? (0: a package with no line has no aarch64 build; another status: the query failed, which is no answer)"
```

- **Debian or Ubuntu** (observed on Ubuntu 26.04): judge only the requested `:arm64` packages, because some dependencies resolve to the host's architecture in this simulation. A package with no arm64 build stops it: `E: Unable to locate package <name>:arm64`.
- **Amazon Linux 2023:** a package with no aarch64 build prints no line.

**Common runtime-extracting libraries** (this list is a *prompt*, not an allowlist — any JAR containing a native lib qualifies, including ones not named here such as `jansi`/`hawtjni`, `commons-crypto`, `jansi-native`):
- **Netty** (`netty-transport-native-epoll`, `netty-tcnative`): Extracts .so based on `os.arch`
- **Conscrypt**: Native crypto libraries at runtime
- **RocksDB** (`rocksdbjni`): Platform-specific .so at first use
- **SQLite JDBC** (`sqlite-jdbc`): Bundles and extracts native SQLite
- **LZ4/Zstd/Snappy** (`lz4-java`, `zstd-jni`, `snappy-java`): Native compression accelerators
- **LevelDB** (`leveldbjni`): Native key-value store bindings
- **JNA-based bindings** (`Native.load`, for example `lazysodium-java`): JNA's own `libjnidispatch.so` is not enough; the library the binding bundles needs an aarch64 Linux build too. lazysodium-java 5.1.1 bundles no aarch64 libsodium, and on an arm64 JVM it loads its 32-bit Arm build and fails with `wrong ELF class: ELFCLASS32`; 5.1.4 adds `arm64/libsodium.so` and loads
- **Executables in JARs** (no `.so` name): `org.seleniumhq.selenium:selenium-manager` 4.6.0 to 4.48.0, a dependency of `selenium-remote-driver`, carries one Linux build, `org/openqa/selenium/manager/linux/selenium-manager`, an x86-64 executable (4.49.0 adds `linux-arm64/`); `com.github.os72:protoc-jar` 3.11.4, its latest release, carries no aarch64 build, and its Linux protoc executables are x86-64 files named `*.exe`; on aarch64 it downloads `protoc-3.11.4-linux-aarch_64.exe` from Maven Central when it runs, and without that access fails with `Unsupported platform: protoc-3.11.4-linux-aarch_64.exe`

**Do not rely on the named list alone.** The §1.2.1 check decides: it finds the native code in every resolved JAR by content, whether or not its name appears above; the grep is only a hint.

Flag each JAR with a §1.2.1 `FINDING` as MUST UPGRADE (never infer it from the version number), unless the library falls back to pure Java without its native code: the application then runs on ARM64, but without the native code it runs on x86, so mark it CHECK and settle it with the loaded check in Phase 3.3. For Netty epoll, `Epoll.unavailabilityCause()` is then `java.io.FileNotFoundException: META-INF/native/libnetty_transport_native_epoll_aarch_64.so`.

### 1.2.3 Tiered Validation Policy

**FAIL immediately if:**
- The §1.2.1 check prints a `FINDING` for the file (so no build of its library suits the target) AND no source code is available AND the user cannot provide an ARM64 build

**WARN but proceed if:**
- Source is available for recompilation (Phase 2.1)

**CHECK if:**
- The check prints a `CHECK` line for the file, OR the library falls back to pure Java without its native code (Netty's epoll transport falls back to NIO): the application runs, but not the code it runs on x86 (the Phase 3.3 loaded check)

**PASS if:**
- The check prints no `FINDING` or `CHECK` for the file, and when a `NOTE` names another build of its library for this target, the Phase 3.3 loaded check shows that the JVM loads that build. A `CHECK` is not a PASS: an assessment reports it as `CHECK` with the step that settles it

For x86-only native files: check for source in the repository, document recompilation needs, or prompt the user. Validate a file with:
```bash
GV_JAVA_SKILL_DIR=   # the skill folder that the Documentation Setup block in SKILL.md printed
GV_CHECK=$GV_JAVA_SKILL_DIR/scripts/java_graviton_check.py
if case $GV_JAVA_SKILL_DIR in /?*) [ -f "$GV_CHECK" ];; *) false;; esac; then   # only the skill's own program: never a path read from the project
for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one check per target that §1.1 recorded; with none, one check named target
case $GV_TAG in *[!A-Za-z0-9._-]*) echo "CHECK: target $GV_TAG skipped: a name in raw/target-roots.txt names output files, so it holds only letters, digits, '.', '_' and '-'"; continue;; esac
GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
case $GV_TDIR in ""|glibc=*) ;; *) case ${GV_TDIR#"${TMPDIR:-/tmp}/graviton-target-root."} in "$GV_TDIR"|""|*/*) false;; *) [ -d "$GV_TDIR" ] && [ -O "$GV_TDIR" ];; esac || { echo "CHECK: target $GV_TAG skipped: $GV_TDIR is not a folder that the skill made for a target image"; continue; };; esac   # only a folder from the image-copy block (mktemp in ${TMPDIR:-/tmp}, yours): the list is a file in the project
GV_T=(); case $GV_TDIR in "") ;; glibc=*) GV_T=(--libc glibc --glibc "${GV_TDIR#glibc=}");; *) GV_T=(--target-root "$GV_TDIR");; esac; GV_T+=(${GV_PAGE:+--page-size} ${GV_PAGE:+"$GV_PAGE"})
python3 "$GV_CHECK" "${GV_T[@]}" libname.so   # no FINDING line (without python3: "${GV_PY[@]}" of §1.2.1)
done
else echo "ERROR: set GV_JAVA_SKILL_DIR on the first line to the skill folder that the Documentation Setup block in SKILL.md printed"; fi
```

## 1.3 Dependency ARM64 Compatibility Analysis

> **Output: `graviton-validation/03-dependency-compatibility-report.md`** and **`graviton-validation/raw/dependency-tree-native.txt`**

**IMPORTANT:** ARM64-incompatible native code can be introduced through transitive dependencies. A pure Java direct dependency may pull in a transitive with native code. Analyze the full tree.

### Generate Filtered Tree

The `-Dincludes` / grep filters below are a convenience view of *well-known* native artifacts. They are NOT the source of truth: a native lib whose coordinates are not listed (e.g. `jansi`, `commons-crypto`) will not appear here. The authoritative native inventory is the §1.2.1 check of the resolved JARs; cross-check the two and treat any JAR the check flagged as in scope even if it is absent from this filtered tree.

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
Evidence: §1.2.1 check: FINDING snappy-java-1.1.1.7.jar!org/xerial/snappy/native/Linux/x86_64/libsnappyjava.so: is x86-64; no aarch64 Linux build of this library in the scanned files
Minimum ARM64 Version: 1.1.2.2
Resolution: dependencyManagement override or exclusion+re-add
```

> ⚠️ **Verify the JAR, never the version number.** Run the §1.2.1 check on the *resolved* JAR: a path search such as `unzip -l <jar> | grep -i aarch64` misses builds stored under names such as `arm64/`, and old versions are often fine ([agent-scope-boundaries.md](agent-scope-boundaries.md)). Fetch a JAR with `curl -sSL --fail` and check the exit status: without `--fail` a 404 page is saved, which the check reports as `CHECK ... not an archive or a native file`. Confirm the version is listed in `maven-metadata.xml`. Check each candidate version in its own run: one run is judged as one classpath, so a version that fails can hide behind one that passes.

### Build-Tool Artifacts with OS/Arch Classifiers

Some build-time tools download a **platform-specific executable** that never appears in `dependency:tree` (it is resolved by a plugin, not as a normal dependency), so the steps above miss it entirely. The classic case: `protoc` pulled by `protobuf-maven-plugin`/`os-maven-plugin` via a classifier like `exe:${os.detected.classifier}`. If the pinned version has no `linux-aarch_64` classifier published, the build fails on Graviton with "Could not resolve artifact ...:exe:linux-aarch_64" — but only at build time.

Grep the build files for plugins/extensions that carry an OS/arch classifier and check the pinned versions:

```bash
grep -nE 'os-maven-plugin|protobuf-maven-plugin|os\.detected\.classifier|protocArtifact|:exe:|javacpp' \
  pom.xml build.gradle build.gradle.kts 2>/dev/null || true
```

For each hit, verify on Maven Central that the *pinned* version actually publishes the classifier it will be asked for, before declaring it compatible. There is no local artifact to inspect here: the plugin resolves it at build time, so it is absent from both `dependency:tree` and the §1.2.1 check. Query the repository directly:

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
  | while IFS= read -r f; do grep -qE '"aarch64"|"arm64"' "$f" || printf '%s\n' "$f"; done   # files comparing amd64/x86_64 but NOT aarch64
# Dockerfiles under any name, and deployment descriptors
if [ -f graviton-validation/raw/dockerfiles.txt ]; then
  while IFS= read -r f; do grep -nE -- '--platform=|@sha256:|BUILDPLATFORM|TARGETPLATFORM|TARGETARCH|x86_64|amd64' "$f" | grep -vE '^[0-9]+:[[:space:]]*#' | sed "s#^#$f:#"; done < graviton-validation/raw/dockerfiles.txt
else echo "CHECK: run the Determine Deployment Type block (§1.1) first: it writes graviton-validation/raw/dockerfiles.txt"; fi
grep -rniE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=cdk.out --include='*.y*ml' --include='*.json' --include='*.tf' \
  'architectures?"?[[:space:]]*[:=]|kubernetes\.io/arch|nodeselector|cpu_?architecture"?[[:space:]]*[:=]|ami_?type"?[[:space:]]*[:=]|instance_?types?"?[[:space:]]*[:=]|ami-[0-9a-f]{8,17}|^functions:|AWS::(Lambda::Function|Serverless::Function|ECS::TaskDefinition|EKS::Nodegroup)|requires_?compatibilities|resource "aws_(lambda_function|ecs_task_definition|eks_node_group)"|x86_64|amd64' . 2>/dev/null || true
# CDK apps: the constructs that take an architecture, and the settings, in each folder with a cdk.json
# (a construct that sets none gets x86_64)
find . \( -name .git -o -name .venv -o -name target -o -name node_modules -o -name cdk.out \) -prune -o -name cdk.json -print |
  while IFS= read -r c; do grep -rnE --exclude-dir=node_modules --exclude-dir=cdk.out --exclude-dir=target --exclude-dir=.venv --include='*.py' --include='*.ts' --include='*.js' \
    --include='*.java' --include='*.cs' --include='*.go' 'Architecture[._](X86_64|ARM_64)|CpuArchitecture[._](X86_64|ARM64)|AmazonLinuxCpuType[._]|MachineImage[._]|NodegroupAmiType[._]|InstanceType(\(|[._][Oo]f\()|InstanceClass[._]|(^|[^A-Za-z0-9_])(New)?(Function|DockerImageFunction|NodejsFunction|PythonFunction|GoFunction|FargateTaskDefinition|Nodegroup|Cluster)(\(|\.Builder)|[Aa]dd_?[Nn]odegroup_?[Cc]apacity' "$(dirname "$c")"; done | sort -u
# x86-only JVM options (HotSpot defines them only in its x86 port) in start scripts, Dockerfiles,
# Compose and Kubernetes files, task definitions, Terraform, systemd units, Maven and Gradle builds and JVM settings
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --exclude-dir=node_modules --include='*.sh' --include='*.cmd' --include='*.bat' \
  --include='Dockerfile*' --include='*.[Dd]ockerfile' --include='Containerfile*' --include='*.y*ml' --include='*.json' --include='*.service' \
  --include='*.conf' --include='*.properties' --include='*.env' --include=jvm.config --include=Procfile --include='*.gradle' --include='*.gradle.kts' --include='*.tf' --include=pom.xml -- \
  '-XX:[+-]?(AVX3Threshold|IntelJccErratumMitigation|RTM[A-Za-z]+|UseAVX|UseAddressNop|UseBMI[12]Instructions|UseCLMUL|UseCount(Leading|Trailing)ZerosInstruction|UseFastStosb|UseIncDec|UseKNLSetting|UseLibmIntrinsic|UseNewLongLShift|UseRTM[A-Za-z]+|UseSSE|UseSSE42Intrinsics|UseStoreImmI16|UseUnalignedLoadStores|UseXMMForObjInit|UseXmm[A-Za-z0-9]+)([^A-Za-z0-9]|$)' . 2>/dev/null || true
# JVM agents: -agentpath loads a native library before main, and an x86-64 one stops an ARM64 JVM ("Could not
# find agent library ... (Possible cause: can't load AMD 64 .so on a AARCH64 platform)"): judge each agent file
# by content (§1.2.1). -javaagent names a JAR: run the §1.2.1 check on it when the project tree does not hold it.
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --include='*.sh' --include='Dockerfile*' --include='*.[Dd]ockerfile' \
  --include='Containerfile*' --include='*.y*ml' --include='*.json' --include='*.service' --include='*.conf' \
  --include='*.properties' --include='*.env' --include=jvm.config --include=Procfile --include='*.gradle' --include='*.gradle.kts' --include='*.tf' --include=pom.xml -- '-agentpath:|-agentlib:|-javaagent:' . 2>/dev/null || true
# System calls made by number: the numbers differ (x86-64's 186 is gettid, aarch64's is 178, and 186 there
# is msgget), and open, fork, pipe, dup2 and poll have no aarch64 number at all (openat, clone, pipe2, dup3
# and ppoll do). Use the libc function or the target's SYS_ constant instead of the number.
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --include='*.java' --include='*.kt' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' -- \
  'syscall\([[:space:]]*(0x[0-9a-fA-F]+|[0-9]+)' . 2>/dev/null || true
# Types and build flags whose results differ by architecture (checked in Phase 3)
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' \
  --include=CMakeLists.txt --include=Makefile --include='*.mk' -- 'long double|__float128|longdouble|float128|float96|complex256|-ffast-math|-Ofast|-funsafe-math' . 2>/dev/null || true
# x86-only compiler flags and intrinsics in JNI sources the project builds (C, C++)
grep -rnE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' \
  --include='*.hpp' --include=CMakeLists.txt --include=Makefile --include='*.mk' -- '-m(avx|sse|fma|bmi|popcnt|pclmul|aes|crc32|f16c|lzcnt)|-march=|-mtune=|[a-z0-9]+intrin\.h|cpuid\.h|__builtin_ia32_|__cpuid|__rdtsc|__x86_64__|_M_X64|__SSE|__AVX|__m(128|256|512)|_mm[0-9]*_' . 2>/dev/null || true
```

Flag code that checks for "amd64" or "x86_64" without "aarch64" handling, loads native libraries without architecture-aware paths, or contains x86-specific assumptions.

An x86-only JVM option is a FINDING when the target JDK refuses it: HotSpot defines these options only in its x86 port, and an ARM64 JVM that does not know one stops before the application starts (`Unrecognized VM option 'UseAVX=2'`, then `Error: Could not create the Java Virtual Machine.`). JDK 17 and 21 refuse all of them, 11 accepts `UseSSE=<n>`, and 8 also `UseSSE42Intrinsics`. `-XX:+IgnoreUnrecognizedVMOptions` lets the JVM start, but it ignores every unrecognized option, not only these.

A setting that is absent also picks an architecture. A Lambda function that names none runs on x86_64, the default of the Lambda API, Terraform and the CDK, whose templates then carry no `Architectures`; a Fargate task definition without `cpuArchitecture` runs `X86_64`, and an ECS task on EC2 capacity without it goes where its capacity providers place it; an EKS managed node group with no instance type launches `t3.medium`, and the CDK's `aws-eks` `Cluster` without `defaultCapacityInstance` adds `m5.large` (x86) nodes, two unless `defaultCapacity` sets another count; the CDK's `MachineImage.latestAmazonLinux2023()` without `cpuType` picks the x86_64 AMI. So each function, task definition and node group the resource lines list needs an arm64 setting (Phase 2.4), whether or not an architecture line matched it. An image can also name one architecture: through its tag (`public.ecr.aws/lambda/java:21-x86_64`) or its repository (`amd64/eclipse-temurin:21-jre`). C or C++ sources the project builds for JNI need an Arm path for any x86 intrinsics they use: `sse2neon.h` ([sse2neon](https://github.com/DLTcollab/sse2neon)) implements the SSE to SSE4.2 and AES intrinsics with NEON, but no AVX (`_mm256_*`); port what it does not cover, and the hot paths found by profiling on Graviton, to NEON intrinsics. `long double` and fast-math flags change results between x86 and Graviton without an error: check them in Phase 3 (Results That Change Without Failing).

A Graviton instance type is a sizing decision: record it under User Decisions Pending with the default from Phase 2.4, also when no file in the repository names the hosts (the same series and size as the hosts' x86 instance type).

Every image the project builds from, tests with or deploys has to list `linux/arm64`, including images a library starts at run time: Testcontainers for Java 1.6.0 to 1.15.1 start a Ryuk image with no arm64 build (add it to the list), and 1.15.2 starts `testcontainers/ryuk:0.3.1`, which has one. List the images and read each one's platforms from its registry, without pulling it:

```bash
mkdir -p graviton-validation/raw
# Image references: FROM lines of the Dockerfiles in raw/dockerfiles.txt (§1.1; not stage names), image: keys in
# YAML and JSON, image names in test code. A reference built from a variable is left out: resolve it by hand.
{ if [ -f graviton-validation/raw/dockerfiles.txt ]; then
    while IFS= read -r f; do
      awk 'toupper($1) == "FROM" { i = ($2 ~ /^--platform=/) ? 3 : 2; if (!($i in s)) print $i
             for (k = i + 1; k < NF; k++) if (toupper($k) == "AS") s[$(k + 1)] = 1 }' "$f"
    done < graviton-validation/raw/dockerfiles.txt
  else echo "CHECK: run the Determine Deployment Type block (§1.1) first: it writes graviton-validation/raw/dockerfiles.txt" >&2; fi
  grep -rhoiE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --exclude-dir=node_modules --include='*.y*ml' --include='*.json' \
    '"?image(uri)?"?[[:space:]]*:[[:space:]]*"?[a-z0-9][^"[:space:],}]*' . |
    sed -E 's/^"?[Ii][Mm][Aa][Gg][Ee]([Uu][Rr][Ii])?"?[[:space:]]*:[[:space:]]*"?//'
  grep -rhoE --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv --include='*.java' --include='*.kt' \
    '(DockerImageName\.parse|Container(<[^>]*>)?)\("[^"]+"' . | sed -E 's/.*\("//; s/"$//'
} | grep -vE '\$|^scratch$' | sort -u > graviton-validation/raw/images.txt
# Platforms per image, from its registry (docker CLI). Without docker, or a login a private registry needs, the line is CHECK.
while IFS= read -r img; do
  if ! out=$(docker manifest inspect -v "$img" 2>&1); then printf 'CHECK   %s: %s\n' "$img" "$(printf '%s\n' "$out" | grep -v '^errors:$' | head -n 1)"
  elif printf '%s' "$out" | grep -q '"architecture": "arm64"'; then printf 'OK      %s\n' "$img"
  else printf 'FINDING %s: no linux/arm64 build\n' "$img"; fi
done < graviton-validation/raw/images.txt
```

`docker manifest inspect -v` prints every platform of a multi-architecture image and the one platform of a single-architecture image. A FINDING is fixed in Phase 2.4. On an ARM64 host a list without arm64 stops the pull (`no matching manifest for linux/arm64/v8 in the manifest list entries`), while a single amd64 manifest is pulled and its container stops with `exec format error` (`--platform linux/arm64` stops that pull: `was found but does not match the specified platform: wanted linux/arm64, actual: linux/amd64`).

## 1.5 Java Version Compatibility Check

> **Output: `graviton-validation/01-project-assessment.md`** (Java Environment section)

1. Document current Java version AND JDK distribution (e.g., "OpenJDK 21", "Corretto 17")
2. JDK 8: Supported with limitations. JDK 11+: Fully supported.
3. Flag known Graviton compatibility issues
4. **DO NOT change** the JDK distribution or Java version
5. All major distributions support ARM64 for Java 8+
