# Phase 1: Static Compatibility Analysis

Analyze the project without making changes. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below runs `pip`, `uv`, `poetry` or `conda`, use `python.package_manager` from `skill-config.md` (if defined) to skip auto-detection, `python.index_url` / `python.extra_index_url` as the index for every probe (and probe PyPI as well, see §1.3), and `python.interpreter_bump` in §1.5. See [skill-configuration.md](skill-configuration.md).

Phase 1 runs on any host, including x86, and installs nothing into the project or its environment. Most checks read files or ask the package index; three kinds of step run code. The §1.1 dry run (`pip install --dry-run` without `--only-binary`) runs the build backend (`setup.py` or the `pyproject.toml` backend) of every sdist it resolves, and of the project itself when the step installs `.`. The §1.1 target probe runs the base image's own `python3` in a container, and §1.2.2 runs the distribution's package tools in containers. The §1.3 probes pass `--only-binary=:all:`, so they never build or run a package. For a repository or an index you do not trust, run Phase 1 in a disposable container or VM. The project's own code and tests run only in Phase 3.

## Contents

- 1.1 Project Structure Analysis: Determine Deployment Type; Detect Multi-Module Structure; Detect Package Manager and Interpreter; Determine Target OS and glibc; Generate Dependency Tree; Categorize Components by Risk
- 1.2 Native Library Validation: 1.2.1 Statically Bundled .so Scanning; 1.2.2 Runtime-Extracted Native Library Detection; 1.2.3 Tiered Validation Policy
- 1.3 Dependency ARM64 Compatibility Analysis: Generate Filtered Tree; Classify Each Dependency; Document Findings; Build-Time Binaries Outside the Dependency Tree
- 1.4 Architecture-Specific Code Detection
- 1.5 Python Version Compatibility Check

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`**, **`graviton-validation/raw/dependency-tree-full.json`** and **`graviton-validation/raw/requirements-resolved.txt`**

### Determine Deployment Type

```bash
find . \( -path ./.venv -o -path ./.git -o -name node_modules -o -name cdk.out \) -prune -o \
  \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' -o -name 'Containerfile*' -o -name 'docker-compose*.y*ml' \
     -o -name 'template.y*ml' -o -name 'serverless.yml' -o -name 'cdk.json' -o -name '*.tf' \
     -o -name 'Procfile' -o -name '*.service' -o -name 'samconfig.toml' \) -print
grep -lE "AWS::Serverless::Function|AWS::Lambda::Function" template.yaml template.yml 2>/dev/null
# Dockerfiles under any name: by name, plus the files a build's -f or --file, Compose dockerfile: and
# docker/build-push-action file: name. A file is kept when it has a FROM line; a name that is no file
# here is printed: find that file by hand and add it to the list.
mkdir -p graviton-validation/raw
{ find . \( -path ./.venv -o -path ./.git -o -name node_modules -o -name cdk.out \) -prune -o -type f \( -name 'Dockerfile*' -o -name '*.[Dd]ockerfile' -o -name 'Containerfile*' \) -print
  grep -rnoE --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --include='*.sh' --include=Makefile --include='*.mk' --include='*.y*ml' --include='Jenkinsfile*' -- \
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
- SAM / CloudFormation / serverless template with a Lambda function: **Lambda** (also check for layer zips and a `python/` directory, §1.2.2)
- systemd unit, Procfile, or a plain `python -m app` entry point: **Host-based**
- A CDK app (`cdk.json`) or Terraform files define the infrastructure, and its architecture settings, in code (§1.4)
- Some applications support more than one; record all of them

### Detect Multi-Module Structure

- pip, setuptools, PEP 621: more than one directory with a `pyproject.toml`, `setup.py` or requirements file
- uv, Poetry, PDM: workspace members (`[tool.uv.workspace]`) and path dependencies (`path = "..."`, `develop = true`) link the packages
- If multi-package: enumerate all package directories, analyze each independently (§1.1 to §1.4), and report them as separate rows in the assessment
- Native code and x86-only pins may reside in any package; do NOT limit the analysis to the root manifest

```bash
# One line per directory that owns a manifest; more than one directory = monorepo
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -name pyproject.toml -o -name setup.py -o -name 'requirements*.txt' -o -name Pipfile -o -name 'environment.y*ml' \) -print \
  | sed 's#/[^/]*$##' | sort | uniq -c

# Workspace and path dependencies (uv, Poetry, PDM) link sub-packages together
grep -nE '^\[tool\.uv\.workspace\]|^\[tool\.uv\.sources\]|path = "|develop = true' pyproject.toml 2>/dev/null
```

### Detect Package Manager and Interpreter

Record every manager marker present, then decide which file the **deployment** installs from (that file is authoritative; a `pyproject.toml` kept only for packaging does not decide anything). Full detection table and per-manager commands: [package-manager-mapping.md](package-manager-mapping.md).

```bash
ls -1 requirements*.txt constraints*.txt pyproject.toml setup.py setup.cfg poetry.lock uv.lock \
      Pipfile Pipfile.lock pdm.lock environment.y*ml conda-lock.yml hatch.toml 2>/dev/null

# What does the deployment actually run? Dockerfile, Makefile, CI, scripts.
grep -nE "pip (install|sync)|uv (sync|pip install|export)|poetry (install|sync|export)|conda (env create|install)|pipenv (install|sync)|pdm (install|sync)" \
  Dockerfile Makefile *.sh .github/workflows/*.y*ml .gitlab-ci.yml buildspec.yml 2>/dev/null
```

Interpreter, in order of authority (the first hit decides; record its source):

```bash
grep -nE "^FROM" Dockerfile*                                  # python:3.11-slim -> 3.11
[ -f .python-version ] && cat .python-version                # pyenv / uv pin
grep -nE "requires-python|python_requires" pyproject.toml setup.py setup.cfg 2>/dev/null
grep -nE "^python_version|^[[:space:]]*runtime:|^[[:space:]]*- python[=>]" Pipfile template.y*ml environment.y*ml 2>/dev/null
```

Also record where that interpreter comes from (official image, distribution package, uv/pyenv/mise/asdf, conda) and its pip version: the origin decides which pip runs and whether pip is installed or allowed to install into it (Phase 3.0, "Where the interpreter comes from"). The interpreter decides the `cp3XY` tag every probe in §1.3 uses. A mismatch between sources (for example `.python-version` 3.12 but the Dockerfile ships `python:3.11-slim`) is itself a finding to record: probe with the deployed one.

### Determine Target OS and glibc

The wheel a pin resolves to must also be accepted by the target's libc and pip, and native code also depends on the kernel page size of the hosts it runs on (see [wheel-verification.md](wheel-verification.md) §1, §2 and §7). Read the libc and the interpreter from the runtime image:

`$CONTAINER_CMD` below is the working container runtime: run the detection block in [phase3-validation.md, Container Runtime Detection](phase3-validation.md#container-runtime-detection) first (in a new shell, set `CONTAINER_CMD` again; the block also applies `container.runtime` from `skill-config.md`). With no working runtime, follow the "No container runtime" item after the block.

```bash
IMG=$(awk '/^FROM/{img=$NF; for(i=2;i<=NF;i++) if($i !~ /^--platform/ && $i!="AS" && $i!="as") {img=$i; break}} END{print img}' Dockerfile)
# Ask the image's own python3: no shell, ldd or pip needed, the image's ENTRYPOINT is bypassed,
# and signal.alarm bounds the probe inside the container.
PROBE='
import glob, os, platform, re, signal, subprocess, sys, sysconfig
signal.alarm(120)
libc = ""
try:
    libc = os.confstr("CS_GNU_LIBC_VERSION") or ""
except (ValueError, OSError):
    pass
musl = glob.glob("/lib/ld-musl-*.so.1")
if not libc and musl:
    err = subprocess.run(musl[:1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True).stderr
    m = re.search(r"Version (\d+\.\d+)", err)
    libc = "musl " + (m.group(1) if m else "unknown")
family, _, version = (libc or "unknown").partition(" ")
prefix = {"glibc": "manylinux_2_", "musl": "musllinux_1_"}.get(family)
max_tag = prefix + version.rpartition(".")[2] + "_" + platform.machine() if prefix and version else "unknown"
try:
    import pip
    pip_version = pip.__version__
except ImportError:
    pip_version = "none"
try:
    import ensurepip
    venv = "yes"
except ImportError:
    venv = "no"
marker = os.path.exists(os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED"))
print("arch=%s libc=%s %s max_tag=%s python=%s (%s) pip=%s venv=%s externally_managed=%s" % (
    platform.machine(), family, version, max_tag, platform.python_version(), sys.executable, pip_version, venv, marker))
'
GV_IMG_ID=$($CONTAINER_CMD image inspect --format '{{.Id}}' "$IMG" 2> /dev/null)   # run --platform moves a local tag to the arm64 image; put back below
GV_IMGS=$($CONTAINER_CMD images -a -q --no-trunc 2> /dev/null) && GV_IMGS="listed: $GV_IMGS"; case $($CONTAINER_CMD --version 2> /dev/null) in "Docker version"*|"podman version"*) ;; *) GV_IMGS=;; esac   # the images here before the pull: the cleanup removes only one the pull added, and nothing if this listing fails or the CLI is neither docker nor podman (others may list image IDs in another form)
$CONTAINER_CMD run --rm --init --platform linux/arm64 --entrypoint python3 "$IMG" -c "$PROBE" ||
  $CONTAINER_CMD run --rm --init --platform linux/arm64 --entrypoint timeout "$IMG" 60 sh -c \
    'echo "arch=$(uname -m) libc=$(getconf GNU_LIBC_VERSION 2>/dev/null || ls /lib/ld-musl-* 2>/dev/null) python3=$(command -v python3 || echo none)"'
n=$($CONTAINER_CMD image inspect --format '{{.Id}}' "$IMG" 2> /dev/null); [ -z "$GV_IMG_ID" ] || [ "$n" = "$GV_IMG_ID" ] || $CONTAINER_CMD tag "$GV_IMG_ID" "$IMG"   # a moved tag goes back to the image it named
case $GV_IMGS in "") ;; *"${n#sha256:}"*) [ -n "$GV_IMG_ID" ] || [ -z "$n" ] || echo "NOTE: $IMG now names the arm64 image that was already here, so the tag stays (removing it could remove that image)";; *) $CONTAINER_CMD rmi "$n" > /dev/null 2>&1;; esac   # an image the pull added goes; one that was here stays
```

The probe asks the image's own `python3`, because `sh -c` with `ldd --version` and `pip debug` misreads common targets: it printed empty fields with exit code 0 for Alpine (its `ldd --version` prints no glibc version) and for images without `python3` or pip, and did not run in the Lambda base images or distroless, whose `ENTRYPOINT` receives the command as arguments. The limits are inside the container (`signal.alarm` in the probe, `timeout` in the fallback) because under emulation a host-side `timeout` does not reliably stop the container (Phase 3, "Emulation limits"). Record the libc as `TARGET_LIBC` and `TARGET_LIBC_VER` for §1.3: for `python:3.11-slim` the probe printed `libc=glibc 2.41`, so `TARGET_LIBC=glibc TARGET_LIBC_VER=2.41` (wheel-verification.md §7 lists other images).

For the native-file scan in §1.2.1, for the same image, copy its loaders and libraries into a folder with this block, which never starts the container. The check reads the C library from that folder, and passes a file only when the image has every library it needs from glibc, libstdc++ and libgcc_s and those define every version it needs, as the image's loader does (Amazon Linux 2023 reports glibc 2.34, yet its `libc.so.6` defines `GLIBC_2.35` and its `libm.so.6` does not).

> **Skill config:** `target.hosts` and `target.images` in `skill-config.md` add targets to the ones the repository names; a host's `page=` and `kernel=` count only when they were not measured there. The C library and its versions still come from each target's files.

```bash
IMG=python:3.11-slim   # the image the application runs on
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

§1.2.1 scans once for each target that `raw/target-roots.txt` records, with its image's folder as `TARGET_ROOT`. For a target with no image, record a name of its own and its lowest glibc version, such as `printf '%s\tglibc=%s\n' al2023-host 2.34 >> graviton-validation/raw/target-roots.txt` for an Amazon Linux 2023 host. The wheel probes of §1.3 still use `TARGET_LIBC` and `TARGET_LIBC_VER`.

- **No `python3` in the base image** (the fallback line): the deployment installs Python in a later step (`apt-get install python3`, `dnf install python3.11`), so the interpreter and pip come from that package. The libc still comes from the base image; read the rest from the built image or the distribution's package before §1.3.
- **Lambda functions deployed as .zip archives:** the runtime identifier sets the OS, as the runtimes table shows ([Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)): Amazon Linux 2023 has glibc 2.34, Amazon Linux 2 glibc 2.26; wheel-verification.md §7 shows a `manylinux_2_28` layer that imports on `python3.12` and fails on `python3.11`. AWS publishes a base image for each runtime, listed with its OS ([AWS base images for Python](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)): read the one for the function's runtime as for a container image; if it cannot be read, set `TARGET_LIBC_VER` to that OS's version and leave `TARGET_GLIBCXX` unset. For container-image functions, run the block against the image.
- **No arm64 variant of the base image:** both runs stop with `no matching manifest for linux/arm64 in the manifest list entries` (executed with `amazonlinux:2018.03`, whose manifest list has only `amd64`). That is a MUST UPGRADE finding, and the replacement image is a user decision ([agent-scope-boundaries.md](agent-scope-boundaries.md), OUT OF SCOPE).
- **No emulator on an x86 host:** both runs fail with `Exec format error`. Do not register one; take the C library and its version from the copy-out block's summary line above.
- **No container runtime:** use the table in wheel-verification.md §7 and say so. For host-based deployments read the AMI's distribution.
- **Kernel page size of the deployment hosts.** A container uses its host's kernel, so the page size comes from the EC2 hosts or Kubernetes nodes, not from the image: a Debian 13 container on an AlmaLinux 8 Graviton2 host reported 65536. Run `getconf PAGESIZE` on a deployment host (executed on Graviton: AlmaLinux 8.10 65536; AlmaLinux 9.8 and Amazon Linux 2023 4096); if no host can be reached, ask the team that runs them and record the page size as unknown until then. Set `TARGET_PAGE_SIZE` to the value in bytes: the scan in §1.2.1 judges page alignment only when it is set. A 64KB-page target needs Phase 3 on a 64KB-page host: on AlmaLinux 8, polars 0.20.20 aborted with `<jemalloc>: Unsupported system page size`, as did every earlier release tested back to 0.15.1, while 0.20.21 and the later releases tested imported. On the 4KB AlmaLinux 9 host polars 0.15.1 imported, so a 4KB validation host hides the failure.

Record `pip` on the target: below 19.3 it cannot install aarch64 wheels at all, and below 20.3 it cannot see `manylinux_2_N` tags; plan the `python3 -m pip install --upgrade pip` step for Phase 3. `pip=none` (the `python3` of Amazon Linux 2023 and AlmaLinux 9, and distroless) means pip has to come from a virtual environment or a distribution package; `venv=no` (distroless) means `python3 -m venv` does not work either.

### Generate Dependency Tree

Produce two artefacts: the manager-native tree (provenance: who pulls in what) and the **flat pinned list** that §1.3 probes. Per-manager commands are in package-manager-mapping.md §2.

> **Use the project's Python version for this step.** pip resolves for the interpreter that runs it, so run these commands with the project's minor version, not the analysis host's default: create the session-scoped environment from [phase3-validation.md](phase3-validation.md) §3.0 now, as below. Executed on the fixture with the host's default Python 3.12, the first resolution failed with `Failed to build 'pygeos' when getting requirements to build wheel`, because pygeos 0.14 has no cp312 wheel and pip tried to build it just to read its metadata.

The pip form:

```bash
GV_VENV=$(mktemp -d "${TMPDIR:-/tmp}/graviton-venv.XXXXXX")   # a new, private folder
uv venv --seed --python 3.11 "$GV_VENV"    # the project's minor version (Phase 3.0); --seed installs pip
. "$GV_VENV/bin/activate"
mkdir -p graviton-validation/raw
# One --dry-run --report per file the deployment installs, in the deployment's order.
# A hashed file turns on --require-hashes for everything in the same pip call, so keep it separate.
python3 -m pip install --dry-run --ignore-installed -q --report graviton-validation/raw/dependency-tree-locked.json \
  --require-hashes -r requirements-locked.txt
python3 -m pip install --dry-run --ignore-installed -q --report graviton-validation/raw/dependency-tree-full.json \
  -r requirements.txt

# Flat pins with provenance. Each pip call resolves on its own, so a package needed by both files
# can resolve to two versions, and the later call installs its version as well: keep every version.
python3 - <<'EOF'
import json
rows = {}
for rep, src in [("graviton-validation/raw/dependency-tree-locked.json", "requirements-locked.txt"),
                 ("graviton-validation/raw/dependency-tree-full.json", "requirements.txt")]:
    for i in json.load(open(rep))["install"]:
        key = (i["metadata"]["name"], i["metadata"]["version"])
        rows.setdefault(key, ("direct" if i.get("requested") else "transitive", src))
with open("graviton-validation/raw/requirements-resolved.txt", "w") as f:
    for (n, v), (kind, src) in sorted(rows.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1])):
        f.write(f"{n}=={v}  # {kind} via {src}\n")
EOF

# Sanity check: the list must contain resolved pins. An empty or one-line file is a failed
# resolution, not an all-clear.
grep -c '==' graviton-validation/raw/requirements-resolved.txt
```

When two install steps pin different versions of one package, keep and probe both: pip installs both into the same prefix, on any architecture (a hash-locked `charset-normalizer` 3.4.0 ended up next to the 3.5.2 that `requests` pulled in). The list also holds transitives that no requirements file names, such as the six that `mkl` pulls in. `pip install --dry-run` and `--report` require pip 22.2 or newer on the analysis host; on x86 the report lists x86 wheels, which is fine: §1.3 re-resolves for aarch64.

> **If `--dry-run` fails** on a hashed file with `Hashes are required in --require-hashes mode`, you passed a hashed and an unhashed file in one call: split them as above. If it fails on `pip install . --dry-run` with `Multiple top-level packages discovered in a flat-layout`, extract `[project].dependencies` with `tomllib` instead (package-manager-mapping.md §2.3).

### Categorize Components by Risk

- **CRITICAL**: committed or vendored `.so` files, in-repo extension modules, `ctypes`/`cffi` loads, Lambda layers with binaries
- **HIGH**: pinned native-wheel dependencies (numpy, pandas, pillow, cryptography, grpcio, torch, ...), hash-locked requirements, conda explicit files
- **MEDIUM**: Dockerfiles, deployment scripts, CI files, architecture detection code
- **LOW**: pure-Python dependencies (`none-any` wheels) and pure-Python application code

## 1.2 Native Library Validation (.so File Analysis)

> **Output: `graviton-validation/02-native-library-report.md`** and **`graviton-validation/raw/site-packages-so-scan-<target>.txt`** (one per target)

Native code reaches a Python deployment in three ways: **wheels** from the index (handled in §1.3 by probing the index, not by scanning), **binaries committed to the repository** (vendored `.so`, Lambda layers, pre-built modules), and **extensions the project builds itself** (`setup.py` `ext_modules`, Cython, Rust, pybind11, CMake). This section covers the last two. All three depend on the target OS as well as the CPU (libc, page size, CPU generation, OS packages; [wheel-verification.md](wheel-verification.md) §1).

### 1.2.1 Statically Bundled .so Scanning

Scan the project tree for every native file and judge it by its content (its first bytes and its headers), never by its name, extension or folder: an executable can have no extension, a file named `libfoo-aarch64.so` can hold x86-64 code, and a Lambda layer zip or a vendored `py3-none-any` wheel can carry binaries. The scan opens every file, the members of zip archives and the objects in static archives (`.a`). It skips installed environments (directories with `pyvenv.cfg` or `conda-meta`), whose packages are judged by wheel in §1.3 and scanned the same way in Phase 3.1. For each Linux (ELF) file it prints the architecture, the C library the file was built for (glibc, musl, Android's bionic, or none), the highest `GLIBC_` version it needs from glibc's own libraries, the highest `GLIBCXX_` version it needs from libstdc++, its page alignment and the libraries it needs (`needs`, its DT_NEEDED list); Mach-O and PE files are listed as macOS and Windows builds. It then judges each file for the target of §1.1 (`TARGET_ROOT`, or `TARGET_LIBC` and `TARGET_LIBC_VER`, and `TARGET_PAGE_SIZE`): a `FINDING` line per problem, a `CHECK` line for what only a load in the target image settles, and `NOTE` lines. The scan only reads files, so no project code runs. It needs only Python 3.6 or later, so it also runs where `file` and `readelf` are missing:

```bash
TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41; TARGET_PAGE_SIZE=4096   # from §1.1 (Alpine: TARGET_LIBC=musl TARGET_LIBC_VER=1.2)
# native_scan PATH...: every native file under PATH, found by its first bytes (not its name or extension),
# including members of zip archives (Lambda layer zips, vendored wheels, eggs) and of static archives (.a).
# Installed environments (directories with pyvenv.cfg or conda-meta) are skipped: Phase 3 scans them.
# Each Linux file is judged for the target in TARGET_ROOT (the image's files, §1.1) or else TARGET_LIBC, TARGET_LIBC_VER
# and, when known, TARGET_GLIBCXX, with TARGET_PAGE_SIZE: FINDING, CHECK and NOTE lines, then "findings: N, checks: M";
# exit status 1 on a FINDING.
native_scan() {
TARGET_LIBC="${TARGET_LIBC-}" TARGET_LIBC_VER="${TARGET_LIBC_VER-}" TARGET_PAGE_SIZE="${TARGET_PAGE_SIZE-}" \
  TARGET_GLIBCXX="${TARGET_GLIBCXX-}" TARGET_ROOT="${TARGET_ROOT-}" python3 - "$@" <<'EOF'
import collections, hashlib, io, os, re, struct, sys, zipfile
ARCH = {3: "i386", 40: "arm", 62: "x86-64", 183: "aarch64", 243: "riscv"}
OS_ABI = {1: "HP-UX", 2: "NetBSD", 6: "Solaris", 7: "AIX", 9: "FreeBSD", 12: "OpenBSD"}  # EI_OSABI of other systems
GLIBC_LIBS = re.compile(r"(libc\.so\.6|libm\.so\.6|libpthread\.so\.0|libdl\.so\.2|librt\.so\.1|libresolv\.so\.2"
                        r"|libutil\.so\.1|libanl\.so\.1|libmvec\.so\.1|libnsl\.so\.1|ld-linux[-a-z0-9_.]*\.so\.[0-9]+)$")
MUSL_SELF = ("c.", "pthread.", "rt.", "m.", "dl.", "util.", "xnet.")  # "lib" + these: names musl's loader answers itself
# Names musl's loader resolves to musl's own name without "64" when no library defines them (get_lfs64 in
# ldso/dynlink.c; musl 1.2.4 and later define only the names without "64"), and readdir64_r to readdir_r
MUSL_LFS64 = frozenset(("aio_cancel aio_error aio_fsync aio_read aio_return aio_suspend aio_write alphasort creat "
                        "fallocate fgetpos fopen freopen fseeko fsetpos fstat fstatat fstatfs fstatvfs ftello "
                        "ftruncate ftw getdents getrlimit glob globfree lio_listio lockf lseek lstat mkostemp "
                        "mkostemps mkstemp mkstemps mmap nftw open openat posix_fadvise posix_fallocate pread preadv "
                        "prlimit pwrite pwritev readdir scandir sendfile setrlimit stat statfs statvfs tmpfile "
                        "truncate versionsort __fxstat __fxstatat __lxstat __xstat").split())
# Architecture and C library parts of file names, removed to find the builds of one library
NAME_PARTS = re.compile(r"[-_.](x86[-_]64|x86[-_]32|x64|x86|amd64|i[3-6]86|aarch[-_]?64|arm64|arm[-_]?32|armv[5-8][a-z]*|"
                        r"armhf|armel|arm|ppc(le)?[-_]?64(le)?|ppc|s390x?|s390[-_]64|riscv[-_]?64|loongarch[-_]?64|"
                        r"mips(64)?(el)?|musl|gnu|glibc)(?=[-_.]|$)", re.I)
# A target image's files (TARGET_ROOT): the folders its loader searches, and the libraries whose files say what the
# image provides: glibc's libraries and loader (the first eleven), musl's loader, libstdc++ and libgcc_s
ROOT_DIRS = ("lib", "lib64", "usr/lib", "usr/lib64", "lib/aarch64-linux-gnu", "usr/lib/aarch64-linux-gnu")
GNU_EXT = re.compile(r"\.cpython-3(1[1-9]|[2-9][0-9])[a-z]*-[a-z0-9_]+-linux-gnu\.so$")  # a glibc CPython 3.11+ module suffix (3.10 and earlier on musl use -linux-gnu.so too)
ROOT_LIBS = ("libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1", "libresolv.so.2", "libutil.so.1",
             "libanl.so.1", "libmvec.so.1", "libnsl.so.1", "ld-linux-aarch64.so.1", "ld-musl-aarch64.so.1",
             "libstdc++.so.6", "libgcc_s.so.1")

def root_file(root, rel):
    """The file rel names in root (a target image's files), following symbolic links as the image would, an absolute
    link pointing into root; None when the image has no such file."""
    parts, done, hops = [x for x in rel.split("/") if x not in ("", ".")], [], 0
    while parts and hops < 40:
        x = parts.pop(0)
        if x == "..":
            done = done[:-1]
        elif os.path.islink(os.path.join(root, *(done + [x]))):
            link, hops = os.readlink(os.path.join(root, *(done + [x]))), hops + 1
            parts = [y for y in link.split("/") if y not in ("", ".")] + parts
            done = [] if link.startswith("/") else done
        else:
            done.append(x)
    p = os.path.join(root, *done)
    return p if not parts and os.path.isfile(p) else None

def root_defines(b):
    """(e_machine, the version names an ELF library defines through DT_VERDEF, without its own name)."""
    if len(b) < 64 or b[:4] != b"\x7fELF" or b[4] != 2 or b[5] != 1:
        return 0, []
    machine, phoff = struct.unpack_from("<H", b, 18)[0], struct.unpack_from("<Q", b, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", b, 54)
    loads, tags = [], {}
    for k in range(phnum):
        o = phoff + k * phentsize
        if o + 56 > len(b):
            break
        p_type = struct.unpack_from("<I", b, o)[0]
        p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from("<QQQQ", b, o + 8)
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == 2:
            for q in range(p_offset, min(len(b), p_offset + p_filesz) - 15, 16):
                tag, val = struct.unpack_from("<qQ", b, q)
                if tag == 0:
                    break
                tags.setdefault(tag, val)

    def off(va):
        return next((va - v + o for v, o, sz in loads if v <= va < v + sz), None)
    st, o, names = off(tags.get(5, -1)), off(tags.get(0x6FFFFFFC, -1)), []  # DT_STRTAB, DT_VERDEF
    for _ in range(tags.get(0x6FFFFFFD, 0)):  # DT_VERDEFNUM
        if o is None or st is None or o + 20 > len(b):
            break
        _v, flags, _x, cnt, _h, aux, nxt = struct.unpack_from("<HHHHIII", b, o)
        if cnt and not flags & 1 and o + aux + 8 <= len(b):  # VER_FLG_BASE (1) marks the library's own name
            n = st + struct.unpack_from("<I", b, o + aux)[0]
            names.append(b[n:b.find(b"\0", n)].decode("latin-1"))
        if not nxt:
            break
        o += nxt
    return machine, names

def elf_sections(read):
    """(sh_type, sh_offset, sh_size, sh_link) of every section of an ELF64 little-endian file, through read(off, n)."""
    h = read(0, 64)
    if len(h) < 64:
        return []
    shoff, shentsize, shnum = struct.unpack("<Q", h[40:48])[0], struct.unpack("<H", h[58:60])[0], struct.unpack("<H", h[60:62])[0]
    if not shoff or shentsize < 64 or shnum > 65535:
        return []
    sh = read(shoff, shentsize * shnum)
    out = []
    for k in range(0, len(sh) - shentsize + 1, shentsize):
        _name, sh_type, _flags, _addr, sh_offset, sh_size, sh_link = struct.unpack("<IIQQQQI", sh[k:k + 44])
        out.append((sh_type, sh_offset, sh_size, sh_link))
    return out


def dynamic_symbols(read):
    """(defined names, [(undefined name, binding, version index)]) from .dynsym and .gnu.version; ([], []) when the
    file has no section headers (a stripped loader keeps them; .dynsym is needed at run time and stays)."""
    secs = elf_sections(read)
    dynsym = next((s for s in secs if s[0] == 11), None)
    if dynsym is None or dynsym[3] >= len(secs):
        return [], []
    strtab, versym = secs[dynsym[3]], next((s for s in secs if s[0] == 0x6FFFFFFF), None)
    syms, strs = read(dynsym[1], dynsym[2]), read(strtab[1], strtab[2])
    vers = read(versym[1], versym[2]) if versym else b""
    defined, undefined = [], []
    for k in range(1, len(syms) // 24):
        st_name, st_info, _other, st_shndx = struct.unpack("<IBBH", syms[24 * k:24 * k + 8])
        end = strs.find(b"\0", st_name)
        name = strs[st_name:end if end >= 0 else len(strs)].decode("latin-1")
        if not name:
            continue
        if st_shndx:
            defined.append(name)
        else:
            v = struct.unpack("<H", vers[2 * k:2 * k + 2])[0] & 0x7FFF if 2 * k + 2 <= len(vers) else 0
            undefined.append((name, st_info >> 4, v))
    return defined, undefined


def has_dynsym(read):
    """Whether the file's section headers lead to a .dynsym, the table glibc_imports reads: without one, the file's
    imports are unknown, which is not the same as none."""
    secs = elf_sections(read)
    d = next((s for s in secs if s[0] == 11), None)
    return d is not None and d[3] < len(secs)


def glibc_imports(read, vlib, is_glibc):
    """The undefined, non-weak dynamic symbols a file takes from a glibc library (vlib: version index to library,
    from DT_VERNEED), sorted: what the target's C library must define for the file's calls to work."""
    return sorted(set(n for n, binding, v in dynamic_symbols(read)[1] if binding != 2 and is_glibc(vlib.get(v, ""))))


def read_root(root):
    """What a target image's files say: its C library, glibc release, the versions each library of ROOT_LIBS in it
    defines, whether a musl image also has a glibc loader (gcompat), its highest GLIBCXX_ version and its os-release
    name. A string saying why when root cannot be judged."""
    if not os.path.isdir(root):
        return "no such folder: %s" % root
    t = {"root": root, "libc": "", "release": "", "defs": {}, "os": "", "glibc_loader": False, "glibcxx": "", "syms": set(),
         "musl_syms": set(), "compat": "", "compat_syms": set(), "paths": {}, "files": set(), "libs": set()}
    for rel in ("etc/os-release", "usr/lib/os-release"):
        p = root_file(root, rel)
        if p:
            with open(p, errors="replace") as f:
                m = re.search(r'^PRETTY_NAME="?([^"\n]*)', f.read(), re.M)
            t["os"] = m.group(1) if m else ""
            break
    machines = set()
    for name in ROOT_LIBS:
        p = next((x for x in (root_file(root, d + "/" + name) for d in ROOT_DIRS) if x), None)
        if p:
            with open(p, "rb") as f:
                b = f.read()
            machine, t["defs"][name] = root_defines(b)
            machines.add(machine)
            defined = dynamic_symbols(lambda o, n, b=b: b[o:o + n])[0]  # what the library defines
            t["syms"].update(defined)
            t["paths"][name] = p  # the file the name leads to (gcompat links several names to one file)
            if name == "ld-musl-aarch64.so.1":  # musl's own symbols: what its loader resolves a glibc build's imports to
                t["musl_syms"] = set(defined)
            elif name == "libc.so.6":  # on a musl image, a glibc compatibility library (gcompat's)
                t["compat"], t["compat_syms"] = "/" + os.path.relpath(p, root).replace(os.sep, "/"), set(defined)
            m = re.search(rb"release version ([0-9]+\.[0-9]+)", b) if name == "libc.so.6" else None
            t["release"] = m.group(1).decode() if m else t["release"]
    lst = os.path.join(root, "gv-image-libs.txt")  # the copy-out block's list of every shared library's name in the image
    if os.path.isfile(lst):
        with open(lst, errors="replace") as f:
            t["libs"] = set(x.strip() for x in f if x.strip())
    db = root_file(root, "lib/apk/db/installed")  # Alpine: every file its packages installed (F: folder, R: name)
    if db:
        with open(db, errors="replace") as f:
            folder = ""
            for line in f:
                folder = line[2:].strip() if line.startswith("F:") else folder
                if line.startswith("R:") and folder in ROOT_DIRS:
                    t["files"].add(line[2:].strip())
    if "ld-musl-aarch64.so.1" in t["defs"]:
        t["libc"], t["glibc_loader"] = "musl", "ld-linux-aarch64.so.1" in t["defs"]
    elif "libc.so.6" in t["defs"]:
        t["libc"] = "glibc"
    else:
        return ("%s has neither glibc's libc.so.6 nor musl's ld-musl-aarch64.so.1 in %s: copy the target image's "
                "files there first" % (root, ", ".join(ROOT_DIRS)))
    if machines - {183}:
        return "the libraries in %s are not aarch64 (e_machine %s): copy them from the image for linux/arm64" % (
            root, ", ".join(str(x) for x in sorted(machines - {183})))
    cxx = [v[8:] for v in t["defs"].get("libstdc++.so.6", []) if re.match(r"^GLIBCXX_[0-9]+(\.[0-9]+)*$", v)]
    t["glibcxx"] = max(cxx, key=lambda v: tuple(int(x) for x in v.split("."))) if cxx else ""
    return t

def root_needs(vers, t):
    """Findings for the versions a glibc file needs ((library, version) pairs) that the image's copy of that library
    does not define, the check glibc's loader makes: one per library and version prefix, naming the highest one
    missing. A version needed from one of glibc's libraries that the image lacks is compared with its glibc release."""
    def num(s):
        return tuple(int(x) for x in s.split("."))
    p = []
    for lib in sorted(set(x for x, _ in vers)):
        have = t["defs"].get(lib)
        if have is None:
            v = [n[6:] for x, n in vers if x == lib and lib in ROOT_LIBS[:11] and re.match(r"^GLIBC_[0-9]+(\.[0-9]+)*$", n)]
            if v and t["release"] and num(max(v, key=num)) > num(t["release"]):
                p.append("needs GLIBC_%s from %s; the image has no %s, and its glibc is %s" % (
                    max(v, key=num), lib, lib, t["release"]))
            continue
        top = {}
        for n in sorted(set(n for x, n in vers if x == lib and n not in have)):
            m = re.match(r"^(.*?_)([0-9]+(\.[0-9]+)*)$", n)
            k = m.group(1) if m else n
            if k not in top or m and num(m.group(2)) > num(top[k][len(k):]):
                top[k] = n
        for k, n in sorted(top.items()):
            known = [d[len(k):] for d in have if k != n and d.startswith(k) and re.match(r"^[0-9]+(\.[0-9]+)*$", d[len(k):])]
            p.append("needs %s from %s; the target's %s %s" % (n, lib, lib, "defines up to %s%s" % (
                k, max(known, key=num)) if known else "does not define it"))
    return p

def root_has(t, names):
    """The names (libraries, or "interpreter <path>") that the target image's files provide; none without a root."""
    if not t:
        return []
    return [n for n in names if (root_file(t["root"], n[12:]) if n.startswith("interpreter ") else
                                 any(root_file(t["root"], d + "/" + n) for d in ROOT_DIRS))]

ROOT_OPTION = "TARGET_ROOT"


EFFECT = "the import fails (Python imports extension modules with RTLD_NOW)"


def musl_resolve(imports, t, needed=()):
    """(missing, preload) for a glibc build's imports on a musl image t, looked up as musl's loader does for the file:
    in musl itself (ld-musl-aarch64.so.1), where a name musl lacks that ends in 64 resolves to the name without 64
    (MUSL_LFS64). missing: no library of the image defines the name. preload: only the image's glibc compatibility
    library (gcompat's libc.so.6) defines it: musl's loader answers the glibc library names itself, so that file
    reaches the build only through LD_PRELOAD, unless the build needs it by another name (needed: its DT_NEEDED)."""
    own = t["musl_syms"]
    left = [n for n in imports if n not in own and not (
        "readdir_r" in own if n == "readdir64_r" else n[-2:] == "64" and n[:-2] in MUSL_LFS64 and n[:-2] in own)]
    by_name = any(t["paths"].get(n) == t["paths"].get("libc.so.6") for n in needed
                  if n in t["paths"] and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)))
    return ([n for n in left if n not in t["syms"]],
            [] if by_name else [n for n in left if n in t["compat_syms"]])


def musl_preload(names, t):
    """The CHECK for imports that only the image's glibc compatibility file defines (musl_resolve's preload)."""
    where = t["compat"]
    return ("glibc build; the image defines %s%s only in %s, which musl's loader does not search for this file: the "
            "definitions reach it only when the process preloads that file (LD_PRELOAD=%s); without the preload, %s; "
            "settle it in the target image with the deployment's own environment" % (
                ", ".join(names[:4]), " and %d more" % (len(names) - 4) if len(names) > 4 else "", where, where, EFFECT))


def musl_unread():
    """The CHECK for a glibc build on a musl image whose dynamic symbol table could not be read."""
    return ("glibc build whose dynamic symbol table could not be read (no section headers), so its glibc imports were "
            "not resolved against the image's musl; for a symbol musl does not define, %s; settle it with musl's ldd "
            "(/lib/ld-musl-aarch64.so.1 --list FILE) in the target image, which lists each one" % EFFECT)


def musl_check(own, image, other=()):
    """The CHECK for a glibc build on a musl target when neither musl's loader nor the image refuses it. other: the
    build's other libraries, which the target image must provide (SkiaSharp 2.88.6: libfontconfig.so.1)."""
    only = "" if other else "only "
    also = "; it also needs %s, which the target image must provide" % ", ".join(other) if other else ""
    if not image:
        return ("glibc build that needs %slibraries musl's loader provides (%s)%s; settle it by resolving its glibc "
                "imports against the image's files (%s): a symbol the image does not define is a FINDING: Python imports "
                "extension modules with RTLD_NOW, so the import fails with symbol not found" % (only, ", ".join(own), also, ROOT_OPTION))
    by_loader = [n for n in own if n not in image]
    return "glibc build that needs %s%sfiles the target image has (%s)%s; settle it by resolving its glibc imports against the image's files (%s)" % (
        only, "libraries musl's loader provides (%s) and " % ", ".join(by_loader) if by_loader else "", ", ".join(image),
        also, ROOT_OPTION)

def needs_other(names, t):
    """The CHECK for a file that needs libraries other than glibc's, libstdc++ and libgcc_s which the target image does
    not have (its list of shared libraries; for a musl image, else its package list or copied files) and which the
    scanned files do not ship."""
    where = ("the target image does not have" if t["libs"] else "no package of the target image installs" if t["files"]
             else "the copied files of the target image do not include")
    return "needs %s, which %s; settle it by finding %s in the image the project deploys" % (
        ", ".join(names), where, "the library" if len(names) == 1 else "the libraries")



def libs_notes(t):
    """The NOTE for a target folder without the image's library list (gv-image-libs.txt): the other libraries the files
    need were then not checked against the whole image."""
    if not t or t["libs"] or t["libc"] == "musl" and t["files"]:
        return []
    return ["target: %s has no gv-image-libs.txt (the copy-out block's list of the image's libraries), so other libraries "
            "the files need were not checked against the whole image" % t["root"]]


def root_shared(probs, x86_vers):
    """The version of a per-library finding (probs) that the x86-64 build needs from the same library too."""
    for p in probs:
        m = re.match(r"^needs (\S+) from (\S+);", p)
        if m and (m.group(2), m.group(1)) in x86_vers:
            return m.group(1)
    return ""

def root_read_from(t):
    """The end of the target line when the target was read from an image's files."""
    return (", read from %s%s" % (t["root"], " (%s)" % t["os"] if t["os"] else "")) if t else ""

# TARGET_ROOT: the image's files give the C library and its versions, and TARGET_LIBC and TARGET_LIBC_VER
# (which the wheel probes use) and TARGET_GLIBCXX are not used by the scan
ROOT, IGNORED = None, [v for v in ("TARGET_LIBC", "TARGET_LIBC_VER", "TARGET_GLIBCXX") if os.environ[v]]
if os.environ["TARGET_ROOT"]:
    ROOT = read_root(os.environ["TARGET_ROOT"])
    if not isinstance(ROOT, dict):
        print("ERROR: " + ROOT)
        sys.exit(2)
ASSUMED = not (os.environ["TARGET_LIBC"] or ROOT)  # no target given: judge against glibc and say so
LIBC = ROOT["libc"] if ROOT else os.environ["TARGET_LIBC"] or "glibc"
VER = "" if ROOT else os.environ["TARGET_LIBC_VER"]
REL = VER or (ROOT["release"] if ROOT else "")  # the glibc release, for the page-alignment rule
if LIBC not in ("glibc", "musl"):
    print("ERROR: TARGET_LIBC is glibc or musl")
    sys.exit(2)
CXX = "" if ROOT else os.environ["TARGET_GLIBCXX"].replace("GLIBCXX_", "")
if not re.match(r"[0-9]*$", os.environ["TARGET_PAGE_SIZE"]):
    print("ERROR: TARGET_PAGE_SIZE is a number of bytes, for example 65536")
    sys.exit(2)
PAGE = int(os.environ["TARGET_PAGE_SIZE"] or 0)
entries, machines = [], collections.Counter()

def vkey(v):
    return tuple(int(x) for x in re.findall(r"[0-9]+", v))

def add(name, box, desc, **kw):  # box: the archive that holds the file, or the path given for loose files
    e = {"name": name, "box": box, "desc": desc, "probs": [], "checks": [], "loadable": False, "small": False}
    e.update(kw)
    entries.append(e)
    return e

def reader(src):  # read(offset, size) on bytes or on an open file, never past its end
    if isinstance(src, bytes):
        return lambda o, n: src[o:o + n] if o >= 0 and n > 0 else b""
    size = os.fstat(src.fileno()).st_size
    def read(o, n):
        if o < 0 or n <= 0 or o >= size:
            return b""
        src.seek(o)
        return src.read(min(n, size - o))
    return read

def elf(name, box, read):
    h = read(0, 64)
    etype, machine = struct.unpack(">HH" if h[5] == 2 else "<HH", h[16:20])
    machines[machine] += 1
    arch = ARCH.get(machine, "other")
    head = "e_machine %d (%s)" % (machine, arch) + (", ELF32" if h[4] == 1 else "") + (", big-endian" if h[5] == 2 else "")
    other = machine != 183 or h[4] != 2 or h[5] != 1
    if etype == 1:  # an object file: a build input that no loader reads
        e = add(name, box, head + ", relocatable object")
        if other:
            e["checks"].append("object file with no aarch64 code (%s); a native arm64 build that links it fails" % head)
        return
    if etype == 4:
        return add(name, box, head + ", core dump")
    if h[7] in OS_ABI:
        return add(name, box, head + " (a %s build; Linux does not load it)" % OS_ABI[h[7]])
    if h[4] != 2 or h[5] != 1:  # 32-bit or big-endian: not read further
        return add(name, box, head, probs=["not aarch64, " + head], loadable=True, arch=arch, libc="", glibc="", cxx="", vers=[])
    phoff = struct.unpack("<Q", h[32:40])[0]
    phentsize, phnum = struct.unpack("<HH", h[54:58])
    loads, dyn, interp, android, phentsize = [], b"", "", False, phentsize or 56
    ph = read(phoff, phentsize * phnum)
    for k in range(0, len(ph) - 55, phentsize):
        p_type = struct.unpack("<I", ph[k:k + 4])[0]
        p_offset, p_vaddr, _, p_filesz, _, p_align = struct.unpack("<6Q", ph[k + 8:k + 56])
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz, p_align))
        elif p_type == 2:
            dyn = read(p_offset, p_filesz)
        elif p_type == 3:
            interp = read(p_offset, p_filesz).split(b"\0")[0].decode("latin-1")
        elif p_type == 4:  # notes: one owned by "Android" marks a build for Android's C library (bionic)
            n, o = read(p_offset, min(p_filesz, 65536)), 0
            while o + 12 <= len(n):
                namesz, descsz = struct.unpack("<II", n[o:o + 8])
                android = android or n[o + 12:o + 12 + namesz].rstrip(b"\0") == b"Android"
                o += 12 + (namesz + 3) // 4 * 4 + (descsz + 3) // 4 * 4

    def off(va):  # file offset of a virtual address
        for v, o, sz, _ in loads:
            if v <= va < v + sz:
                return o + va - v
        return -1
    tags, needed = {}, []
    for k in range(0, len(dyn) - 15, 16):
        tag, val = struct.unpack("<qQ", dyn[k:k + 16])
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        else:
            tags.setdefault(tag, val)
    st = read(off(tags[5]), tags.get(10, 1 << 20)) if 5 in tags else b""

    def string(o):
        e = st.find(b"\0", o)
        return st[o:e if e >= 0 else len(st)].decode("latin-1")
    names, vers, vlib = [string(n) for n in needed], [], {}
    osname = [s for n, s in (("libc.so.7", "FreeBSD"), ("libc.so.12", "NetBSD"), ("libc.so.1", "Solaris")) if n in names] + [
        "OpenBSD" for n in names if re.match(r"libc\.so\.[0-9]+\.[0-9]+$", n)]
    if osname:  # the C library of another system
        return add(name, box, head + " (a %s build; Linux does not load it)" % osname[0])
    o = off(tags[0x6FFFFFFE]) if 0x6FFFFFFE in tags else -1  # DT_VERNEED: the versions needed, by library
    for _ in range(tags.get(0x6FFFFFFF, 0) if o >= 0 else 0):
        vn = read(o, 16)
        if len(vn) < 16:
            break
        _, cnt, vfile, aux, nxt = struct.unpack("<HHIII", vn)
        a = o + aux
        for _ in range(cnt):
            va = read(a, 16)
            if len(va) < 16:
                break
            vname, anxt = struct.unpack("<II", va[8:16])
            vers.append((string(vfile), string(vname)))
            vlib[struct.unpack("<H", va[6:8])[0] & 0x7FFF] = string(vfile)  # .gnu.version index of this version need
            if not anxt:
                break
            a += anxt
        if not nxt:
            break
        o += nxt

    def top(prefix, lib):  # highest version with this prefix needed from the libraries lib() accepts
        v = [n[len(prefix):] for f, n in vers if n.startswith(prefix) and lib(f) and re.match(r"[0-9.]+$", n[len(prefix):])]
        return max(v, key=vkey) if v else ""
    glibc = top("GLIBC_", GLIBC_LIBS.match)  # from glibc's own libraries only, not from libgcc_s or others
    relr = any(n == "GLIBC_ABI_DT_RELR" and GLIBC_LIBS.match(f) for f, n in vers)  # pack-relative relocations, glibc 2.36
    imports = glibc_imports(read, vlib, GLIBC_LIBS.match) if any(GLIBC_LIBS.match(f) for f, _ in vers) else []
    syms_read = has_dynsym(read)  # whether the imports could be read at all
    cxx = top("GLIBCXX_", lambda f: f.startswith("libstdc++"))
    if "libc.so" in names or interp.startswith("/system/"):
        libc = "android" if android or interp.startswith("/system/") else "musl"
    elif any(n.startswith("libc.musl") for n in names) or "ld-musl" in interp:
        libc = "musl"
    elif any(GLIBC_LIBS.match(n) for n in names) or "ld-linux" in interp:
        libc = "glibc"
    elif not names and not interp:
        libc = "needs no C library"
    else:
        libc = "C library not named"
    align = min(a for _, _, _, a in loads) if loads else 0
    voff = min([(v - o) & (o - v) for v, o, _, _ in loads if v != o] or [0])  # largest power of two dividing p_vaddr - p_offset
    desc = head + ", " + libc + "".join(", " + x for x in ("GLIBC_" + glibc if glibc else "", "GLIBCXX_" + cxx if cxx else "") if x)
    desc += (", LOAD align %#x" % align if loads else "") + (", vaddr-offset align %#x" % voff if 0 < voff < 0x10000 else "")
    desc += ", needs " + " ".join(names) if names else ""
    e = add(name, box, desc, loadable=True, arch=arch, libc=libc, glibc=glibc, cxx=cxx, vers=vers, needed=names, soname=string(tags[14]) if 14 in tags else "",
            interp=interp, imports=imports)
    p, c = e["probs"], e["checks"]
    if other:
        return p.append("not aarch64, " + head)
    e["small"] = bool(loads) and (align < 0x10000 or 0 < voff < 0x10000)
    if LIBC == "musl" and GNU_EXT.search(name):  # CPython on musl imports no module by this name
        p.append("module named for a glibc Python (%s): CPython 3.11 and later on musl import only -linux-musl.so, "
                 ".abi3.so and .so modules, so this file is never loaded (the package falls back to pure Python or fails to "
                 "import)" % GNU_EXT.search(name).group(0))
    elif libc == "android":
        p.append("Android build (bionic C library), not for glibc or musl")
    elif libc == "musl" and LIBC == "glibc":
        p.append("musl build; the target uses glibc")
    elif libc == "glibc" and LIBC == "musl":
        own = [n for n in names if GLIBC_LIBS.match(n)]
        refused = (["interpreter " + interp] if "ld-linux" in interp else []) + [
            n for n in own if not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
        image = root_has(ROOT, refused)  # the image's own files (gcompat's glibc loader, for example)
        refused = [n for n in refused if n not in image]
        if refused:
            p.append("glibc build; musl's loader does not provide " + ", ".join(refused))
        else:
            known = bool(ROOT and ROOT["musl_syms"])  # musl's own symbols were read from the image
            missing, preload = musl_resolve(imports, ROOT, names) if known else ([], [])
            if missing:  # Python imports with RTLD_NOW: a symbol the target does not define fails the import
                p.append("glibc build; the target's musl does not define %s%s (imported from %s): Python imports extension modules with RTLD_NOW, so the import fails with symbol not found" % (", ".join(missing[:4]), " and %d more" % (len(missing) - 4) if len(missing) > 4 else "", ", ".join(own)))
            elif not known:
                c.append(musl_check(own, image, [n for n in names if n not in own]))
            elif not syms_read:  # no symbol table read: nothing was resolved, which is not a pass
                c.append(musl_unread())
            elif preload:
                c.append(musl_preload(preload, ROOT))
            # with the image's files and every import defined by musl: OK, as on a glibc image
    if LIBC == "glibc" and ROOT and libc not in ("musl", "android"):
        p.extend(root_needs(vers, ROOT))  # the versions each library of the image defines
    if ROOT:  # a library the file needs from the image's own set that the image does not have (the loaders aside: the C library found names them)
        gone = [n for n in names if n in ROOT_LIBS and not n.startswith("ld-") and n not in ROOT["defs"] and not (LIBC == "musl" and GLIBC_LIBS.match(n))]
        if gone:
            p.append("needs %s, which the image does not have" % ", ".join(gone))
    if ROOT and libc in ("glibc", "musl") and not (LIBC == "musl" and libc == "glibc" and not ROOT["musl_syms"]) and (
            ROOT["libs"] or LIBC == "musl" and (ROOT["files"] or libc == "glibc")):  # judged once every scanned file is known
        e["lack"] = [n for n in names if n not in ROOT_LIBS and not GLIBC_LIBS.match(n) and not n.startswith("ld-")
                     and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF)) and n not in ROOT["libs"]
                     and n not in ROOT["files"] and not root_has(ROOT, [n])]
    if LIBC == "glibc" and VER and glibc and libc != "musl" and vkey(glibc) > vkey(VER):
        p.append("needs GLIBC_%s; the target has glibc %s" % (glibc, VER))
    if LIBC == "glibc" and VER and relr and libc != "musl" and vkey(VER) < (2, 36):
        p.append("needs GLIBC_ABI_DT_RELR (pack-relative relocations, glibc 2.36 or later); the target has glibc %s" % VER)
    if LIBC == "glibc" and CXX and cxx and vkey(cxx) > vkey(CXX):  # musl's loader checks no symbol versions
        p.append("needs GLIBCXX_%s; the target's libstdc++ provides up to GLIBCXX_%s" % (cxx, CXX))
    if PAGE and loads:
        # glibc 2.34 and earlier refuse a PT_LOAD whose p_align is not a multiple of the page size; glibc 2.35 and
        # later, and musl, need p_vaddr - p_offset to be one. Unknown glibc version: both rules.
        old = not (LIBC == "musl" or REL and vkey(REL) >= (2, 35))
        new = not (LIBC == "glibc" and REL and vkey(REL) < (2, 35))
        bad = [a for _, _, _, a in loads if a % PAGE]
        if old and bad:
            p.append("LOAD align %#x is not a multiple of the %d-byte page size" % (min(bad), PAGE))
        if new and any((v - o) % PAGE for v, o, _, _ in loads):
            p.append("LOAD vaddr-offset align %#x is not a multiple of the %d-byte page size" % (voff, PAGE))

def archive(name, box, data):  # static library: the object files it holds
    o, m, other = 8, collections.Counter(), collections.Counter()
    while o + 60 <= len(data):
        try:
            size = int(data[o + 48:o + 58].decode("ascii").strip() or "0")
        except ValueError:
            break
        tag = data[o:o + 16].rstrip()
        skip = int(tag[3:]) if tag.startswith(b"#1/") and tag[3:].isdigit() else 0  # BSD ar: the name comes first
        h = data[o + 60 + skip:o + 60 + skip + 20]
        if h[:4] == b"\x7fELF" and len(h) == 20:
            m[struct.unpack(">H" if h[5] == 2 else "<H", h[18:20])[0]] += 1
        elif h[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
            other["Mach-O"] += 1
        o += 60 + size + (size & 1)
    if not m:
        return add(name, box, "static archive with no ELF members%s: another system's format" % (
            " (%s objects)" % ", ".join(sorted(other)) if other else ""))
    e = add(name, box, "static archive, ELF objects by e_machine %s" % dict(sorted(m.items())))
    if 183 not in m:
        e["checks"].append("static library with no aarch64 code (%s); a native arm64 build that links it fails" % (
            ", ".join("e_machine %d (%s)" % (k, ARCH.get(k, "other")) for k in sorted(m))))

def digest(src):  # SHA-256 of a member's bytes or of a loose file, read in parts: copies of one file are one build
    if isinstance(src, bytes):
        return hashlib.sha256(src).hexdigest()
    s, pos = hashlib.sha256(), src.tell()
    src.seek(0)
    for b in iter(lambda: src.read(1 << 20), b""):
        s.update(b)
    src.seek(pos)
    return s.hexdigest()

def check(name, box, h, load):
    try:
        if h[:4] == b"\x7fELF":
            src, n = load(), len(entries)
            elf(name, box, reader(src))
            for e in entries[n:]:
                e["sha"] = digest(src)
        elif h[:8] == b"!<arch>\n":
            src = load()
            archive(name, box, src if isinstance(src, bytes) else reader(src)(0, os.fstat(src.fileno()).st_size))
        elif h[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce") or \
                h[:4] == b"\xca\xfe\xba\xbe" and len(h) >= 8 and struct.unpack(">I", h[4:8])[0] < 30:  # a universal binary; other formats share the magic
            add(name, box, "Mach-O (a macOS build; Linux does not load it)")
        elif h[:2] == b"MZ" and len(h) >= 64 and h[struct.unpack("<I", h[60:64])[0]:][:4] == b"PE\0\0":
            add(name, box, "PE (a Windows build; Linux does not load it)")
        elif h[:4] == b"PK\x03\x04":
            src = load()
            with zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes) else src) as z:
                for m in z.infolist():
                    if not m.filename.endswith("/"):
                        with z.open(m) as f:
                            mh = f.read(4096)
                        check(name + "!" + m.filename, name, mh, lambda m=m, z=z: z.read(m))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, struct.error, ValueError) as e:
        print("could not read: %s (%s)" % (name, e))

def library(name):  # the builds of one library share this name
    n = name.rsplit("!", 1)[-1].rsplit("/", 1)[-1].lower()
    ext = re.match(r"(.+?)\.(cpython-|pypy|abi3\.)", n)  # a Python extension module: the name before its suffix
    if ext and n.endswith(".so"):
        return ext.group(1)
    n = re.sub(r"\.so(\.[0-9]+)+$", ".so", n)
    n = re.sub(r"([-_.])linux(32|64)(?=[-_.]|$)", r"\1linux", n)
    n = re.sub(r"([-_.])linux(musl|gnu)(?=[-_.]|$)", r"\1linux", n)  # sharp-linuxmusl-arm64
    prev = None
    while prev != n:
        prev, n = n, NAME_PARTS.sub("", n)
    return n


OS_PARTS = re.compile(r"[-_.](linux|darwin|macos|osx|mac|win32|win64|windows|mingw|freebsd|openbsd|netbsd|dragonfly(bsd)?|"
                      r"sunos|solaris|aix|android|ios)(?=[-_.]|$)", re.I)


def group_key(path):
    """The builds of one library share this key: its name without architecture and C library parts (library),
    with its soname version, in a folder (and archive) whose segments are the same once the operating system,
    architecture and C library parts are removed (com/sun/jna/linux-aarch64 and com/sun/jna/win32-x86-64 both read
    com/sun/jna; runtimes/linux-arm64/native and runtimes/linux-musl-arm64/native both read runtimes/native). Files of
    other libraries with the same base name in other folders, and other soname versions, are judged on their own."""
    out = []
    for seg in re.split(r"[/!]", path.lower())[:-1]:
        s, prev = "-" + seg, None
        while prev != s:
            prev, s = s, OS_PARTS.sub("", NAME_PARTS.sub("", s))
        s = s.strip("-_.")
        if s:
            out.append(s)
    name = path.rsplit("!", 1)[-1].rsplit("/", 1)[-1].lower()
    m = re.search(r"\.so((\.[0-9]+)+)$", name)
    return "/".join(out), library(path) + (m.group(1) if m else "")

def x86_refused(x):  # what an x86-64 glibc build needs that musl's loader does not answer itself and the image lacks;
    # the image's glibc loader (gcompat) stands in for the x86-64 one, which the image's x86-64 variant would carry instead
    names = (["interpreter " + x.get("interp", "")] if "ld-linux" in x.get("interp", "") else []) + [
        n for n in x.get("needed", []) if GLIBC_LIBS.match(n) and not (n.startswith("lib") and n[3:].startswith(MUSL_SELF))]
    image = root_has(ROOT, [n for n in names if "ld-linux" not in n])
    return [n for n in names if n not in image and not ("ld-linux" in n and ROOT and ROOT["glibc_loader"])]

def baseline(e, g, problem):  # the same glibc, libstdc++ or musl-loader problem in the x86-64 build: not a Graviton change
    for x in g:
        same = e["arch"] == "aarch64" and x["arch"] == "x86-64" and x["libc"] == e["libc"]
        shared = root_shared([problem], x.get("vers", [])) if same else ""
        need = x86_refused(x) if same and problem.startswith("glibc build; musl") and not any(  # no x86-64 musl build
            y["libc"] == "musl" for y in g if y.get("arch") == "x86-64") else []
        if shared or need:
            return "; the x86-64 build %s needs %s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                x["name"], shared or ", ".join(need))
        syms = [n for n in x.get("imports", []) if n in musl_resolve(e.get("imports", []), ROOT)[0]] if (
            same and ROOT and ROOT.get("musl_syms") and problem.startswith("glibc build; the target's musl does not define") and not any(
                y["libc"] == "musl" for y in g if y.get("arch") == "x86-64")) else []
        if syms:  # the same missing symbol in the x86-64 build: the import fails on x86-64 hosts with this image too
            return "; the x86-64 build %s imports %s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                x["name"], ", ".join(syms[:4]))
    for key, prefix, tgt in (("glibc", "needs GLIBC_", VER), ("cxx", "needs GLIBCXX_", CXX)):
        if not (problem.startswith(prefix) and tgt and e["arch"] == "aarch64"):
            continue
        for x in g:
            if x["arch"] == "x86-64" and x["libc"] == e["libc"] and x[key] and vkey(x[key]) > vkey(tgt):
                return "; the x86-64 build %s needs %s%s too, so x86-64 hosts with this OS fail as well (not a Graviton change)" % (
                    x["name"], prefix[6:], x[key])
    return ""

tl = "target: " + LIBC + (" (assumed)" if ASSUMED else "") + (", with a glibc loader" if ROOT and ROOT["glibc_loader"] else "")
if LIBC == "glibc":
    tl += (" " + REL) if REL else (", glibc release not read" if ROOT else ", glibc version not given")
elif VER:
    tl += " " + VER
TCXX = CXX or (ROOT["glibcxx"] if ROOT else "")
tl += (", page size %d" % PAGE if PAGE else ", page size not given") + (", libstdc++ GLIBCXX_" + TCXX if TCXX and LIBC == "glibc" else "")
print(tl + root_read_from(ROOT))
missing = [p for p in sys.argv[1:] if not os.path.exists(p)]
for p in missing:
    print("no such file or directory:", p)
empty = []  # path arguments whose folder holds no files
for top in sys.argv[1:]:
    walk, seen = [(os.path.dirname(top), [], [os.path.basename(top)])] if os.path.isfile(top) else os.walk(top), 0
    for root, dirs, files in walk:
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "graviton-validation")
                   and not os.path.exists(os.path.join(root, d, "pyvenv.cfg"))
                   and not os.path.isdir(os.path.join(root, d, "conda-meta"))]
        for n in files:
            p = os.path.join(root, n)
            if os.path.isfile(p) and not os.path.islink(p):
                seen += 1
                with open(p, "rb") as f:
                    check(p, top, f.read(4096), lambda f=f: f)
    if os.path.isdir(top) and not seen:  # a copy or build that produced nothing is not a pass
        empty.append(top)

findings, checks, notes, groups = [], [], [], collections.OrderedDict()
checks += ["%s: holds no files: the copy or build that should have filled it produced none" % p for p in empty]
if ROOT and IGNORED:
    notes.append("%s set but not used: TARGET_ROOT gives the C library and its versions" % ", ".join(IGNORED))
notes.extend(libs_notes(ROOT))
SHIPPED = set(x for e in entries if e.get("arch") == "aarch64" and e.get("loadable") for x in (e["name"].rsplit("!", 1)[-1].rsplit("/", 1)[-1], e.get("soname")) if x)  # the aarch64 libraries the scanned files ship, by file name and by SONAME (a library loaded by path answers a later need for its SONAME)
for e in entries:
    left = [n for n in e.get("lack", []) if n not in SHIPPED]
    if left and not e["probs"]:  # another library it needs that the image does not have
        e["checks"].append(needs_other(left, ROOT))
for e in entries:
    if e["loadable"]:
        groups.setdefault((e["box"], group_key(e["name"])), []).append(e)
    else:
        if e["checks"]:
            checks.append("%s: %s" % (e["name"], "; ".join(e["checks"])))
for (box, key), g in groups.items():
    ok = [e for e in g if not e["probs"]]
    if ok:  # the build for the target (no CHECK and its C library first) is judged; the other builds get no flag
        pick = sorted(ok, key=lambda e: (bool(e["checks"]), e["libc"] not in (LIBC, "needs no C library")))[0]
        for e in g:
            e["replaced"] = e is not pick  # another build of the library is the one for the target
        if pick["checks"]:
            checks.append("%s: %s" % (pick["name"], "; ".join(pick["checks"])))
        builds = len(set(e.get("sha") or e["name"] for e in g))  # copies of one file are one build
        if builds > 1:
            notes.append("%s: %d Linux builds in %s; %s is the build for this target; confirm in Phase 3 that it is the "
                         "one loaded" % (library(pick["name"]), builds, "the scanned files" if box in sys.argv[1:] else box, pick["name"]))
        continue
    arm = [e for e in g if e["arch"] == "aarch64"]
    primary = ([e for e in arm if e["libc"] in (LIBC, "needs no C library")] or [e for e in arm if e["libc"] != "android"]
               or arm or [e for e in g if e["arch"] == "x86-64"][:1] or g[:1])
    for e in g:
        e["replaced"] = e not in primary
    for e in primary:  # the build the target would load carries the finding
        findings.append("%s: %s" % (e["name"], "; ".join(x + baseline(e, g, x) for x in e["probs"])))
        if e["checks"]:
            checks.append("%s: %s" % (e["name"], "; ".join(e["checks"])))
small = sorted(e["name"] for e in entries if e["small"] and not e.get("replaced"))
if small and not PAGE:
    notes.insert(0, "%d aarch64 file(s) aligned for 4 KB pages only (%s%s): a kernel with 64 KB pages refuses them; give "
                    "the page size if the target uses 64 KB pages" % (len(small), ", ".join(small[:5]),
                                                                       " and %d more" % (len(small) - 5) if len(small) > 5 else ""))
for e in sorted(entries, key=lambda x: x["name"]):
    print("%s: %s" % (e["name"], e["desc"]))
print("ELF files by e_machine:", dict(sorted(machines.items())))
for x in sorted(findings):
    print("FINDING " + x)
for x in sorted(checks):
    print("CHECK " + x)
for x in notes:
    print("NOTE " + x)
print("findings: %d, checks: %d" % (len(findings), len(checks)))
sys.exit(2 if missing else 1 if findings else 0)
EOF
}
GV_DIR=$(mktemp -d "${TMPDIR:-/tmp}/graviton.XXXXXX") || GV_DIR=$PWD/graviton-validation/raw   # a private folder (mode 700): no other user can plant a file in it
typeset -f native_scan > "$GV_DIR/native_scan.sh"; mkdir -p graviton-validation/raw && printf 'GV_SCAN=%s\n' "$GV_DIR/native_scan.sh" >> graviton-validation/raw/session.env   # later blocks, perhaps in a new shell, read the path here
for GV_TAG in $(cut -f1 graviton-validation/raw/target-roots.txt 2> /dev/null | sort -u | grep . || echo target); do   # one scan per target that §1.1 recorded; with none, one scan named target
GV_TDIR=$(awk -F '\t' -v t="$GV_TAG" '$1 == t {d = $2} END {print d}' graviton-validation/raw/target-roots.txt 2> /dev/null)   # its image's folder, or glibc=VERSION for a target with no image
case $GV_TDIR in "") native_scan .;; glibc=*) TARGET_ROOT= TARGET_LIBC=glibc TARGET_LIBC_VER=${GV_TDIR#glibc=} native_scan .;; *) TARGET_ROOT=$GV_TDIR native_scan .;; esac | tee "graviton-validation/raw/site-packages-so-scan-$GV_TAG.txt"
done
```

Executed on the fixture:

```
target: glibc 2.41, page size 4096
./vendor/_fixture_ext.cpython-311-x86_64-linux-gnu.so: e_machine 62 (x86-64), glibc, GLIBC_2.2.5, LOAD align 0x1000, vaddr-offset align 0x1000, needs libc.so.6
./vendor/libfastsum-x86_64.so: e_machine 62 (x86-64), glibc, GLIBC_2.2.5, LOAD align 0x1000, vaddr-offset align 0x1000, needs libc.so.6
ELF files by e_machine: {62: 2}
FINDING ./vendor/_fixture_ext.cpython-311-x86_64-linux-gnu.so: not aarch64, e_machine 62 (x86-64)
FINDING ./vendor/libfastsum-x86_64.so: not aarch64, e_machine 62 (x86-64)
findings: 2, checks: 0
```

On the fixed fixture, which ships an aarch64 build next to each x86-64 one:

```
target: glibc 2.41, page size 4096
./vendor/_fixture_ext.cpython-311-aarch64-linux-gnu.so: e_machine 183 (aarch64), needs no C library, LOAD align 0x10000
./vendor/_fixture_ext.cpython-311-x86_64-linux-gnu.so: e_machine 62 (x86-64), glibc, GLIBC_2.2.5, LOAD align 0x1000, vaddr-offset align 0x1000, needs libc.so.6
./vendor/libfastsum-aarch64.so: e_machine 183 (aarch64), needs no C library, LOAD align 0x10000
./vendor/libfastsum-x86_64.so: e_machine 62 (x86-64), glibc, GLIBC_2.2.5, LOAD align 0x1000, vaddr-offset align 0x1000, needs libc.so.6
ELF files by e_machine: {62: 2, 183: 2}
NOTE _fixture_ext: 2 Linux builds in the scanned files; ./vendor/_fixture_ext.cpython-311-aarch64-linux-gnu.so is the build for this target; confirm in Phase 3 that it is the one loaded
NOTE libfastsum.so: 2 Linux builds in the scanned files; ./vendor/libfastsum-aarch64.so is the build for this target; confirm in Phase 3 that it is the one loaded
findings: 0, checks: 0
```

Every `FINDING` line is a finding, and the scan exits with status 1 when it prints one. With the image's files, a glibc, libstdc++ or libgcc_s library the file needs that the image does not have is also a `FINDING`, and so is a glibc symbol it imports that nothing in a musl image provides. A file that needs another library the image does not have, one the scanned files do not ship, is also a `CHECK`: the image the project deploys may install it. A `CHECK` line is settled by the step it names, and is not a pass; a `NOTE` changes no verdict. The first line names the target, `glibc (assumed)` when neither `TARGET_ROOT` nor `TARGET_LIBC` is set. It judges one target per run: run it once with each target's values (for example an Alpine image and an arm64 Lambda function); each run writes `raw/site-packages-so-scan-<target>.txt`, named by `GV_TAG` (§1.1 sets it from the image; set it yourself for a target with no image).

- `not aarch64`: built for another architecture (e_machine 183 is aarch64, 62 is x86-64, 3 is 32-bit x86, 40 is 32-bit Arm).
- Several Linux builds of one library (files in one folder, or in folders named for each platform, whose names differ only by architecture or C library parts, such as `libfastsum-x86_64.so` and `libfastsum-aarch64.so`): the scan judges the target's build by content and names it in a `NOTE`; the other builds get no line, and a `FINDING` means no build suits. The code must load it on aarch64 (§1.4).
- `Android build`: the file needs a bare `libc.so` and carries Android's ELF note, so it was built against Android's C library (bionic), not glibc or musl.
- `musl build` or `glibc build; musl's loader does not provide`: built for the other C library than the target's. A glibc build that needs no glibc library musl's loader lacks is a `CHECK` judged without the image's files (with `TARGET_ROOT`, the scan resolves the file's glibc imports against the image's libraries, and a symbol the image does not define is a `FINDING`: Python imports extension modules with `RTLD_NOW`, so the import fails with `symbol not found`).
- `needs GLIBC_2.N`: newer than the target's glibc, which refuses to load it with `version 'GLIBC_2.N' not found`. Only versions needed from glibc's own libraries count.
- `needs GLIBCXX_3.4.N`: newer than the target image's libstdc++ (judged only for a glibc target, with `TARGET_ROOT` or `TARGET_GLIBCXX` set, below).
- When the x86-64 build needs the same version or library, the line says so: x86-64 hosts with this OS fail as well, so the OS or the package version is the change.
- `LOAD align` or `LOAD vaddr-offset align`: not linked for the target's page size (below). Without `TARGET_PAGE_SIZE`, one `NOTE` lists the aarch64 files linked for 4 KB pages only.
- `object file with no aarch64 code` or `static library with no aarch64 code`: a `CHECK`, because no loader reads them but an arm64 build that links them fails.
- With `TARGET_ROOT`, the target line ends with `read from <folder> (<os-release name>)`, and a version finding names the library: `needs GLIBC_2.35 from libm.so.6; the target's libm.so.6 defines up to GLIBC_2.32`. On a musl image with gcompat, a symbol that only gcompat's library defines is a `CHECK`: musl's loader gives it to the file only when that library is preloaded (`LD_PRELOAD`).

Wheels from the index get the C library and glibc checks through their tags in §1.3. The scan's checks matter most for files committed to the repository, which no tag describes. The `needs` list names the libraries the loader must find on the target: each must come from the target image or travel with the file, and a load that cannot find one fails (executed on arm64 with NumPy 1.26.4's `numpy.libs` folder removed: `OSError: libopenblas64_p-r0-17488984.3.23.dev.so: cannot open shared object file: No such file or directory` from `ctypes.CDLL`). A CPython extension's filename states the target it was built for (`*.cpython-311-x86_64-linux-gnu.so` for x86_64 Python 3.11, `*.cpython-311-aarch64-linux-gnu.so` for Graviton); the scan confirms that the content matches.

Lambda layers and vendored `site-packages` also carry package metadata. The scan above already checked their binaries; find them so their pins also get the wheel check of §1.3:

```bash
# Lambda layers and vendored site-packages (python/ at the zip root, *.dist-info directories)
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -type d -name 'python' -o -name '*.dist-info' -o -name '*.egg-info' -o -name 'layer*.zip' \) -print
```

For a Lambda layer or vendored directory, list `*.dist-info` to get `name==version` pins and feed them to §1.3; Lambda extensions need the same check.

For a target with 64KB pages (§1.1), an aarch64 file must also be linked for that page size, and which value the loader checks depends on the target's C library: glibc 2.34 and earlier refuse a `PT_LOAD` segment whose `p_align` is not a multiple of the page size (`ELF load command alignment not page-aligned`). glibc 2.35 and later instead refuse one whose `p_vaddr - p_offset` is not a multiple of it (`ELF load command address/offset not page-aligned`). musl's loader checks neither value: it maps each segment from its file offset rounded down to the page size at its address rounded down to the page size ([`ldso/dynlink.c`](https://git.musl-libc.org/cgit/musl/tree/ldso/dynlink.c)), which places the segment correctly only when the two differ by a multiple of the page size, so for musl the scan applies the second rule. The scan prints each aarch64 file's smallest `LOAD align`, and its `vaddr-offset align` (the largest power of two dividing every segment's `p_vaddr - p_offset`) when that is below `0x10000`. With `TARGET_PAGE_SIZE` set, it applies the rule of the target's C library and version, and both rules when the version is not set.

With `TARGET_ROOT`, the scan judges each file's `GLIBCXX_` needs against the image's own libstdc++, whose highest version the §1.1 block prints (`GLIBCXX_3.4.33` for `python:3.11-slim`). Without an image folder, the scan judges them only when `TARGET_GLIBCXX` is set to the highest version the target's libstdc++ provides. An image with no `libstdc++.so.6` (`python:3.11-alpine`) has to install it for a file whose `needs` list names it.

Then find extensions the project builds and their sources:

```bash
grep -rnE --exclude-dir=.venv --exclude-dir=.git \
  --include=setup.py --include=setup.cfg --include=pyproject.toml --include=CMakeLists.txt --include=meson.build --include=Cargo.toml \
  "ext_modules|Extension\(|cythonize|cffi_modules|pybind11|setuptools-rust|setuptools_rust|maturin|scikit-build|scikit_build|meson-python|mesonpy|cmake" .
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -name '*.pyx' -o -name '*.pxd' -o -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.rs' -o -name 'Cargo.toml' \) -type f -print
```

An extension built from source is not a blocker by itself (it will be compiled on aarch64 in Phase 3); its **flags and headers** are checked in §1.4.

### 1.2.2 Runtime-Extracted Native Library Detection

Some packages and scripts download or unpack native binaries at run, build or deploy time instead of shipping them in a wheel, and packages from the OS arrive outside pip. None of them shows up in the dependency tree.

```bash
# Every download in scripts, Dockerfiles and CI. A URL that names no architecture still fetches a build
# for one, so each downloaded file is judged by its content (the next block)
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.sh' --include='Dockerfile*' --include='*.[Dd]ockerfile' \
  --include='Containerfile*' --include='Makefile' --include='*.py' --include='*.y*ml' --include='Jenkinsfile*' \
  '(curl|wget|Invoke-WebRequest|iwr|Start-BitsTransfer)[[:space:]]|^[[:space:]]*ADD([[:space:]]+--[^[:space:]]+)*[[:space:]]+https?:|releases/(latest/)?download/' .

# Packages installed from the OS by Dockerfiles and scripts
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='Dockerfile*' --include='*.sh' \
  '(apt-get|apt|dnf|yum|microdnf) install|apk add' .
```

Fetch each download into a scratch folder and scan what it holds, whatever its URL says. Resolve the script's variables in the URL first; `native_scan` opens zip archives itself, and a tar archive is unpacked first:

```bash
GV_SCAN=$(sed -n 's/^GV_SCAN=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the function's file, recorded by §1.2.1
if [ -f "$GV_SCAN" ] && . "$GV_SCAN"; then
  TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41; TARGET_PAGE_SIZE=4096   # the §1.1 values, as in §1.2.1
  URL='https://github.com/jqlang/jq/releases/download/jq-1.6/jq-linux64'   # one download from the list above
  d=$(mktemp -d "${TMPDIR:-/tmp}/graviton-download.XXXXXX") && mkdir "$d/x" || { d=; echo "ERROR: mktemp -d made no folder under ${TMPDIR:-/tmp}; set TMPDIR to a writable folder and rerun"; }
  if [ -n "$d" ] && curl -fsSL --max-time 300 -o "$d/download" "$URL"; then
    # Unpack by the first bytes, not the name: a .deb (an ar archive), an .rpm, a zip or a tar archive; native_scan opens a zip itself
    case "$(od -An -tx1 -N4 "$d/download" | tr -d ' \t\n')" in
      213c6172) if head -c 64 "$d/download" | grep -q debian-binary; then   # another ar archive is a static library, which the scan reads
                  (cd "$d/x" && ar x ../download && for t in data.tar.*; do tar -xf "$t"; done) && rm "$d/download" \
                    || echo "CHECK: $URL is a .deb this host cannot unpack (needs ar, and tar with xz or zstd)"
                fi ;;
      edabeedb) { if command -v bsdtar > /dev/null 2>&1; then bsdtar -xf "$d/download" -C "$d/x"   # bsdtar keeps every path inside the folder
                  else (cd "$d/x" && rpm2cpio ../download | cpio -idm --quiet --no-absolute-filenames); fi; } && rm "$d/download" \
                  || echo "CHECK: $URL is an .rpm this host cannot unpack (needs bsdtar, or rpm2cpio and GNU cpio)" ;;
      *) tar -xf "$d/download" -C "$d/x" 2>/dev/null ;;
    esac
    native_scan "$d"
  else echo "CHECK: $URL did not download"; fi
  [ -z "$d" ] || rm -rf "$d"
else echo "CHECK: run the Phase 1.2.1 scan block first: it records the function's file in graviton-validation/raw/session.env"; fi
```

Executed: jq 1.6's `jq-linux64`, whose URL names no architecture, gave `FINDING ...: not aarch64, e_machine 62 (x86-64)`; jq 1.7.1's `jq-linux-arm64` gave no finding. A download that cannot be fetched from here (credentials, a private network) stays CHECK until it is scanned where it can be.

**Common packages that fetch or carry native binaries outside their wheel tags** (this list is a *prompt*, not an allowlist):
- **selenium**: its `py3-none-any` wheel carries Selenium Manager executables. Up to 4.48.0 the only Linux build is an x86-64 executable (`selenium/webdriver/common/linux/selenium-manager`); 4.49.0 is the first release that also carries `linux-arm64/selenium-manager`. On Linux aarch64, 4.48.0 stops before it starts any program, with `WebDriverException: Message: Unsupported platform/architecture combination: linux/aarch64` (its `selenium_manager.py` maps Linux to a binary only for `x86_64`); the bundled file itself, run directly on Graviton, fails with `Exec format error`. 4.49.0 and 4.50.0 run the arm64 one
- **pyppeteer**: downloads Chromium on first use from the `Linux_x64` snapshot path on every Linux host (2.0.0), so on Graviton it fetches an x86 browser (executed: `pyppeteer-install` downloaded an x86-64 `chrome` that fails with `Exec format error`)
- **Browser and driver downloaders** (Selenium Manager, webdriver-manager): fetch Chrome for Testing builds at run time. The current Stable release lists `linux-arm64` for Chrome and ChromeDriver (154.0.8037.92), and on Graviton webdriver-manager 4.1.2 downloaded the `linux-arm64` ChromeDriver for that release; check the platform list for the version the project uses
- **duckdb**: downloads extensions for its platform at first use; `linux_arm64` builds are published (on Graviton, duckdb 1.5.6 installed and loaded the `linux_arm64` `httpfs` extension)

**Do not rely on the named list alone.** The authoritative signal is the ELF scan of the installed environment (Phase 3.1), which opens every file and so also reports executables inside `py3-none-any` wheels. Binaries a package downloads to a directory outside `site-packages` need the downloading code read instead.


For each OS package, check that the target's arm64 repository has it. From an x86 host this needs no emulation:

```bash
# Debian or Ubuntu target: read the arm64 package index from the target image, run for this host's own
# platform (no emulation). Enable the repositories the Dockerfile enables (non-free for MKL here).
IMG=python:3.11-slim   # the runtime image (§1.1)
case "$(uname -m)" in x86_64|amd64) NATIVE=linux/amd64 ;; *) NATIVE=linux/arm64 ;; esac
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
# timeout 300 bounds each index download; raise it on a slow network
$CONTAINER_CMD run --rm --init --platform "$NATIVE" --entrypoint timeout "$IMG" 300 sh -c "$PORTS"'
   [ -f /etc/apt/sources.list.d/debian.sources ] && sed -i "s/^Components: main$/Components: main non-free/" /etc/apt/sources.list.d/debian.sources
   dpkg --add-architecture arm64 && apt-get update -qq >/dev/null &&
   for p in libgeos-dev libmkl-dev; do echo "$p arm64: $(apt-cache policy "$p:arm64" | sed -n "s/^ *Candidate: //p")"; done'
# Amazon Linux 2023 (and other dnf distributions): query the aarch64 repository, for this host's own platform
# (timeout 300, as above).
$CONTAINER_CMD run --rm --init --platform "$NATIVE" amazonlinux:2023 timeout 300 sh -c \
  'dnf -q --forcearch=aarch64 repoquery --available --latest-limit 1 --qf "%{name}-%{version}-%{release}.%{arch}" geos-devel python3.11 2>/dev/null; echo "repoquery exit status $? (0: a package with no line has no aarch64 build; another status: the query failed, which is no answer)"'
```

A package with no arm64 candidate is a MUST UPGRADE finding, and its substitute is a user decision (as for `mkl` in [agent-scope-boundaries.md](agent-scope-boundaries.md)).

### 1.2.3 Tiered Validation Policy

**FAIL immediately if:**
- the §1.2.1 scan prints a `FINDING` for the file (so no build of its library beside it suits the target) AND no source in the repository AND the user cannot provide such a build

**WARN but proceed if:**
- Source is present (the extension or library can be rebuilt on aarch64 in Phase 2.1), OR a pure-Python fallback path exists (for example `fast_sum` falling back to `sum()` when the load fails), OR the binary is an optional accelerator

**PASS if:**
- the scan prints no `FINDING` or `CHECK` for the file, and when a `NOTE` names another build of its library for this target, Phase 3 shows the code loads that build. A `CHECK` is not a PASS: an assessment reports it as `CHECK` with the step that settles it

For x86-only binaries: locate the source, document the rebuild, or ask the user for an aarch64 build. Validate with:
```bash
GV_SCAN=$(sed -n 's/^GV_SCAN=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the function's file, recorded by §1.2.1
if [ -f "$GV_SCAN" ] && . "$GV_SCAN"; then
  TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41; TARGET_PAGE_SIZE=4096   # the §1.1 values, as in §1.2.1
  native_scan libname.so   # no FINDING line
else echo "CHECK: run the Phase 1.2.1 scan block first: it records the function's file in graviton-validation/raw/session.env"; fi
```

## 1.3 Dependency ARM64 Compatibility Analysis

> **Output: `graviton-validation/03-dependency-compatibility-report.md`** and **`graviton-validation/raw/wheel-availability.txt`**

**IMPORTANT:** ARM64-incompatible native code is introduced through transitive dependencies as often as direct ones. The fixture's `requirements.txt` names `mkl`; the resolved tree adds six Intel-only transitives. Probe the full flat list from §1.1, never just the manifest.

### Generate Filtered Tree

The Python equivalent of a "native-artifact-only tree" is the probe output: one verdict per pin, for the project's interpreter, against the aarch64 platform tags. The probe and its exact flags are defined and demonstrated in [wheel-verification.md](wheel-verification.md) §3; this is the loop over the resolved list:

```bash
PYVER=3.11; ABI="cp${PYVER/./}"
TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41   # from the target probe in §1.1 (Alpine: TARGET_LIBC=musl TARGET_LIBC_VER=1.2; no target named: both empty)
platforms() { # $1=arch ; sets PLAT to one --platform flag per wheel tag the target's libc accepts, newest first
  local i="${TARGET_LIBC_VER#*.}"; PLAT=()
  case "$i" in ''|*[!0-9]*) i=99;; esac   # no version given: every tag; the wheel's tag names the version it needs
  if [ "$TARGET_LIBC" = musl ]; then
    while [ "$i" -ge 1 ]; do PLAT+=(--platform "musllinux_1_${i}_$1"); i=$((i - 1)); done
  else
    while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_$1"); i=$((i - 1)); done
    PLAT+=(--platform "manylinux2014_$1")
  fi
}
GV_DIR=$(mktemp -d "${TMPDIR:-/tmp}/graviton.XXXXXX") || GV_DIR=$PWD/graviton-validation/raw   # a private folder (mode 700): no other user can plant a file in it
typeset -f platforms > "$GV_DIR/platforms.sh"; mkdir -p graviton-validation/raw && printf 'GV_PLATFORMS=%s\n' "$GV_DIR/platforms.sh" >> graviton-validation/raw/session.env   # later blocks, perhaps in a new shell, read the path here
probe() { # $1=requirement $2=arch ; prints the wheel filename (rc 0), the from-versions list (rc 1),
          # nothing (rc 3) when an environment marker excluded the pin on this host, or why the indexes
          # give no verdict (rc 4). --no-input and </dev/null: pip never reads the loop's list of pins;
          # --disable-pip-version-check: the only index requests in the log are the probe's.
  local d f miss; platforms "$2"; d=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
  if python3 -m pip download --no-input --disable-pip-version-check --only-binary=:all: --no-deps -vv -d "$d" "${PLAT[@]}" \
       --python-version "$PYVER" --implementation cp --abi "$ABI" "$1" </dev/null >"$d/log" 2>&1; then
    f=$(ls "$d" | grep '\.whl$' | head -n 1); rm -rf "$d"
    [ -n "$f" ] && { echo "$f"; return 0; }; return 3
  fi
  # pip skips an index whose request fails ("Could not fetch URL") and decides from the others. A 403 or 404
  # means that index does not have the project: keep the verdict and name the index. Any other failure (401,
  # a server error, no connection, TLS) leaves an index that may have the wheel unread: no verdict.
  miss=$(sed -nE 's/^.*Could not fetch URL ([^ ]+): (40[34]) Client Error.*$/\1 (\2)/p' "$d/log" | awk 'NR > 1 {printf ", "} {printf "%s", $0}')
  if grep 'Could not fetch URL' "$d/log" | grep -qvE ': 40[34] Client Error'; then
    echo "an index did not answer: $(grep 'Could not fetch URL' "$d/log" | grep -vE ': 40[34] Client Error' | head -n 1 | sed -E 's/^.*Could not fetch URL ([^ ]+): (.*) - skipping$/\2 (\1)/' | cut -c1-160)"
    rm -rf "$d"; return 4
  elif ! grep -q 'Fetched page' "$d/log"; then
    echo "no index has the project: ${miss:-no index was searched}"; rm -rf "$d"; return 4
  fi
  echo "$(grep -oE 'from versions: [^)]*' "$d/log" | head -n 1)${miss:+; not on $miss}"; rm -rf "$d"; return 1
}
sed -E 's/[[:space:]]*#.*//' graviton-validation/raw/requirements-resolved.txt | grep '==' | while read -r req; do
  out=$(probe "$req" aarch64); rc=$?
  if [ $rc -eq 4 ]; then echo "CHECK INDEX     $req  $out"; continue; fi
  if [ $rc -eq 0 ]; then
    case "$out" in
      *-none-any.whl)   # pure on aarch64: x86_64 may still get compiled code for the same pin
        x86=$(probe "$req" x86_64); xrc=$?
        case "$xrc:$x86" in
          0:*-none-any.whl|[123]:*) echo "COMPATIBLE      $req  pure Python: $out";;
          4:*) echo "CHECK INDEX     $req  $x86";;
          *) echo "CHECK FALLBACK  $req  aarch64 gets only the pure-Python wheel $out; x86_64 gets compiled code: $x86";;
        esac;;
      *) echo "COMPATIBLE      $req  aarch64 wheel: $out";;
    esac
  elif [ $rc -eq 3 ]; then
    echo "CHECK MARKER    $req  skipped: its environment marker does not match this host; judge it for Linux aarch64 by hand"
  else
    x86=$(probe "$req" x86_64); xrc=$?
    if [ $xrc -eq 0 ]; then
      echo "MUST UPGRADE    $req  x86_64 wheel exists for $ABI, no aarch64 wheel; $out"
    elif [ $xrc -eq 4 ]; then
      echo "CHECK INDEX     $req  $x86"
    else
      note=; case "$out" in *'; not on '*) note="; not on ${out#*; not on }";; esac
      echo "CHECK SDIST/ABI $req  no $ABI wheel for either arch: pure-Python sdist, interpreter ABI mismatch, or a libc older than every wheel (wheel-verification.md sections 5 to 7)$note"
    fi
  fi
done | tee graviton-validation/raw/wheel-availability.txt
```

Set `TARGET_LIBC` and `TARGET_LIBC_VER` from §1.1. `platforms` then offers pip every wheel tag the target's libc accepts, newest first as pip itself prefers them, and nothing above it. pip matches each `--platform` value exactly, so a shorter list misses wheels: executed, `polars==1.0.0`, whose only aarch64 wheel is `manylinux_2_24`, came out `MUST UPGRADE` when only `manylinux2014`, `_2_17`, `_2_28` and `_2_34` were offered, and `COMPATIBLE` with the full list. With `TARGET_LIBC=musl` the loop probes `musllinux` wheels for Alpine targets. A pin whose wheels all need a newer libc than the target's is a MUST UPGRADE finding with the OS or Lambda runtime as the user decision: rerun its aarch64 probe with a higher `TARGET_LIBC_VER` to show that (wheel-verification.md §7).

Run the loop in the same shell as §1.1, so `python3` is the project-version environment. pip evaluates environment markers (`; python_version < "3.12"`, `; platform_machine == "x86_64"`, `; sys_platform == "win32"`) against the interpreter and machine that run it, not against `--python-version` or `--platform`: executed with a Python 3.12 host and `--python-version 3.11`, a pin marked `python_version < "3.12"` was skipped and one marked `python_version >= "3.12"` was downloaded. With the project's interpreter the `python_version` markers resolve correctly; markers on the machine or platform still follow the analysis host, so a `CHECK MARKER` line, or a `MUST UPGRADE` line whose marker names `platform_machine`, needs a manual call for Linux aarch64. Exports from Poetry and uv carry such markers; requirement files from pip usually do not.

> **Skill config:** when `python.index_url` is set, run the loop twice, with `PIP_INDEX_URL` set to the configured index and then to `https://pypi.org/simple` (the loop has no index option; pip reads the variable). A pin that fails only on the configured index is COMPATIBLE with an **INFRA** note ("mirror lacks the aarch64 wheel"), not a dependency change (wheel-verification.md §9).

Then the hash-lock check for every hashed requirements file the deployment installs:

```bash
GV_PLATFORMS=$(sed -n 's/^GV_PLATFORMS=//p' graviton-validation/raw/session.env 2> /dev/null | tail -n 1)   # the function's file, recorded by the probe block
if [ -f "$GV_PLATFORMS" ] && . "$GV_PLATFORMS"; then
  PYVER=3.11; ABI="cp${PYVER/./}"; TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41   # the values of the probe block
  platforms aarch64   # the same tag list as the loop above
  python3 -m pip install --dry-run --ignore-installed --only-binary=:all: --require-hashes -q "${PLAT[@]}" \
    --python-version "$PYVER" --implementation cp --abi "$ABI" --target /tmp/graviton-probe-target \
    -r requirements-locked.txt
else echo "CHECK: run the probe block above first: it records the function's file in graviton-validation/raw/session.env"; fi
```

With hashes for the x86 wheels only, the dry run stops at `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`. The error is about the lock's hashes only, and the probe loop judges each pin: here both pins have aarch64 wheels, so the **lock file** is the MUST UPGRADE finding, and a pin without one (such as `pygeos==0.14`) stays a finding of its own. `poetry.lock`, `uv.lock`, `pdm.lock`, `Pipfile.lock` and pip-tools output with `--generate-hashes` carry hashes for every published file and pass this check without changes (package-manager-mapping.md §1).

### Classify Each Dependency

Apply the decision tree in [agent-scope-boundaries.md](agent-scope-boundaries.md) to every line of `raw/wheel-availability.txt`:

**MUST UPGRADE (Blocking):** no aarch64 wheel for the pinned version and interpreter where a later version has one (upgrade to the **lowest** such version); no aarch64 wheel in any release and the package is x86-only by nature (substitute, user confirms); hash lock excludes the aarch64 wheel (regenerate); wheel tag exceeds the target glibc (user decision); documented aarch64 correctness bug at this version (NumPy < 1.21.1, SciPy < 1.7.2, whose OpenBLAS lacks aarch64 correctness fixes).

**RECOMMENDED UPGRADE (Non-blocking):** installs and runs on aarch64, and a newer version has a documented Graviton improvement; record it with its source and evidence level and never apply it. Runtime settings go to `05-runtime-configuration.md` (Phase 2.5).

**COMPATIBLE (No action):** aarch64 wheel present, or a `none-any` wheel that x86_64 gets too, or pure-Python sdist. Age, CVEs and "newer is faster" do not move a package out of this class.

**CHECK SDIST/ABI lines need one more step before they get a label:** download the sdist and list compiled sources (wheel-verification.md §5); if there are none it is COMPATIBLE. If the package has aarch64 wheels for a *different* `cp` tag (probe again with `--python-version 3.10 --abi cp310`, and x86_64 with the project's tag), it is an interpreter-ABI blocker, reported in its own table and resolved only through the gate in §1.5.

**CHECK FALLBACK lines run on aarch64, but not the code x86 runs:** aarch64 gets the pure-Python wheel and x86_64 a compiled one for the same pin. Executed for `pydantic==1.10.26`: on x86_64 pip installed a Cython-compiled wheel (`pydantic.compiled` is `True`, 23 native files loaded) and on Graviton2 to Graviton5 the `none-any` wheel (`False`); no pydantic 1.x release has an aarch64 wheel. List the releases with an aarch64 wheel for the project's tag (wheel-verification.md §4) and record the pin under User Decisions Pending. The Recommendation is the lowest such release in the same major version. When there is none, the options are the pure-Python path as it is (the default in unattended runs: nothing changes), a compiled wheel built on aarch64 from the sdist, or the next major version (pydantic 2.x moves its compiled code to `pydantic-core`, which has aarch64 wheels). A plain build from the sdist can be pure again: pydantic 1.x compiles only with its own build option, and on Graviton `pip wheel --no-binary pydantic --config-settings=--build-option=--cythonize --build-constraint build-constraints.txt pydantic==1.10.26`, with `Cython==3.0.12` in the constraints file (`--build-constraint` needs pip 25.3 or later, `python3 -m pip install 'pip>=25.3'`, and the build needs a C compiler), built `pydantic-1.10.26-cp311-cp311-linux_aarch64.whl` (`pydantic.compiled` is `True`); without the option it built the `none-any` wheel, and with Cython 3.3.0 the build stopped inside Cython. The Phase 3 loaded check shows which code runs.

**CHECK INDEX lines are not verdicts:** an index that may have the wheel did not answer (credentials, network, a server error), or no configured index has the project. Fix access or the index settings, or probe PyPI as in the skill-config note above, and rerun the loop for those pins; never label a pin from a failed request. An index that answers 403 or 404 for a project page does not have that project, and pip uses the other indexes: the loop keeps their verdict and appends `not on <url> (403)`. A private index can also answer 403 or 404 when the probe may not read it; when a note names one that should carry the package, check access to it (wheel-verification.md §9).

**A pin the decision tree sends to a user decision stays CHECK until the user chooses** (pygeos in [agent-scope-boundaries.md](agent-scope-boundaries.md): a source build is COMPATIBLE, a move to `shapely>=2.0` is MUST UPGRADE). The loop's line for it records only the probe result; the report lists it under User Decisions Pending.

For transitive dependencies: record which direct dependency pulls each one in (the `# transitive via` provenance plus the manager's tree). Resolution usually happens at the parent (`mkl` removal removes all six Intel transitives).

### Document Findings

```
Dependency: blosc2 (direct, requirements.txt)
Pinned: 0.6.3
Status: MUST UPGRADE
Reason: no Linux aarch64 wheel for cp311; x86_64 wheel exists (blosc2-0.6.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl)
Evidence: pip download --only-binary=:all: --platform manylinux_2_17_aarch64 ... blosc2==0.6.3 -> "from versions: 0.6.4, 0.6.5, 0.6.6, 2.0.0, ..."
Minimum aarch64 version for cp311: 0.6.4 (blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl)
Resolution: pin blosc2==0.6.4 in requirements.txt (lowest version restoring the wheel, not latest)
```

> ⚠️ **Verify the wheel, never the version number.** Do not infer "old version, so no aarch64 wheel" or "new version, so it must have one": numpy 1.19.0 has aarch64 wheels, pygeos 0.14 has none, blosc2 lost and regained them between 0.3.0 and 0.6.4. Confirm by probing the exact pin for the project's interpreter and quote the filename or the `from versions:` list. And make a missing artefact fail loudly: a typo in a version number produces the same `(from versions: none)` as a real gap, so check the version exists on PyPI (`curl --fail https://pypi.org/pypi/<name>/<version>/json`) before recording the verdict.

### Build-Time Binaries Outside the Dependency Tree

Some binaries the build or deployment needs are fetched by scripts rather than resolved as packages, so none of the steps above sees them: a `curl` of a `tool-linux-amd64` release asset in a deploy script, a Dockerfile `ADD` of an x86 tarball, `npm`/`node` installed by a build hook, or a Dockerfile that installs a compiler and compiles a dependency with `--no-binary`. These were collected by the §1.2.2 download grep; for each one, check that the vendor publishes an `arm64`/`aarch64` asset (open the release page or run `curl --fail -I` on the aarch64 URL) and record it in `04-code-scan-findings.md`. If no aarch64 asset exists, it is a MUST UPGRADE finding and a user decision, like an x86-only package.

## 1.4 Architecture-Specific Code Detection

> **Output: `graviton-validation/04-code-scan-findings.md`**

Scan from the project root (`.`), not a hard-coded `src/` or `app/`, and exclude the virtualenv (its site-packages contain thousands of legitimate `x86_64` strings inside wheels).

```bash
# Native library loads (ctypes, cffi), with file:line
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.py' \
  "ctypes\.CDLL|cdll\.LoadLibrary|ctypes\.util\.find_library|CDLL\(|ffi\.dlopen|dlopen\(|LoadLibrary\(" .

# Architecture checks in Python, with file:line
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.py' \
  "platform\.(machine|processor|architecture|uname)\(|os\.uname\(|[\"'](x86_64|amd64|AMD64|i386|i686)[\"']" .

# The risky shape: files that COMPARE against x86 but never mention aarch64/arm64 (heuristic; read the hits above)
grep -rlE --exclude-dir=.venv --exclude-dir=.git --include='*.py' "[\"'](x86_64|amd64|AMD64)[\"']" . \
  | while IFS= read -r f; do grep -qE "[\"'](aarch64|arm64)[\"']" "$f" || printf '%s\n' "$f"; done

# Shell scripts, Makefiles, CI
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.sh' --include=Makefile --include='*.mk' --include='*.y*ml' \
  'uname -m|HOSTTYPE|x86_64|amd64' .

# x86-only compiler flags, intrinsics headers and macros in build files and extension sources
grep -rnE --exclude-dir=.venv --exclude-dir=.git \
  --include=setup.py --include=setup.cfg --include=pyproject.toml --include=CMakeLists.txt --include=meson.build \
  --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' --include='*.pyx' \
  --include='*.rs' --include=Cargo.toml -- '-m(avx|sse|fma|bmi|popcnt|pclmul|aes|crc32|f16c|lzcnt)|-march=|-mtune=|[a-z0-9]+intrin\.h|cpuid\.h|__builtin_ia32_|__cpuid|__rdtsc|__x86_64__|_M_X64|__SSE|__AVX|__m(128|256|512)|_mm[0-9]*_' .

# System calls made by number: the numbers differ (x86-64's 186 is gettid, aarch64's is 178, and 186 there
# is msgget), and open, fork, pipe, dup2 and poll have no aarch64 number at all (openat, clone, pipe2, dup3
# and ppoll do). Use the libc function or the target's SYS_ constant instead of the number.
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.py' --include='*.pyx' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' -- \
  'syscall\([[:space:]]*(0x[0-9a-fA-F]+|[0-9]+)' . 2>/dev/null || true
# Dockerfiles under any name, and deployment descriptors
if [ -f graviton-validation/raw/dockerfiles.txt ]; then
  while IFS= read -r f; do grep -nE -- '--platform=|@sha256:|BUILDPLATFORM|TARGETPLATFORM|TARGETARCH|x86_64|amd64|pip install|uv (sync|pip)|poetry install|conda env' "$f" | grep -vE '^[0-9]+:[[:space:]]*#' | sed "s#^#$f:#"; done < graviton-validation/raw/dockerfiles.txt
else echo "CHECK: run the Determine Deployment Type block (§1.1) first: it writes graviton-validation/raw/dockerfiles.txt"; fi
grep -rniE --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=cdk.out --include='*.y*ml' --include='*.json' --include='*.tf' \
  'architectures?"?[[:space:]]*[:=]|kubernetes\.io/arch|nodeselector|cpu_?architecture"?[[:space:]]*[:=]|ami_?type"?[[:space:]]*[:=]|instance_?types?"?[[:space:]]*[:=]|ami-[0-9a-f]{8,17}|^functions:|AWS::(Lambda::Function|Serverless::Function|ECS::TaskDefinition|EKS::Nodegroup)|requires_?compatibilities|resource "aws_(lambda_function|ecs_task_definition|eks_node_group)"|x86_64|amd64' .
# CDK apps: the constructs that take an architecture, and the settings, in each folder with a cdk.json
# (a construct that sets none gets x86_64)
find . \( -path ./.venv -o -path ./.git -o -name node_modules -o -name cdk.out \) -prune -o -name cdk.json -print |
  while IFS= read -r c; do grep -rnE --exclude-dir=node_modules --exclude-dir=cdk.out --exclude-dir=.venv --include='*.py' --include='*.ts' --include='*.js' \
    --include='*.java' --include='*.cs' --include='*.go' 'Architecture[._](X86_64|ARM_64)|CpuArchitecture[._](X86_64|ARM64)|AmazonLinuxCpuType[._]|MachineImage[._]|NodegroupAmiType[._]|InstanceType(\(|[._][Oo]f\()|InstanceClass[._]|(^|[^A-Za-z0-9_])(New)?(Function|DockerImageFunction|NodejsFunction|PythonFunction|GoFunction|FargateTaskDefinition|Nodegroup|Cluster)(\(|\.Builder)|[Aa]dd_?[Nn]odegroup_?[Cc]apacity' "$(dirname "$c")"; done | sort -u
# Wheels the project builds itself: cibuildwheel builds only the runner's architecture unless archs adds one
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.toml' --include='*.y*ml' 'cibuildwheel|CIBW_ARCHS|^[[:space:]]*archs[[:space:]]*=' .
# Types and build flags whose results differ by architecture (checked in Phase 3)
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.py' --include='*.pyx' --include='*.c' --include='*.cc' --include='*.cpp' --include='*.cxx' --include='*.h' --include='*.hpp' \
  --include=CMakeLists.txt --include=Makefile --include='*.mk' \
  --include=setup.cfg --include=pyproject.toml --include=meson.build -- 'long double|__float128|longdouble|float128|float96|complex256|-ffast-math|-Ofast|-funsafe-math' .
```

The descriptor pattern is case-insensitive and allows an optional quote and `:` or `=`, so it catches CloudFormation JSON (`"Architectures": ["x86_64"]`) and YAML, ECS task definitions (`"cpuArchitecture": "X86_64"`) and Terraform (`architectures = ["x86_64"]`, `cpu_architecture`, `ami_type`, `instance_type`). Note the `--` before the pattern in the flags and Dockerfile greps: those patterns start with `-`, and without `--` grep reads them as options (`grep: unrecognized option '--platform=...'`). Keep the `--include` flags **before** the `--`, or grep treats them as file names.

A setting that is absent also picks an architecture. A Lambda function that names none runs on x86_64, the default of the Lambda API, Terraform and the CDK, whose templates then carry no `Architectures`; a Fargate task definition without `cpuArchitecture` runs `X86_64`, and an ECS task on EC2 capacity without it goes where its capacity providers place it; an EKS managed node group with no instance type launches `t3.medium`, and the CDK's `aws-eks` `Cluster` without `defaultCapacityInstance` adds `m5.large` (x86) nodes, two unless `defaultCapacity` sets another count; the CDK's `MachineImage.latestAmazonLinux2023()` without `cpuType` picks the x86_64 AMI. So each function, task definition and node group the resource lines list needs an arm64 setting (Phase 2.4), whether or not an architecture line matched it. An image can also name one architecture: through its tag (`public.ecr.aws/lambda/python:3.12-x86_64`) or its repository (`amd64/python:3.11-slim`). cibuildwheel's default, `archs = "auto"`, builds only `x86_64` wheels on a Linux x86_64 runner, so a project that builds its wheels on x86 runners ships no aarch64 wheel until `archs` (or `CIBW_ARCHS_LINUX`) adds `aarch64` (Phase 2.4 "CI pipelines"). `long double`, numpy's long double types and fast-math flags change results between x86 and Graviton without an error: check them in Phase 3 (Results That Change Without Failing).

Instance types and AMI IDs need arm64 counterparts. A Graviton instance type is a sizing decision: record it under User Decisions Pending with the default from Phase 2.4, also when no file in the repository names the hosts (the same series and size as the hosts' x86 instance type). An AMI ID names one architecture: `aws ec2 describe-images --image-ids <id> --query 'Images[].[ImageId,Architecture,Name]'` shows which (executed: `al2023-ami-2023.12.20260930.0-kernel-6.18-x86_64` reports `x86_64` and its `-arm64` sibling `arm64`), and the arm64 AMI of the same release replaces it; the public SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` has an `-arm64` counterpart. ECS `cpuArchitecture` takes `X86_64` or `ARM64` (Fargate defaults to `X86_64`), and EKS `amiType` values come in pairs (`AL2023_x86_64_STANDARD` and `AL2023_ARM_64_STANDARD`). Change these only where the project ships the files ([agent-scope-boundaries.md](agent-scope-boundaries.md), IN SCOPE 6).

For each `CDLL` or `dlopen`, read the code that builds the path: a hard-coded x86 filename or a lookup table without an `aarch64` key is a FAIL. The heuristic misses a file that mentions `aarch64` anywhere, such as a test whose only assertion runs under `if platform.machine() == "x86_64":`; only the first grep shows it. An x86 header under `#ifdef __x86_64__` is fine; x86-only compiler flags are not.

Flag code that checks for `x86_64`/`amd64` without `aarch64`/`arm64` handling, builds library paths or download URLs from the architecture without an aarch64 case, compiles with x86-only flags, or pins container images to amd64. A test whose assertions run only on x86 does not block the migration: record it in `04-code-scan-findings.md` as COMPATIBLE with that note, leave it unchanged, and check the path it would have covered directly in Phase 3.3. One Dockerfile rule needs particular care: **`pip install` must run on the target platform.** Wheels are architecture-specific, so a stage that installs packages and is copied into the runtime image must run on `$TARGETPLATFORM` (Phase 2.4).

Every image the project builds from, tests with or deploys has to list `linux/arm64`, including images a library starts at run time: a test that creates `MySqlContainer("mysql:5.7")` starts `mysql:5.7`, which has no arm64 build. List the images and read each one's platforms from its registry, without pulling it:

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
  grep -rhoiE --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --include='*.y*ml' --include='*.json' \
    '"?image(uri)?"?[[:space:]]*:[[:space:]]*"?[a-z0-9][^"[:space:],}]*' . |
    sed -E 's/^"?[Ii][Mm][Aa][Gg][Ee]([Uu][Rr][Ii])?"?[[:space:]]*:[[:space:]]*"?//'
  grep -rhoE --exclude-dir=.venv --exclude-dir=.git --include='*.py' "Container\((image=)?[\"'][^\"']+" . |
    sed -E "s/^[^\"']*[\"']//"
} | grep -vE '\$|^scratch$' | sort -u > graviton-validation/raw/images.txt
# Platforms per image, from its registry (docker CLI). Without docker, or a login a private registry needs, the line is CHECK.
while IFS= read -r img; do
  if ! out=$(docker manifest inspect -v "$img" 2>&1); then printf 'CHECK   %s: %s\n' "$img" "$(printf '%s\n' "$out" | grep -v '^errors:$' | head -n 1)"
  elif printf '%s' "$out" | grep -q '"architecture": "arm64"'; then printf 'OK      %s\n' "$img"
  else printf 'FINDING %s: no linux/arm64 build\n' "$img"; fi
done < graviton-validation/raw/images.txt
```

`docker manifest inspect -v` prints every platform of a multi-architecture image and the one platform of a single-architecture image. A FINDING is fixed in Phase 2.4. On an ARM64 host a list without arm64 stops the pull (`no matching manifest for linux/arm64/v8 in the manifest list entries`), while a single amd64 manifest is pulled and its container stops with `exec format error` (`--platform linux/arm64` stops that pull: `was found but does not match the specified platform: wanted linux/arm64, actual: linux/amd64`).

## 1.5 Python Version Compatibility Check

> **Output: `graviton-validation/01-project-assessment.md`** (Python Environment section)

1. Document the interpreter version and the source it was read from (§1.1). Record the implementation (CPython; PyPy and others change the wheel tags and need their own probe).
2. Look up its support status live; do not use a remembered table, the dates move every October:
   ```bash
   curl -sS --fail -A "graviton-skill/1.0" https://devguide.python.org/versions/ | python3 -c "
   import sys, re, html
   want = '3.11'
   for r in re.findall(r'<tr[^>]*>(.*?)</tr>', sys.stdin.read(), flags=re.S):
       c = [html.unescape(re.sub(r'<[^>]+>', '', x)).strip() for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, flags=re.S)]
       if c and c[0] == want: print(f'Python {c[0]}: status={c[2]}, first release {c[3]}, end of life {c[4]}')"
   ```
   (The `-A` user agent matters: devguide.python.org returns 403 to urllib's default agent.)
3. CPython itself is not the blocker: the official `python:` images are multi-architecture, and the guidance is to target a release the devguide lists as supported, because package maintainers drop wheels for end-of-life releases first. An end-of-life interpreter is recorded as a RECOMMENDED UPGRADE with the live date, not as a blocker, unless §1.3 produced interpreter-ABI blockers.
4. **DO NOT change the interpreter version by default.** The gate is `python.interpreter_bump` in `skill-config.md`:
   - `never` (default): report ABI blockers with evidence and options; make no change
   - `ask`: present the blockers and the lowest interpreter that resolves them, and wait for approval
   - `approved=<3.X>`: the team pre-approved that version; apply it as a consequence of the required fix and record it in `01-project-assessment.md` and `00-summary.md`
   A bump is only in scope when it is the sole path to an aarch64 wheel for a required package; "3.10 is end of life" alone never justifies it.

   **One interpreter for the whole dependency set.** The interpreter is one decision covering every pin, never made for one package at a time, because a bump made for one package changes the wheel every other pin needs. Before proposing or applying a bump, rerun the §1.3 loop for each candidate interpreter over the whole resolved list (`PYVER=3.Y`, run in a 3.Y environment from Phase 3.0), and record for each candidate which pins are not COMPATIBLE and the lowest versions that fix them (03 report, Interpreter-ABI Blockers). Keep the current interpreter when every MUST UPGRADE finding is fixable there; otherwise choose the lowest candidate at which every pin is, and apply the bump and all of its pin changes together. When no single interpreter works for every pin, report the table as a user decision and change nothing.
5. Record `pip` on the target (§1.1): pip 19.3 is the first release that installs `manylinux2014` aarch64 wheels ([pip's changelog](https://pip.pypa.io/en/stable/news/)), and pip 20.3 the first that sees the `manylinux_2_N` tags most current aarch64 wheels carry ([wheel-verification.md](wheel-verification.md) §2); plan the upgrade in Phase 3 if it is older than 20.3.
