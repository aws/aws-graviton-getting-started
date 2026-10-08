# Phase 3: ARM64 Validation & Testing

Install, build and test on ARM64 architecture. Supported platforms: Linux, macOS, WSL.

## Container Runtime Detection

Before skipping validation, check for a container runtime that can run `linux/arm64` images. Apple Silicon Macs and Graviton hosts run them natively; x86 Linux hosts run them through QEMU emulation.

> **Skill config:** If `skill-config.md` defines `container.runtime`, pin `CONTAINER_CMD` to that value instead of running the auto-detection cascade below, but only after verifying it works; if the pinned runtime does not respond, fall back to the cascade. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

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

# Detect a WORKING container runtime. Being on PATH is not enough: a runtime can be installed
# but unusable (no daemon, no VM, missing permissions), so ask each one for `info`.
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
  $CONTAINER_CMD run --rm --init --platform linux/arm64 alpine:3.20 timeout 30 uname -m   # must print aarch64
fi
```

On the x86 host used to validate this skill, `finch` was on PATH but `finch info` failed, so a `command -v` cascade would have selected a runtime that cannot run anything; `docker` answered `info` and ran `linux/arm64` containers (`uname -m` printed `aarch64`). On a Graviton host (c9g.xlarge, Amazon Linux 2023) the block selected `docker` and printed `aarch64`. `host_timeout` keeps the host-side limits working where GNU `timeout` is missing: Homebrew's coreutils installs it as `gtimeout`, and also as `timeout` when the system has no `timeout` of its own; without either, `host_timeout` uses Python. Executed in bash 3.2.57 with no `timeout` or `gtimeout` on `PATH`, and in zsh 5.9 the same way: a 1-second command returned 0, a 30-second command given 2 seconds returned 124 after 2 seconds, and an exit code of 3 passed through.

**Decision logic:**
- **ARM64 host (aarch64/arm64) + container runtime:** Install, build and validate in containers using `$CONTAINER_CMD`. This is the ideal path.
- **ARM64 host (aarch64/arm64) + no container runtime:** Validate directly on the host, in a virtual environment (§3.0).
- **x86 host + container runtime with ARM64 support:** Use `--platform linux/arm64`. On x86 Linux this runs under QEMU emulation, which works for installing wheels, importing and testing, but is slow (see "Emulation limits" below).
- **x86 host + no container runtime:** Static analysis only (Phase 1). Document that ARM64 validation requires an ARM64 environment and recommend a Graviton instance or an ARM64 Mac with a container runtime.

**Match the production hosts.** A container uses its host's kernel, so validate on a host with the production page size (Phase 1.1): a 4KB-page host, including any x86 host under emulation and an Apple Silicon Mac, does not show failures that happen on 64KB pages. When the project builds its own native code, run its tests on the oldest Graviton generation it deploys to (Phase 2.5): a newer generation does not show `Illegal instruction`. Record both in `06-build-test-results.md`.

**Do NOT skip validation if a working container runtime is available.** Only recommend external validation as a last resort.

Throughout Phase 3, replace `docker` with `$CONTAINER_CMD` in all commands.

**Emulation limits (x86 host).** Observed while validating this skill with Docker 25.0 and QEMU registered through binfmt_misc:

- **Bound every container run, inside the container.** Five runs wrapped as `timeout N docker run ...` did not stop at their limit: Docker forwarded the stop signal into the emulated container, the container froze (even a plain `sleep 60` never finished), and the command waited until it was cancelled while the container kept running for hours until `docker rm -f`. Put the limit inside the container and remove the container afterwards:
  ```bash
  run_arm64() {  # usage: run_arm64 <seconds> <image> <command...>
    local limit="$1" img="$2" name="graviton-check-$$"; shift 2
    host_timeout "$((limit + 20))" $CONTAINER_CMD run --rm --init --name "$name" --platform linux/arm64 \
      "$img" timeout "$limit" sh -c "$*"
    local rc=$?
    $CONTAINER_CMD rm -f "$name" >/dev/null 2>&1   # no-op if the container already exited
    return $rc
  }
  ```
  With the limit inside the container, a `sleep 60` given 5 seconds returned in 6 seconds with nothing left running. The image must provide `timeout` (`python:3.11-slim` and `alpine:3.20` do).
- **Do not build packages from source under emulation.** A pygeos source build took about 14 minutes and failed, and one compiler run crashed (`gcc ... failed with exit code -11`). Build from source on Graviton hardware (or an ARM64 CI runner) instead: on a c9g.xlarge the same pygeos build took about 5 seconds once its two workarounds were in place (Phase 2.2).
- **Installing wheels under emulation is slow too.** A `docker build --platform linux/arm64` of the fixed fixture did not finish within 8 minutes, although no package was compiled: every compiled wheel the builder downloaded was an aarch64 wheel, the rest were pure-Python wheels, and the one sdist was pure Python. Natively on Graviton the same build took 14 seconds. On an x86 host the faster pattern is to download aarch64 wheels natively and only run the checks emulated:
  ```bash
  # Native on the x86 host: install aarch64 wheels into a directory (no compiling, no emulation)
  TARGET_LIBC_VER=2.41    # glibc from Phase 1.1 (python:3.11-slim); for a musl target use platforms() from Phase 1.3
  PLAT=(); i=${TARGET_LIBC_VER#*.}
  while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_aarch64"); i=$((i - 1)); done
  P=("${PLAT[@]}" --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.11 --implementation cp --abi cp311)
  python3 -m pip install "${P[@]}" --target /tmp/arm64-site --require-hashes -r requirements-locked.txt
  grep -v '^docopt==' requirements.txt > /tmp/req-wheels.txt    # --platform needs wheels; pure-Python sdists go in separately
  python3 -m pip install "${P[@]}" --target /tmp/arm64-site --upgrade -r /tmp/req-wheels.txt -r requirements-dev.txt   # the project's test requirements
  python3 -m pip install --no-deps --target /tmp/arm64-site --upgrade docopt==0.6.2

  # Emulated: run imports, startup and tests against that directory, in place on the read-only mount
  # (nothing is copied or written; -p no:cacheprovider stops pytest writing its cache)
  $CONTAINER_CMD run --rm --init --platform linux/arm64 -v /tmp/arm64-site:/site:ro -v "$PWD":/src:ro \
    -e PYTHONPATH=/site -e PYTHONDONTWRITEBYTECODE=1 python:3.11-slim timeout 300 sh -c 'cd /src && python3 -m pytest -q -p no:cacheprovider tests'
  ```
  For the fixed fixture this ran the full set of import, startup and test checks in 153 seconds; rerun with the flag array above, the installs and the tests (3 passed) took 57 seconds. The ELF scan from §3.1 needs no emulation: run it on the host against `/tmp/arm64-site` and the project's `vendor/` directory. This pattern validates the dependencies and the code, not the Dockerfile; build the image itself on ARM64 when possible.

## 3.0 Build Environment Preparation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Environment sections)

### Python Runtime Alignment

Compiled wheels and extensions are tagged with the interpreter's minor version (stable-ABI `abi3` builds are the exception), so ARM64 validation MUST use the same CPython minor version the project deploys (Phase 1.1): on aarch64 Python 3.11 the import system only looks for extension files ending in `.cpython-311-aarch64-linux-gnu.so`, `.abi3.so` or `.so`. A validation run on a different minor version tests different wheels.

**Where the interpreter comes from.** The same version can come from the official `python:` images, the distribution's packages (`dnf`/`apt`), a version manager (uv, pyenv, mise, asdf), conda, or Homebrew on a developer machine. For the migration, the origin changes three things; the minor version itself is still what decides the wheel tags:

- **Which pip runs, and how old it is.** On the x86 host used to validate this skill, a mise-installed Python 3.11 had pip 26.2.1 while the distribution's `/usr/bin/python3` (3.9) had pip 21.3.1. On Graviton with Amazon Linux 2023, the distribution's `python3.11` package came with pip 22.3.1. Check `python3 -m pip --version` for the interpreter the deployment actually uses.
- **Whether pip is there and allowed to install.** The `amazonlinux:2023` and `almalinux:9` images, and AlmaLinux 9.8 on Graviton, ship `python3` 3.9 with no pip module; AlmaLinux 8.10 ships `python3` 3.6.8 with pip 9.0.3, below the 19.3 that aarch64 wheels need; the distroless `python3-debian12` image has neither pip nor `ensurepip`; the `ubuntu:24.04` image ships no `python3` at all, and Ubuntu 24.04's `libpython3.12-stdlib` package installs an `EXTERNALLY-MANAGED` marker, so pip refuses to install into the system interpreter outside a virtual environment ([PEP 668](https://peps.python.org/pep-0668/); pip reports `externally-managed-environment`). Homebrew also marks its current Python as externally managed and directs project installs to a virtual environment ([Homebrew documentation](https://docs.brew.sh/Language-Runtimes-and-Packages)). Install into a virtual environment, never with `--break-system-packages`.
- **Whether the same tool exists on the target.** A version manager used on a laptop must also be available on Graviton. uv offers managed CPython builds for Linux aarch64 (`uv python list --all-platforms --all-arches` lists `cpython-3.11.16-linux-aarch64-gnu`); per uv's documentation these come from the python-build-standalone project, which mise also uses. pyenv builds CPython from source on the target (its README covers the build dependencies and the `configure` and compiler flags), which needs the build prerequisites below. `uv venv --python 3.11` uses an installed CPython 3.11 when it finds one (on the Graviton instance, the distribution's 3.11.16); `--managed-python` makes it use uv's own build, which installed the fixed fixture and passed its tests natively.

The highest `manylinux` tag pip accepts comes from the OS glibc, not from where the interpreter came from: on that host both interpreters accepted at most `manylinux_2_34_x86_64` (AL2023, glibc 2.34). Record the interpreter's origin and pip version in `01-project-assessment.md`, and validate with an interpreter from the same source as production.

Two more things to align before installing:

- **pip version.** pip 19.3 is the minimum that installs `manylinux2014` aarch64 wheels and pip 20.3 the minimum for `manylinux_2_N` tags ([../document_references/wheel-verification.md](../document_references/wheel-verification.md) §2). An older pip cannot see those wheels and falls back to building native packages from source. Check `python3 -m pip --version` and, inside the validation environment only, run `python3 -m pip install --upgrade pip` (the repo's documented workaround, [python.md section 1](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#1-installing-python-packages)). The `python:3.11-slim` image used here ships pip 24.0.
- **Build prerequisites**, only if an sdist build remains after Phase 2: pure-Python sdists (for example `docopt`) need no compiler; native sdists need the toolchain from [python.md section 1.1](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#11-prerequisites-for-installing-python-packages-from-source) plus the library headers the package names.

Build-time tools (build backends, compilers) may not support the newest setuptools, compiler or NumPy release. Runtime compatibility != build-time tooling compatibility; this matters whenever Phase 2 leaves an sdist build.

**Common build-tool sensitivities** (from the pygeos 0.14 sdist build in Phase 2.2, executed natively on Graviton):
- **setuptools:** 82.0.0 removed `pkg_resources`, so a `setup.py` that imports it stops at `ModuleNotFoundError: No module named 'pkg_resources'`; pass `setuptools<82` as a build constraint (`--build-constraint`, pip 25.3 or later; pip 26.2 no longer applies `PIP_CONSTRAINT` to build environments)
- **gcc 14:** incompatible pointer types are errors by default; older C extensions need `CFLAGS=-Wno-error=incompatible-pointer-types`
- **NumPy 2:** an extension built against NumPy 1.x needs `numpy<2` at run time

**If an sdist build fails with build-tool errors:**
1. Identify the build backend and its requirements from the sdist's `pyproject.toml` `[build-system]` table, or from the imports at the top of `setup.py`
2. Check compatibility with the current interpreter, setuptools, compiler and NumPy (the sensitivities above)
3. Apply the build constraint or `CFLAGS` from Phase 2.2, or the session-scoped Python alignment below
4. Document the package, the build requirement and the version that needed alignment

### Detect Project Target Version

```bash
# The deployed interpreter wins; fall back through the declared ones. Record which source decided.
PY_TARGET=$(grep -hoE '^FROM[^#]*python:[0-9]+\.[0-9]+' Dockerfile* 2>/dev/null | tail -1 | grep -oE '[0-9]+\.[0-9]+$')
[ -z "$PY_TARGET" ] && [ -f .python-version ] && PY_TARGET=$(cut -d. -f1,2 .python-version)
[ -z "$PY_TARGET" ] && PY_TARGET=$(grep -hoE 'requires-python *= *"[^"]*' pyproject.toml 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
[ -z "$PY_TARGET" ] && PY_TARGET=$(grep -hoE 'python_requires *= *"[^"]*' setup.py 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
[ -z "$PY_TARGET" ] && PY_TARGET=$(grep -hoE '^[[:space:]]*- python[=<>]+[0-9]+\.[0-9]+' environment.y*ml 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
echo "Project targets Python: $PY_TARGET"
```

Executed on all five fixture variants (pip, fixed pip, Poetry, uv, conda): each reported `3.11`. A `requires-python` such as `>=3.11,<3.13` is a range; the first number is the floor, so prefer the Dockerfile or `.python-version` when they exist.

### Session-Scoped Python Switching

Create an isolated environment with the target interpreter, outside the project tree (so the commit steps in SKILL.md never pick it up; adding it to `.gitignore` is out of scope). Never change the machine's default Python. On Amazon Linux 2023, `/tmp` is a RAM-backed `tmpfs` (3.8 GB on the 8 GiB c9g.xlarge used here), so an environment there uses memory: with three environments in `/tmp` taking 2.1 GB, a vLLM test on that instance ran out of memory, and it passed once they were moved to disk. For large environments, set `TMPDIR` to a disk-backed directory first.

```bash
# uv (downloads a managed interpreter if needed, leaves the system python3 alone).
# --seed installs pip into the environment; without it `python -m pip` fails with "No module named pip"
uv venv --seed --python "$PY_TARGET" "${TMPDIR:-/tmp}/graviton-venv" && . "${TMPDIR:-/tmp}/graviton-venv/bin/activate"

# A specific installed interpreter
"python$PY_TARGET" -m venv "${TMPDIR:-/tmp}/graviton-venv" && . "${TMPDIR:-/tmp}/graviton-venv/bin/activate"

# pyenv: current shell session only
pyenv shell "$PY_TARGET"

# conda: a prefix environment, used through `conda run`
conda create -y -p "${TMPDIR:-/tmp}/graviton-conda" "python=$PY_TARGET" && conda run -p "${TMPDIR:-/tmp}/graviton-conda" python --version

# Containers: the official image for the same minor version
$CONTAINER_CMD run --rm --init --platform linux/arm64 "python:$PY_TARGET-slim" timeout 60 python3 --version
```

Executed: `uv venv --seed --python 3.11` produced Python 3.11.9 with pip 26.2.1 while the host's `/usr/bin/python3` stayed at 3.9.25; a `conda create -p ... python=3.11 --dry-run` resolved without touching any shell configuration.

**ALLOWED:** virtual environments, `uv venv`, `pyenv shell` (pyenv's documentation: "select just for current shell session"), conda prefix environments with `conda run`, containers, single-command environment variables.

**FORBIDDEN:** editing `~/.bashrc`/`~/.zshrc`/`~/.bash_profile`, `pyenv global` ("select globally for your user account"), `conda init` (a dry run shows it would modify `~/.bashrc`), `update-alternatives` for `python3`, replacing `/usr/bin/python3`, and `pip install` into the system interpreter. After the transformation, the user's `python3 --version` must match its pre-transformation value.

> **Skill config:** If `skill-config.md` defines `python.interpreter_select` (`uv | pyenv | conda | system`), use that tool for the session-scoped environment above; `system` means the interpreter already on PATH, used through a virtual environment. This selects only the validation environment; the project's declared interpreter is governed by `python.interpreter_bump` (Phase 1.5). See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

**If no matching interpreter is found:** document the requirement and provide install commands; do NOT install automatically. Use `python.install_hint` from `skill-config.md` if defined; otherwise suggest `uv python install <version>` or the distribution's package for that version.

## 3.1 ARM64 Build Validation

> **Output: `graviton-validation/06-build-test-results.md`** (Build Attempts, Test Failure Classification)

### Build Strategy

> **Skill config:** Use `python.test_command` from `skill-config.md` for the test step in §3.2 if defined, and `python.index_url` / `python.extra_index_url` for every install. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

1. **First attempt:** install exactly as the deployment does, in its order (for the fixture: `pip install --require-hashes -r requirements-locked.txt`, then `pip install -r requirements.txt`), then build the project's own extensions (`pip install .` or the project's build command). Record, per package, whether pip used a wheel (`Downloading <name>-...-aarch64.whl` or `...-none-any.whl`) or built from source (`Building wheel for <name>`). Every source build on aarch64 must be either a pure-Python sdist or a native build the Phase 2 report expected.

2. **If the install, build or tests fail**, classify the root cause:
   - `ARM64`: architecture failure (blocking)
   - `INFRA`: missing services, credentials, network or mirror access (non-blocking)
   - `PRE-EXISTING`: fails the same way on x86 (non-blocking)

   Messages seen on the unfixed fixture, in a `linux/arm64` container and natively on Graviton, all `ARM64`:

   | Message | Cause |
   |---|---|
   | `THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE ... Expected sha256 b91c0375... Got 6ec585f6...` | hash lock lists the x86_64 wheel only |
   | `Could not find a version that satisfies the requirement blosc2==0.6.3 (from versions: 0.6.4, 0.6.5, ...)` (with `--only-binary=:all:`) | no aarch64 wheel for the pinned version |
   | `gcc: error: unrecognized command-line option ‘-mavx2’` | x86-only compiler flag in `setup.py` |
   | `ModuleNotFoundError: No module named 'pkg_resources'`, then `ERROR: Failed to build 'pygeos' when getting requirements to build wheel` (plain `pip install -r requirements.txt`) | no aarch64 wheel, so pip fell back to the sdist, which needs a build constraint (Phase 2.2) |

   A `from versions:` failure that appears only when installing from a mirror, a connection error, or missing index credentials is `INFRA`.

3. **INFRA or PRE-EXISTING failures:** document them and continue with the remaining steps. The installation that succeeds becomes the **final build**.

4. **ARM64 failures:** do NOT work around them (no `--no-deps`, no skipping the package). The failing build is the final build and requires resolution in Phase 2.

The final build command determines the build score.

### Container Validation (if containerized)

**Docker ENTRYPOINT handling:** override the entrypoint for validation commands.
- Wrong: `$CONTAINER_CMD run app:arm64 python3 -c '...'` (appends to the entrypoint or command)
- Correct: `$CONTAINER_CMD run --rm --entrypoint python3 app:arm64 -c '...'`

```bash
# Build
$CONTAINER_CMD build --platform linux/arm64 -t app:arm64 .

# Validate the architecture INSIDE the image
$CONTAINER_CMD run --rm --platform linux/arm64 --entrypoint python3 app:arm64 \
  -c 'import platform, sys; print(platform.machine(), sys.version.split()[0])'     # must print aarch64

# Every ELF file in the environment must be aarch64 (e_machine 183; x86-64 is 62),
# or sit next to an aarch64 build of the same file. Opens every file: wheels can carry executables.
$CONTAINER_CMD run --rm --platform linux/arm64 --entrypoint python3 app:arm64 -c '
import os, struct, collections, sysconfig
c, other = collections.Counter(), []
for root in {sysconfig.get_paths()[k] for k in ("purelib", "platlib")}:
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fh: h = fh.read(20)
            except OSError:
                continue
            if h[:4] == b"\x7fELF":
                m = struct.unpack("<H", h[18:20])[0]; c[m] += 1
                if m != 183: other.append(p)
print("ELF files by e_machine:", dict(c))
for p in other: print("not aarch64:", p)'
```

On an x86 host these run under emulation; bound them inside the container as in "Emulation limits", for example `$CONTAINER_CMD run --rm --init --platform linux/arm64 --entrypoint timeout app:arm64 120 python3 -c '...'` (this also overrides the image's entrypoint). Do not accept image metadata as proof: an image built with `FROM --platform=linux/amd64` and `--platform linux/arm64` was reported by `image inspect` as `arm64`, yet its interpreter was an `x86-64` executable (Phase 2.4). The scan opens every file, not only `*.so` files, because a `py3-none-any` wheel can carry executables: for selenium 4.48.0 it reported `{62: 1}` with `not aarch64: .../selenium/webdriver/common/linux/selenium-manager` and no aarch64 build next to it (a blocker: on Graviton, selenium 4.48.0 raises `Unsupported platform/architecture combination: linux/aarch64` before starting it, and the file itself fails with `Exec format error`), and for 4.50.0 `{62: 1, 183: 1}`, the x86-64 file sitting next to `linux-arm64/selenium-manager`, which selenium picks and runs on Graviton (fine). Add any project directory that holds compiled objects (for example a `vendor/` directory) to the scan. Scan `platlib` as well as `purelib`: in a Poetry environment on Amazon Linux 2023 every compiled package sat in `lib64/.../site-packages` (platlib), and a purelib-only scan found nothing. Executed natively on Graviton: the image build took 14 seconds, `platform.machine()` inside the image printed `aarch64 3.11.17`, the scan reported `{183: 99}`, the image's default command started the service on aarch64, and its `/srv/vendor` held the two aarch64 builds next to the two x86-64 ones (`{183: 2, 62: 2}`).

Verify the image uses the SAME base image distribution and version and the same Python minor version as the original.

### Host-Based Validation

```bash
python3 -c 'import platform, sys; print(platform.machine(), sys.version.split()[0])'   # aarch64, project version
python3 -m pip --version                                                               # >= 20.3
python3 -m pip install --require-hashes -r requirements-locked.txt && python3 -m pip install -r requirements.txt
```

Run inside the session-scoped environment from §3.0, then run the ELF scan above against the environment's `purelib` and `platlib`. Executed natively on Graviton, once with the distribution's Python 3.11.16 and once with uv's managed 3.11.9: every package installed from a wheel (docopt from its pure-Python sdist), the imports and the 3 tests passed, and the service loaded `libfastsum-aarch64.so`.

## 3.2 Functional Testing on ARM64

> **Output: update `graviton-validation/06-build-test-results.md`**

**Import smoke test first.** Import every package that Phase 1.3 found to ship compiled code, plus the project's own extensions, before running the full suite; a missing aarch64 binary shows up here in seconds. For NumPy, also print the BLAS it uses ([python.md section 2.5](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#25-testing-numpy-and-scipy-installation)):

```bash
python3 -c 'import numpy, pandas, PIL, blosc2, shapely, msgpack, markupsafe, charset_normalizer; print("imports OK")'
python3 -c 'import numpy as np; np.__config__.show()'
```

Executed on the fixed fixture in a `linux/arm64` container: all imports succeeded and NumPy 1.26.4 reported `"name": "openblas64"`.

**Containerized:** the shippable runtime image usually contains the installed packages and the application, but not the tests or the test runner. Run the ARM64 test suite one of these ways:

```bash
# Option A: a test stage pinned to --platform=$TARGETPLATFORM in the Dockerfile, built with
#           $CONTAINER_CMD build --platform linux/arm64 --target test .

# Option B: run the tests in the official image with the source mounted (same Python minor version):
$CONTAINER_CMD run --rm --init --platform linux/arm64 -v "$PWD":/src:ro python:3.11-slim timeout 900 sh -c \
  'cp -r /src /app && cd /app && pip install -q --require-hashes -r requirements-locked.txt && pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q tests'

# Option C (x86 hosts): the native-download pattern from "Emulation limits" above, which keeps
#           the emulated part to imports and tests
```

On an x86 host, Option B runs pip under emulation, which took longer than 8 minutes for the fixture's dependencies; prefer Option C there. Executed with Option C on the fixed fixture: `3 passed`. Natively on Graviton, Option B finished in 8 seconds with `3 passed`.

> Note (finch/lima on macOS): `-v` bind mounts only work for host paths shared into the VM. Finch's macOS VM template shares `~`, `/private`, `/var/folders` and `/tmp/lima`, plus any `additional_directories` from Finch's configuration. `/tmp` is not among them, so a project under `/tmp` is not visible inside the VM; use `/private/tmp` or a path under `~`, or `$CONTAINER_CMD build` (which sends the build context) instead.

**Host-based:** run the project's test command in the §3.0 environment (`python -m pytest`, `python -m unittest`, `tox`, or the Makefile target).

Classify all failures (`INFRA` / `ARM64` / `PRE-EXISTING`). Exercise the architecture-specific paths explicitly, not only through the test suite: `ctypes`/`cffi` library loads, accelerated paths with a pure-Python fallback, and anything that branches on `platform.machine()`. On the unfixed fixture the service started and returned the correct result on aarch64 through its fallback, while calling the accelerator directly raised `RuntimeError: Unsupported architecture: aarch64`; a passing smoke test can hide a broken native path.

**Final build determination:**
- All tests pass: the test run is the final build
- INFRA/PRE-EXISTING failures: document them; the successful install and build is the final build
- ARM64 failures: the failing build is the final build (do not skip tests)

## 3.3 Startup Validation

> **Output: update `graviton-validation/06-build-test-results.md`** (Startup Validation)

Verify:
1. The application starts without errors
2. `platform.machine()` reports `aarch64` at runtime
3. No `ImportError`, `ModuleNotFoundError`, `OSError` from library loads, or `GLIBC_` version errors in the startup log
4. Accelerated paths load the aarch64 binary (log the path that was loaded; on the fixed fixture: `vendor/libfastsum-aarch64.so`)

Several ARM64 failures do not mention the architecture. The first three rows were observed in `linux/arm64` containers and again natively on Graviton, the next two on Graviton and on AWS Lambda; the last is documented in python.md:

| Symptom | Actual cause |
|---|---|
| `OSError: .../libfastsum-x86_64.so: cannot open shared object file: No such file or directory` | the file exists (`ls` lists it) but is an x86-64 ELF |
| `ModuleNotFoundError: No module named '_fixture_ext'` | only `_fixture_ext.cpython-311-x86_64-linux-gnu.so` exists; the aarch64 interpreter never looks at that filename |
| `ModuleNotFoundError: No module named 'numpy.core._multiarray_umath'` | x86 wheel contents copied into an arm64 image (`$BUILDPLATFORM` builder, Phase 2.4) |
| `exec /usr/local/bin/python3: exec format error` | an amd64 image run on a Graviton host without emulation (an amd64 `--platform` pin, or a local tag holding the amd64 image) |
| `ImportError: Error importing numpy: you should not try to import numpy from its source directory` | on Lambda, an aarch64 layer attached to an `x86_64` function, or the reverse |
| `ImportError: /lib64/libm.so.6: version 'GLIBC_2.27' not found` | wheel built for a newer glibc than the OS ([python.md](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#python-wheel-glibc-requirements)) |

> **macOS-host false PASS.** A package can publish macOS arm64 wheels without any Linux aarch64 wheel: `tfx-bsl` 1.21.0 ships `macosx_11_0_arm64` wheels and no `aarch64` file. An install that works on an Apple-Silicon Mac therefore does not show that the package installs on Graviton. Validate in a `linux/arm64` container or on a Graviton host, which is authoritative.

Recommend to the user for independent testing: performance benchmarking, load testing, resource utilization measurement.

## Write Summary

> **Output: `graviton-validation/00-summary.md`**

After all phases complete, write the summary using the template from [../document_references/documentation-standards.md](../document_references/documentation-standards.md). This file consolidates exit criteria status and references (not duplicates) detail in files 01-06.
