# Phase 2: Compatibility Resolution

Apply fixes for ARM64-blocking issues identified in Phase 1. Update ONLY what is required for ARM64 compatibility (findings labelled MUST UPGRADE in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md)). Findings labelled user decision are presented with their options and left unchanged until the user chooses. In an unattended run, where no one can answer (an automated transformation, or a brief that says not to ask), apply the option the decision's Recommendation names instead of waiting, list it under User Decisions Pending as applied, with how to reverse it, and continue; a `skill-config.md` value that rules the change out still wins, and an item no option fixes, or whose options all lie outside the skill (such as the OS or the base image), stays unchanged and listed.

## Contents

- 2.1 Native Library Resolution
- 2.2 Dependency Compatibility Updates
- 2.3 Architecture Detection Code Updates
- 2.4 Build Configuration Updates
- 2.5 Graviton-Specific Runtime Recommendations

## 2.1 Native Library Resolution

> **Output: update `graviton-validation/02-native-library-report.md`** (Resolution Details)

For each x86-only binary and each x86-only build flag identified in Phase 1.2 and 1.4:

**If source code available:**

`$CONTAINER_CMD` is the working container runtime found by the detection block in [phase3-validation.md, Container Runtime Detection](phase3-validation.md#container-runtime-detection); run that block first (in a new shell, set `CONTAINER_CMD` again).

Build on aarch64 hardware: a Graviton host or an ARM64 CI runner, directly or inside a `linux/arm64` container, which runs natively there (the build prerequisites: `"@Development tools" python3-devel` on Amazon Linux / RHEL, `build-essential python3-dev` on Debian / Ubuntu; `gcc libc6-dev` is enough for a plain C library on a `python:*-slim` image). On an x86 host the same container runs under emulation, where source builds are slow and can crash (Phase 3, "Emulation limits"), so do not run these commands there:

```bash
# On an aarch64 host; timeout 900 bounds the package install and the build (raise it for a larger build).
# Plain shared library loaded through ctypes/cffi:
$CONTAINER_CMD run --rm --init --platform linux/arm64 -v "$PWD":/w -w /w -e HOST_IDS="$(id -u):$(id -g)" python:3.11-slim timeout 900 sh -c \
  'apt-get update && apt-get install -y gcc libc6-dev && gcc -shared -fPIC -O2 -o vendor/libfastsum-aarch64.so native/fastsum.c && chown "$HOST_IDS" vendor/libfastsum-aarch64.so'

# On an aarch64 host (timeout 900, as above). CPython extension, built with the project's own build system into a wheel in dist/
# (the .so inside the wheel is the file to vendor, if the project vendors a prebuilt copy):
$CONTAINER_CMD run --rm --init --platform linux/arm64 -v "$PWD":/w -w /w -e HOST_IDS="$(id -u):$(id -g)" python:3.11-slim timeout 900 sh -c \
  'apt-get update && apt-get install -y gcc libc6-dev && pip wheel --no-deps -w dist . && chown -R "$HOST_IDS" dist build *.egg-info'
python3 -m zipfile -l dist/*.whl | grep '\.so'   # the extension, e.g. _fixture_ext.cpython-311-aarch64-linux-gnu.so
python3 -m zipfile -e dist/*.whl "${TMPDIR:-/tmp}/whl" && cp "${TMPDIR:-/tmp}"/whl/_fixture_ext.*.so vendor/   # only if the project vendors the built file

# Verify
file vendor/libfastsum-aarch64.so  # Must show "ARM aarch64"
```

Keep `--platform linux/arm64` even on an aarch64 host: without it Docker runs whatever architecture the local tag holds. On Graviton, after an amd64 pull had replaced the local tag, the container failed with `exec format error`. `HOST_IDS` hands the files the container writes back to your user: on a Linux host, files written through a bind mount otherwise belong to root. A setuptools build also leaves `build/` and `*.egg-info` in the project (and the wheel in `dist/`); delete whatever the build created before the commit step, so `git add -A` does not record it.

**On an x86 host without aarch64 hardware**, a plain C library can be cross-compiled natively, with no emulation. Ubuntu 24.04 packages the cross compiler as `gcc-aarch64-linux-gnu`:

```bash
# timeout 600 inside the container: an upper bound, so a stalled apt-get cannot hold the session
$CONTAINER_CMD run --rm --init --platform linux/amd64 -v "$PWD":/w -w /w -e HOST_IDS="$(id -u):$(id -g)" ubuntu:24.04 timeout 600 sh -c \
  'apt-get update && apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu libc6-dev-arm64-cross && aarch64-linux-gnu-gcc -shared -fPIC -O2 -o vendor/libfastsum-aarch64.so native/fastsum.c && chown "$HOST_IDS" vendor/libfastsum-aarch64.so'
file vendor/libfastsum-aarch64.so  # Must show "ARM aarch64"
```

A CPython extension also needs the target's Python headers and build configuration, so build it on aarch64 hardware; until then, record it as an open item in `02-native-library-report.md`. Keep the x86 build next to the aarch64 one when the project still ships to x86: CPython picks the extension whose filename matches the running interpreter (`importlib.machinery.EXTENSION_SUFFIXES` on aarch64 is `['.cpython-311-aarch64-linux-gnu.so', '.abi3.so', '.so']`), so `_fixture_ext.cpython-311-x86_64-linux-gnu.so` and `_fixture_ext.cpython-311-aarch64-linux-gnu.so` can sit in the same directory.

Before rebuilding, remove x86-only compiler flags, or apply them only on x86 (see §2.4 "Extension build flags"): the fixture's unfixed `pip install .` on aarch64 stops at `gcc: error: unrecognized command-line option ‘-mavx2’` (gcc puts the option in typographic quotes in UTF-8 locales; observed natively on Graviton with gcc 11 and gcc 14). Headers such as `<immintrin.h>` must sit behind `#if defined(__x86_64__)` with a portable code path for the other branch; the fixture's include was already guarded, so only the flags needed changing.

**If source unavailable:** ask the user for an aarch64 build of the library, or confirm that a pure-Python fallback is acceptable (the fixture's `fast_sum` falls back to `sum()` when the load fails; record that the fallback is slower, not that the migration passed). For a binary that is really a PyPI package vendored by hand, take its aarch64 wheel instead of rebuilding (next block).

**Lambda layers and vendored site-packages:** re-create them for arm64 from the pins listed by `*.dist-info` (Phase 1.2.2). pip can download aarch64 wheels from an x86 host; offer the tags the target's glibc accepts (Phase 1.1), which for a layer is the function runtime's:

```bash
if . "${TMPDIR:-/tmp}/graviton-python-native_scan.sh"; then
  PYVER=3.11              # the function's runtime: python3.11 -> 3.11, python3.12 -> 3.12
  TARGET_LIBC=glibc; TARGET_LIBC_VER=2.26    # Phase 1.1: 2.26 for python3.10 and python3.11 (Amazon Linux 2), 2.34 for python3.12 and later
  TARGET_PAGE_SIZE=       # the function's page size, if measured in it (getconf PAGESIZE); unset, the scan skips the page check
  PLAT=(); i=${TARGET_LIBC_VER#*.}
  while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_aarch64"); i=$((i - 1)); done
  python3 -m pip install "${PLAT[@]}" --platform manylinux2014_aarch64 --only-binary=:all: \
    --python-version "$PYVER" --implementation cp --target python/ -r layer-requirements.txt
  native_scan python   # the function from Phase 1.2.1: no FINDING line
else echo "CHECK: run the Phase 1.2.1 scan block first: it writes ${TMPDIR:-/tmp}/graviton-python-native_scan.sh"; fi
```

The scan also reports executables inside `py3-none-any` wheels, such as selenium 4.48.0's x86-64 `selenium-manager`, which a check of one file misses. Layer contents go in `python/` at the root of the zip ([AWS Lambda Python layers](https://docs.aws.amazon.com/lambda/latest/dg/python-layers.html)). A package with no aarch64 wheel fails this command; resolve it in §2.2 first. The tag list matters: confluent-kafka 2.15.1's only aarch64 wheel is `manylinux_2_28`, so with `TARGET_LIBC_VER=2.26` the command fails for it, and a layer built from that wheel anyway imported on an arm64 `python3.12` function and failed on `python3.11` with `version 'GLIBC_2.28' not found` (Phase 1.1).

**Update native library loading logic** to handle ARM64:

```python
import ctypes, os, platform

def accelerator_library_path() -> str:
    arch = platform.machine()
    if arch in ("aarch64", "arm64"):
        return os.path.join(VENDOR, "libfastsum-aarch64.so")
    if arch in ("x86_64", "AMD64"):
        return os.path.join(VENDOR, "libfastsum-x86_64.so")
    raise RuntimeError(f"Unsupported architecture: {arch}")

try:
    lib = ctypes.CDLL(accelerator_library_path())
except (OSError, RuntimeError):
    lib = None  # pure-Python fallback; log it so a silent slow path is visible
```

`platform.machine()` returned `aarch64` in every `linux/arm64` container used to validate this skill.

## 2.2 Dependency Compatibility Updates

> **Output: update `graviton-validation/03-dependency-compatibility-report.md`**

Update ONLY dependencies flagged as MUST UPGRADE in Phase 1.3. Do NOT upgrade compatible dependencies. Prefer the *lowest* version that publishes an aarch64 wheel the target accepts (the project's interpreter, and the target's C library and glibc, which the probe's platform tags encode), not the latest: read the candidates from the probe's `from versions:` list (Phase 1.3), pick the lowest one at or above the current pin, and **probe that exact candidate** before writing it ([../document_references/wheel-verification.md](../document_references/wheel-verification.md) §3). Availability is not monotonic, so a version between the pin and the candidate may have no wheel.

> **Skill config:** If `skill-config.md` defines `python.index_url`, the new pin must resolve against that index as well as PyPI. If the mirror lacks the candidate's aarch64 wheel, record an INFRA item ("mirror needs blosc2 0.6.4 aarch64") rather than choosing a different version. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

**Direct dependencies (pip):** e.g. `blosc2==0.6.3` had no cp311 aarch64 wheel; the lowest candidate in the probe output was 0.6.4, and its probe returned `blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`:

```text
# requirements.txt
blosc2==0.6.4   # lowest version with a cp311 aarch64 wheel (was 0.6.3, x86_64 wheel only)
```

**Transitive dependencies (pip):** pin through a constraints file, which constrains a version without adding the package as a requirement:

```text
# constraints.txt
msgpack==1.1.0
```

```bash
pip install -c constraints.txt -r requirements.txt     # or set PIP_CONSTRAINT=constraints.txt in the Dockerfile
```

For other managers use their own mechanism and regenerate the lock, never edit a lock by hand ([../document_references/package-manager-mapping.md](../document_references/package-manager-mapping.md) §2):

| Manager | Direct pin | Transitive pin | Then |
|---|---|---|---|
| pip-tools | edit `requirements.in` | add the transitive to `requirements.in` with a comment | `pip-compile --generate-hashes` |
| uv | edit `[project].dependencies` | `[tool.uv] override-dependencies = ["msgpack==1.1.0"]` (or `constraint-dependencies`) | `uv lock` |
| Poetry | edit the dependency | no override table: `poetry add --lock "msgpack==1.1.0"` and note why | `poetry lock` |
| conda | edit the spec in `environment.yml` | pin it explicitly in `environment.yml` | re-solve; `conda-lock -p linux-64 -p linux-aarch64` if a lock is kept |
| Pipenv / PDM | edit `Pipfile` / `[project]` | `[packages]` entry / `[tool.pdm.resolution.overrides]` | `pipenv lock` / `pdm lock` |

The uv and Poetry rows were executed on the fixture variants (each regenerated lock contained the `blosc2-0.6.4` aarch64 wheel); the conda-lock command was executed for `linux-64` and `linux-aarch64`; Pipenv and PDM locks were generated in scratch projects.

**Hash-locked requirements:** add the aarch64 wheel's hash beside the x86 one, or regenerate the file with a tool that records every published file:

```bash
TARGET_LIBC_VER=2.41    # Phase 1.1 (python:3.11-slim): every tag the target's glibc accepts, as in the Phase 1.3 probe
PLAT=(); i=${TARGET_LIBC_VER#*.}
while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_aarch64"); i=$((i - 1)); done
python3 -m pip download --only-binary=:all: --no-deps -d /tmp/aarch64-wheels "${PLAT[@]}" \
  --platform manylinux2014_aarch64 --python-version 3.11 --implementation cp --abi cp311 "MarkupSafe==2.1.5"
python3 -m pip hash --algorithm sha256 /tmp/aarch64-wheels/MarkupSafe-2.1.5-*.whl
# append the printed --hash=sha256:... as a second --hash on the MarkupSafe line
# or: pip-compile --generate-hashes requirements.in   (records the hashes of all published files)
```

**Packages with no aarch64 build in any release:** these need a substitute, and substitutions change behaviour, so present the evidence and wait for the user (an unattended run applies the recommended substitute, as stated at the top of this phase). `mkl` (and its transitives `intel-openmp`, `tbb`, `intel-cmplr-lib-ur`, `tcmlib`, `umf`, `onemkl-license`) has no Linux aarch64 file in any release. Confirm nothing imports it directly, then remove it:

```bash
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.py' '^[[:space:]]*(import|from)[[:space:]]+mkl([^[:alnum:]_]|$)' .   # no output = safe to remove
```

The default NumPy and SciPy wheels use OpenBLAS, so removing `mkl` leaves NumPy working with OpenBLAS on Graviton.

**Packages whose aarch64 wheels stopped:** present the options and record the user's choice in the "User Decisions Pending" table. Example from the fixture, `pygeos==0.14` (no aarch64 wheel, no later release, and 0.13 has wheels only up to cp310). Its PyPI description says "PyGEOS was merged with Shapely (https://shapely.readthedocs.io) in December 2021 and will be released as part of Shapely 2.0". The options are:

- (a) Build the 0.14 sdist on Graviton against the distribution's GEOS (`libgeos-dev`). On current toolchains it needs two workarounds, on any architecture: its `setup.py` imports `pkg_resources`, which setuptools removed in 82.0.0, so the build environment needs `setuptools<82`; and gcc 14 rejects its code (`incompatible-pointer-types` errors in `src/ufuncs.c`). Pass the setuptools limit with `--build-constraint` (pip 25.3 and later): since pip 26.2, `-c` and `PIP_CONSTRAINT` no longer reach isolated build environments.

  ```bash
  echo 'setuptools<82' > build-constraints.txt
  CFLAGS=-Wno-error=incompatible-pointer-types python3 -m pip install --build-constraint build-constraints.txt "numpy<2" pygeos==0.14
  ```

  Without the constraint the build stops at `ModuleNotFoundError: No module named 'pkg_resources'` (with pip 26.2.1, `PIP_CONSTRAINT` alone does not help), and without the `CFLAGS` at the pointer-type errors. Keep numpy below 2 at runtime (the project's own numpy pin): the build compiles against NumPy 1.x, and with numpy 2.4.6 installed next to it the import failed with `AttributeError: _ARRAY_API not found`.
- (b) Move to `shapely>=2.0` (2.0.0 is the first Shapely release with cp311 Linux aarch64 wheels). This changes the API, so the code changes are outside this skill.

**Documented aarch64 correctness floors:** a `numpy` pin below 1.21.1 or a `scipy` pin below 1.7.2 is flagged MUST UPGRADE even when it installs, because those releases carry an older OpenBLAS with aarch64 correctness fixes missing. Target the floor, or the lowest version that also ships a wheel for the project's interpreter if that is higher (for cp311, numpy 1.23.2).

**Interpreter-ABI blockers:** if a required package only ships aarch64 wheels for a different interpreter, follow `python.interpreter_bump` (Phase 1.5): `never` leaves the pin and reports it; `ask` waits for approval; `approved=<3.X>` applies the bump and records it in `01-project-assessment.md`. An approved bump is applied together with every pin change it requires (Phase 1.5, "One interpreter for the whole dependency set"): regenerate the lock through the project's manager at the new interpreter, then rerun the §1.3 loop with the new `PYVER`.

After the changes, keep the Phase 1 evidence that `03-dependency-compatibility-report.md` cites (`cp graviton-validation/raw/wheel-availability.txt graviton-validation/raw/wheel-availability-phase1.txt`, and the same for `requirements-resolved.txt`), then re-run the Phase 1.1 flat-pin step, the Phase 1.3 probe and the hash-lock check.

## 2.3 Architecture Detection Code Updates

> **Output: update `graviton-validation/04-code-scan-findings.md`** (Changes Applied)

Add `aarch64` handling to all architecture detection:

```python
# Before
if platform.machine() == "x86_64":
    path = os.path.join(VENDOR, "libfastsum-x86_64.so")
else:
    raise RuntimeError(f"Unsupported architecture: {platform.machine()}")

# After
arch = platform.machine()
if arch in ("aarch64", "arm64"):
    path = os.path.join(VENDOR, "libfastsum-aarch64.so")   # ARM64 code path
elif arch in ("x86_64", "AMD64"):
    path = os.path.join(VENDOR, "libfastsum-x86_64.so")
else:
    raise RuntimeError(f"Unsupported architecture: {arch}")  # generic fallback
```

Shell scripts get the same treatment; map `uname -m` to the artefact naming the vendor uses:

```bash
case "$(uname -m)" in
  x86_64)  TOOL_ARCH=amd64 ;;
  aarch64) TOOL_ARCH=arm64 ;;   # confirm the vendor publishes this asset before relying on it
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
curl -sSL -o /usr/local/bin/tool "https://example.invalid/releases/tool-linux-${TOOL_ARCH}"
```

Change only the architecture handling. The fixture's deploy script keeps its URL, flags and structure; if the vendor publishes no arm64 asset, the item stays a user decision (Phase 1.3 "Build-Time Binaries Outside the Dependency Tree").

## 2.4 Build Configuration Updates

> **Output: update `graviton-validation/04-code-scan-findings.md`** (Changes Applied)

**Extension build flags:** apply x86-only flags only when building on x86:

```python
# setup.py
import platform
ARCH_FLAGS = ["-mavx2", "-march=haswell"] if platform.machine() in ("x86_64", "AMD64") else []
ext = Extension("_fixture_ext", sources=["native/fixture_ext.c"], extra_compile_args=["-O3", *ARCH_FLAGS])
```

Without the guard, the build on aarch64 stops at `unrecognized command-line option ‘-mavx2’`. Apply the equivalent condition in CMake, meson, or Cargo build scripts. Adding Graviton tuning flags (`-mcpu=...`) is an improvement, not a required change (§2.5). Source that calls x86 intrinsics (an `*intrin.h` header, `_mm_*` functions) needs an Arm path: `sse2neon.h` ([sse2neon](https://github.com/DLTcollab/sse2neon)) implements the SSE to SSE4.2 and AES intrinsics with NEON, but no AVX (`_mm256_*`); port what it does not cover, and the hot paths found by profiling on Graviton, to NEON intrinsics.

**Dockerfile updates (containerized deployments only):**

PRESERVE the current base image distribution and version. Do NOT change the Python version or the image tag. One tag change is in scope: a tag or repository that names one architecture (`public.ecr.aws/lambda/python:3.12-x86_64`, `amd64/python:3.11-slim`) becomes the same image's multi-architecture tag (`public.ecr.aws/lambda/python:3.12`, `python:3.11-slim`); the distribution and version stay. An image with no arm64 build at its tag (Phase 1.4) moves to the lowest tag of the same image that lists `linux/arm64` (`mysql:5.7` lists only amd64, `mysql:8.0` lists arm64 too): a user decision, which an unattended run applies and records with how to reverse it. A library that starts such an image moves to its lowest version whose image has an arm64 build (MUST UPGRADE).

> **Skill config:** If `skill-config.md` defines `container.base_image_registry`, redirect the base image(s) to pull from that registry/namespace while keeping the SAME distribution and version (e.g. `python:3.11-slim` → `<registry>/python:3.11-slim`). If absent, leave the existing registry unchanged. **Verify the mirror is reachable before redirecting**: if the configured registry does not resolve or pull from the build host, do NOT rewrite the `FROM`; keep the original registry and record the skipped redirect in `01-project-assessment.md`. **If the project ships no Dockerfile/container assets**, record "container config supplied but not applicable (no container assets)" in `01-project-assessment.md`. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Single-stage (the whole image is the deployable artifact):
```dockerfile
# Omit --platform and let the build's --platform linux/arm64 drive it.
FROM <current-base-image>:<current-version>
```

Multi-stage (a builder installs packages, the runtime copies them):
```dockerfile
# Builder: $TARGETPLATFORM, because wheels are architecture-specific
FROM --platform=$TARGETPLATFORM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt requirements-locked.txt ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements-locked.txt && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime: no --platform pin
FROM python:3.11-slim
WORKDIR /srv
COPY --from=builder /install /usr/local
COPY app ./app
COPY vendor ./vendor
CMD ["python", "-m", "app.service"]
```

Key rules:
- **A stage that runs `pip install` (or `uv sync`, `poetry install`, `conda env create`) and is copied into the deployable image must run on `$TARGETPLATFORM`.** The defect shows only when the build host is x86, where a `$BUILDPLATFORM` stage installs x86 wheels: copied into an arm64 runtime, `import numpy` failed with `ModuleNotFoundError: No module named 'numpy.core._multiarray_umath'`.
- **Remove `--platform=linux/amd64` pins and amd64 image digests** from every stage that ends up in the image. An image built from `FROM --platform=linux/amd64 python:3.11-slim` with `docker build --platform linux/arm64` was reported by `docker image inspect` as `arm64`, yet its interpreter was x86-64: check inside the image (Phase 3.1), never its metadata. On a Graviton host without emulation an amd64 image does not start at all: `exec /usr/local/bin/python3: exec format error`.
- **Tests in a builder stage run on the builder's platform.** If they matter for ARM64 validation, run them in a stage pinned to `$TARGETPLATFORM` or in a `linux/arm64` container (Phase 3.2).

Host-based deployments skip Docker steps.

**Lambda functions and layers (only if the project already ships the template):** set `Architectures: [arm64]` on each function in the SAM/CloudFormation template (`architecture=Architecture.ARM_64` in a CDK app, `architectures = ["arm64"]` in Terraform; a function that names none runs on x86_64) and rebuild any layer for arm64 (§2.1) with the tags of the function's runtime. Do not add a template the project does not have, and do not change the runtime: moving `python3.11` to `python3.12` changes the interpreter and the OS, so it follows `python.interpreter_bump`. [Lambda instruction set architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html) documents the `arm64` value. Both changes are needed: with `x86_64` left in the template, the function failed to import the arm64 layer's numpy with `ImportError: Error importing numpy: you should not try to import numpy from its source directory`.

**Deployment manifests (only if the project already ships them):**

If the project contains Kubernetes/Helm manifests (or similar deployment descriptors), ensure they can schedule onto ARM64 nodes. Only touch node selection, image registry, and ingress vocabulary; do NOT restructure manifests or add resources the project does not already have. If no manifests are present, skip this step.

> **Skill config:** If `skill-config.md` defines `deploy.arch_selector` / `deploy.nodepool_label` / `deploy.registry` / `deploy.ingress_convention`, use those values for the node selector, nodepool label, image registry, and ingress convention respectively. If absent, use the generic `kubernetes.io/arch` label as the capacity rule below says, and leave the existing registry/ingress unchanged. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

On a one-node Graviton cluster, a Deployment with `nodeSelector: kubernetes.io/arch: amd64` stayed `Pending` with `0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector`.

Change a node selector, a node affinity or the `cpuArchitecture` of an ECS task on EC2 capacity to arm64 only together with arm64 capacity in the files the project ships (a node group, NodePool, capacity provider or instance type): a pod whose selector no node matches stays `Pending`. Without that capacity, allow both architectures (a node affinity on `kubernetes.io/arch` with `operator: In` and the values `amd64` and `arm64`) and ship a multi-architecture image, so the workload keeps its x86 nodes until arm64 nodes exist. An instance type in those files gets the same series (`m`, `c`, `r`, ...) and size in the newest Graviton generation the region offers, with `g` for the processor letter (`m6i` and `m5a` become `m*g`) and its other letters kept (`m5d`, with instance store volumes, becomes `m*gd`); when no Graviton type keeps them, change nothing and list it. It goes under User Decisions Pending because sizing is the team's call (an unattended run applies it). With AWS credentials, list the candidates for `m5.xlarge`:

```bash
aws ec2 describe-instance-type-offerings --region us-west-2 --location-type region \
  --filters 'Name=instance-type,Values=m*g.xlarge' --query 'InstanceTypeOfferings[].InstanceType' --output text
```

Executed in us-west-2, it listed `m6g.xlarge`, `m7g.xlarge`, `m8g.xlarge` and `m9g.xlarge`, so the default is `m9g.xlarge`.

**CI pipelines (only if the project already ships them):** apply the changes that only add or switch an architecture, and leave the rest of the pipeline as it is: add `linux/arm64` to the platforms an image build publishes (`docker buildx build --platform linux/amd64,linux/arm64`, or the `platforms` input of `docker/build-push-action`) with the two steps it needs on an x86 runner: QEMU (`docker/setup-qemu-action`; elsewhere `docker run --privileged --rm tonistiigi/binfmt --install all`; where no privileged container may run, use the arm64 job below), or an arm64 `RUN` step stops with `exec /bin/sh: exec format error`, and a builder for several platforms (`docker/setup-buildx-action`; elsewhere `docker buildx create --driver docker-container --use`), or an engine without the containerd image store, which Docker Engine 29.0 and later use by default only on a fresh installation, stops with `Multi-platform build is not supported for the docker driver`; add `aarch64` to cibuildwheel's `archs`, with QEMU registered on an x86 runner (cibuildwheel's documentation uses `docker/setup-qemu-action`), or add an arm64 job beside the x86 one (a GitHub-hosted `ubuntu-24.04-arm` runner, a CodeBuild `ARM_CONTAINER` environment). Record each change in `04-code-scan-findings.md`. Anything else the pipeline needs (credentials, deployment steps, triggers, tool versions) is a recommendation in `00-summary.md`; with `ci.changes: recommend` in `skill-config.md`, the architecture changes are recommendations too.

## 2.5 Graviton-Specific Runtime Recommendations

> **Output: `graviton-validation/05-runtime-configuration.md`**

Do NOT apply runtime settings automatically. Document recommendations in the report for the team to evaluate during performance testing, each with its evidence level from the validation ladder in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md) and the exact source (Phase 2.5 for a level-A row, the link for a level-B row). Include only rows for libraries the project actually uses.

**Interpreter:** target a release the devguide lists as supported (bugfix or security; Phase 1.5 reads it). Record the project's version with its status; any change goes through `python.interpreter_bump`.

**Numerical libraries (NumPy, SciPy):**

| Recommendation | Applies when | Level |
|---|---|---|
| Default NumPy/SciPy wheels use OpenBLAS; no action needed for correctness once the §2.2 floors are met | NumPy or SciPy present | A |
| BLIS as an alternative BLAS: benchmarking with BLIS may find more performance | performance-sensitive linear algebra | measure before adopting |
| `OMP_NUM_THREADS` (OpenBLAS built with `USE_OPENMP=1`) and `BLIS_NUM_THREADS` (BLIS built with `--enable-threading=openmp`); both default to one thread in those builds | the project builds OpenBLAS or BLIS itself | A |

**ML frameworks:**

| Framework | Recommendation | Applies when | Level |
|---|---|---|---|
| PyTorch | `DNNL_DEFAULT_FPMATH_MODE=BF16` when `grep -q bf16 /proc/cpuinfo` (Graviton3 and later), `LRU_CACHE_CAPACITY=1024`, `THP_MEM_ALLOC_ENABLE=1`, `OMP_NUM_THREADS` per the formula, `OMP_PROC_BIND=false`, `OMP_PLACES=cores`; `torch.compile`; channels-last for CNNs | PyPI wheels or Docker Hub images (AWS DLCs already enable the optimizations) | A |
| TensorFlow | `TF_ENABLE_ONEDNN_OPTS=1` for TensorFlow older than 2.14; `DNNL_DEFAULT_FPMATH_MODE=BF16` on Graviton3(E); OMP settings; `intra_op_parallelism_threads` / `inter_op_parallelism_threads` | PyPI wheels | A |
| ONNX Runtime | session option `mlas.enable_gemm_fastmath_arm64_bfloat16 = "1"` | ONNX Runtime 1.17.0 or later on Graviton3(E) | A |
| llama-cpp-python | pass `n_threads` equal to the vCPU count when creating the `Llama` object ("Without this set, the python bindings use half of the vcpus") | llama-cpp-python | A |

**Compiler flags for in-repo extensions:** each Graviton generation has a "performance" flag (`-mcpu=neoverse-n1` / `-v1` / `-v2` / `-v3`) and a "balanced" one (`-march=armv8.2-a` for Graviton2, `-mcpu=neoverse-512tvb` for Graviton3 and later), and code built for a newer generation may not run on an older one. Record the flag that matches the oldest Graviton generation the team deploys to, as a recommendation to measure (level A for the flag guidance, measure before adopting for the gain). Builds that contain SVE instructions (`-march=armv8.2-a+sve`, `-mcpu=neoverse-512tvb`, or `-mcpu=native` on Graviton4) stopped with `Illegal instruction` (exit code 132) on Graviton2, while the `-march=armv8.2-a` build ran on Graviton2, Graviton3 and Graviton4. A build host newer than the oldest deployed generation hides this, so Phase 3 runs on the oldest generation.

Nothing else is recommended without a written source. In particular, do not recommend worker counts, garbage-collector settings or allocator changes for Python services unless the project's own documentation or a cited source covers them.

The report should note the project's interpreter, the frameworks found, and which rows (if any) apply; an application with none of these libraries gets the interpreter row and "Not Applicable" for the rest.
