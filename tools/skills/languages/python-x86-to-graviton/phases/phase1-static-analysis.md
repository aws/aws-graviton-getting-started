# Phase 1: Static Compatibility Analysis

Analyze the project without making changes. All findings are documented in `graviton-validation/` files.

> **Skill config:** Wherever a step below runs `pip`, `uv`, `poetry` or `conda`, use `python.package_manager` from `skill-config.md` (if defined) to skip auto-detection, `python.index_url` / `python.extra_index_url` as the index for every probe (and probe PyPI as well, see §1.3), and `python.interpreter_bump` in §1.5. See [../document_references/skill-configuration.md](../document_references/skill-configuration.md).

Phase 1 runs on any host, including x86, and installs nothing into the project or its environment. Most checks read files or ask the package index; three kinds of step run code. The §1.1 dry run (`pip install --dry-run` without `--only-binary`) runs the build backend (`setup.py` or the `pyproject.toml` backend) of every sdist it resolves, and of the project itself when the step installs `.`. The §1.1 target probe runs the base image's own `python3` in a container, and §1.2.2 runs the distribution's package tools in containers. The §1.3 probes pass `--only-binary=:all:`, so they never build or run a package. For a repository or an index you do not trust, run Phase 1 in a disposable container or VM. The project's own code and tests run only in Phase 3.

## 1.1 Project Structure Analysis

> **Output: `graviton-validation/01-project-assessment.md`**, **`graviton-validation/raw/dependency-tree-full.json`** and **`graviton-validation/raw/requirements-resolved.txt`**

### Determine Deployment Type

```bash
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -name 'Dockerfile*' -o -name 'docker-compose*.y*ml' -o -name 'template.y*ml' -o -name 'serverless.yml' \
     -o -name 'Procfile' -o -name '*.service' -o -name 'samconfig.toml' \) -print
grep -lE "AWS::Serverless::Function|AWS::Lambda::Function" template.y*ml 2>/dev/null
```

- Dockerfile or container config present: **Containerized**
- SAM / CloudFormation / serverless template with a Lambda function: **Lambda** (also check for layer zips and a `python/` directory, §1.2.2)
- systemd unit, Procfile, or a plain `python -m app` entry point: **Host-based**
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

Record every manager marker present, then decide which file the **deployment** installs from (that file is authoritative; a `pyproject.toml` kept only for packaging does not decide anything). Full detection table and per-manager commands: [../document_references/package-manager-mapping.md](../document_references/package-manager-mapping.md).

```bash
ls -1 requirements*.txt constraints*.txt pyproject.toml setup.py setup.cfg poetry.lock uv.lock \
      Pipfile Pipfile.lock pdm.lock environment.y*ml conda-lock.yml hatch.toml 2>/dev/null

# What does the deployment actually run? Dockerfile, Makefile, CI, scripts.
grep -nE "pip (install|sync)|uv (sync|pip install|export)|poetry (install|sync|export)|conda (env create|install)|pipenv (install|sync)|pdm (install|sync)" \
  Dockerfile Makefile *.sh .github/workflows/*.y*ml .gitlab-ci.yml buildspec.yml 2>/dev/null
```

Executed on the fixture: markers `requirements.txt`, `requirements-locked.txt`, `requirements-dev.txt`, `setup.py`; the Dockerfile and Makefile both run `pip install --require-hashes -r requirements-locked.txt` followed by `pip install -r requirements.txt`, so those two files are authoritative and `requirements-dev.txt` is test-only.

Interpreter, in order of authority (the first hit decides; record its source):

```bash
grep -nE "^FROM" Dockerfile*                                  # python:3.11-slim -> 3.11
[ -f .python-version ] && cat .python-version                # pyenv / uv pin
grep -nE "requires-python|python_requires" pyproject.toml setup.py setup.cfg 2>/dev/null
grep -nE "^python_version|^[[:space:]]*runtime:|^[[:space:]]*- python[=>]" Pipfile template.y*ml environment.y*ml 2>/dev/null
```

Also record where that interpreter comes from (official image, distribution package, uv/pyenv/mise/asdf, conda) and its pip version: the origin decides which pip runs and whether pip is installed or allowed to install into it (Phase 3.0, "Where the interpreter comes from"). The interpreter decides the `cp3XY` tag every probe in §1.3 uses. A mismatch between sources (for example `.python-version` 3.12 but the Dockerfile ships `python:3.11-slim`) is itself a finding to record: probe with the deployed one.

### Determine Target OS and glibc

The wheel a pin resolves to must also be accepted by the target's libc and pip, and native code also depends on the kernel page size of the hosts it runs on (see [../document_references/wheel-verification.md](../document_references/wheel-verification.md) §1, §2 and §7). Read the libc and the interpreter from the runtime image:

`$CONTAINER_CMD` below is the working container runtime: run the detection block in [phase3-validation.md, Container Runtime Detection](phase3-validation.md#container-runtime-detection) first, in the same shell (it also applies `container.runtime` from `skill-config.md`). With no working runtime, follow the "No container runtime" item after the block.

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
$CONTAINER_CMD run --rm --init --platform linux/arm64 --entrypoint python3 "$IMG" -c "$PROBE" ||
  $CONTAINER_CMD run --rm --init --platform linux/arm64 --entrypoint timeout "$IMG" 60 sh -c \
    'echo "arch=$(uname -m) libc=$(getconf GNU_LIBC_VERSION 2>/dev/null || ls /lib/ld-musl-* 2>/dev/null) python3=$(command -v python3 || echo none)"'
```

The probe asks the image's own `python3`, because `sh -c` with `ldd --version` and `pip debug` misreads common targets: executed natively on Graviton4 against 16 base images, that form printed empty fields with exit code 0 for Alpine (its `ldd --version` prints no glibc version) and for images without `python3` or pip, and did not run in the Lambda base images or distroless, whose `ENTRYPOINT` receives the command as arguments. The block above reported all 16: 11 through `python3` and the 5 without it (`ubuntu:22.04`, `ubuntu:24.04`, `debian:12`, `amazonlinux:2`, `almalinux:8`) through the fallback, in a second or less each once pulled, and in 5 to 23 seconds each under emulation on x86, including the pull. The limits are inside the container (`signal.alarm` in the probe, `timeout` in the fallback) because under emulation a host-side `timeout` does not reliably stop the container (Phase 3, "Emulation limits"). Executed on the fixture (`python:3.11-slim`): `arch=aarch64 libc=glibc 2.41 max_tag=manylinux_2_41_aarch64 python=3.11.17 (/usr/local/bin/python3) pip=24.0 venv=yes externally_managed=False`; wheel-verification.md §7 lists the other images. Record the libc as `TARGET_LIBC` and `TARGET_LIBC_VER` for §1.3 (`TARGET_LIBC=glibc TARGET_LIBC_VER=2.41` for the fixture).

- **No `python3` in the base image** (the fallback line): the deployment installs Python in a later step (`apt-get install python3`, `dnf install python3.11`), so the interpreter and pip come from that package. The libc still comes from the base image; read the rest from the built image or the distribution's package before §1.3.
- **Lambda functions deployed as .zip archives** have no image: the runtime identifier sets the OS. `python3.12` and later run on Amazon Linux 2023 (glibc 2.34), `python3.10` and `python3.11` on Amazon Linux 2 (glibc 2.26) ([Lambda Python runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html)); wheel-verification.md §7 shows a `manylinux_2_28` layer that imports on `python3.12` and fails on `python3.11`. For container-image functions, run the block against the image.
- **No arm64 variant of the base image:** both runs stop with `no matching manifest for linux/arm64 in the manifest list entries` (executed with `amazonlinux:2018.03`, whose manifest list has only `amd64`). That is a MUST UPGRADE finding, and the replacement image is a user decision ([../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md), OUT OF SCOPE).
- **No container runtime:** use the table in wheel-verification.md §7 and say so. For host-based deployments read the AMI's distribution.
- **Kernel page size of the deployment hosts.** A container uses its host's kernel, so the page size comes from the EC2 hosts or Kubernetes nodes, not from the image: a Debian 13 container on an AlmaLinux 8 Graviton2 host reported 65536. Run `getconf PAGESIZE` on a deployment host (executed on Graviton: AlmaLinux 8.10 65536; AlmaLinux 9.8 and Amazon Linux 2023 4096); if no host can be reached, ask the team that runs them and record the page size as unknown until then. A 64KB-page target needs Phase 3 on a 64KB-page host: on AlmaLinux 8, polars 0.20.20 aborted with `<jemalloc>: Unsupported system page size`, as did every earlier release tested back to 0.15.1, while 0.20.21 and the later releases tested imported. On the 4KB AlmaLinux 9 host polars 0.15.1 imported, so a 4KB validation host hides the failure.

Record `pip` on the target: below 19.3 it cannot install aarch64 wheels at all (python.md section 1), and below 20.3 it cannot see `manylinux_2_N` tags; plan the `python3 -m pip install --upgrade pip` step for Phase 3. `pip=none` (the `python3` of Amazon Linux 2023 and AlmaLinux 9, and distroless) means pip has to come from a virtual environment or a distribution package; `venv=no` (distroless) means `python3 -m venv` does not work either.

### Generate Dependency Tree

Produce two artefacts: the manager-native tree (provenance: who pulls in what) and the **flat pinned list** that §1.3 probes. Per-manager commands are in package-manager-mapping.md §2.

> **Use the project's Python version for this step.** pip resolves for the interpreter that runs it, so run these commands with the project's minor version, not the analysis host's default: create the session-scoped environment from [phase3-validation.md](phase3-validation.md) §3.0 now, as below. Executed on the fixture with the host's default Python 3.12, the first resolution failed with `Failed to build 'pygeos' when getting requirements to build wheel`, because pygeos 0.14 has no cp312 wheel and pip tried to build it just to read its metadata.

The pip form:

```bash
uv venv --seed --python 3.11 "${TMPDIR:-/tmp}/graviton-venv"    # the project's minor version (Phase 3.0); --seed installs pip
. "${TMPDIR:-/tmp}/graviton-venv/bin/activate"
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

Executed on the fixture: 25 pins (11 direct, 14 transitive). `charset-normalizer` appears twice: 3.4.0 from the hash-locked file and 3.5.2 as a transitive of `requests`, and a dry run of the project's second `pip install --prefix` step showed it would install 3.5.2 into the prefix that already held 3.4.0, and the image built natively on Graviton held both `charset_normalizer-3.4.0.dist-info` and `charset_normalizer-3.5.2.dist-info`: `import charset_normalizer` gave 3.5.2 while `importlib.metadata` reported 3.4.0. Both versions are probed (that is the project's behaviour on any architecture, not a Graviton finding). The list includes six transitives of `mkl` (`intel-openmp`, `intel-cmplr-lib-ur`, `tbb`, `tcmlib`, `umf`, `onemkl-license`) that never appear in `requirements.txt`. `pip install --dry-run` and `--report` require pip 22.2 or newer on the analysis host; on x86 the report lists x86 wheels, which is fine: §1.3 re-resolves for aarch64.

> **If `--dry-run` fails** on a hashed file with `Hashes are required in --require-hashes mode`, you passed a hashed and an unhashed file in one call: split them as above. If it fails on `pip install . --dry-run` with `Multiple top-level packages discovered in a flat-layout`, extract `[project].dependencies` with `tomllib` instead (package-manager-mapping.md §2.3).

### Categorize Components by Risk

- **CRITICAL**: committed or vendored `.so` files, in-repo extension modules, `ctypes`/`cffi` loads, Lambda layers with binaries
- **HIGH**: pinned native-wheel dependencies (numpy, pandas, pillow, cryptography, grpcio, torch, ...), hash-locked requirements, conda explicit files
- **MEDIUM**: Dockerfiles, deployment scripts, CI files, architecture detection code
- **LOW**: pure-Python dependencies (`none-any` wheels) and pure-Python application code

## 1.2 Native Library Validation (.so File Analysis)

> **Output: `graviton-validation/02-native-library-report.md`** and **`graviton-validation/raw/site-packages-so-scan.txt`**

Native code reaches a Python deployment in three ways: **wheels** from the index (handled in §1.3 by probing the index, not by scanning), **binaries committed to the repository** (vendored `.so`, Lambda layers, pre-built modules), and **extensions the project builds itself** (`setup.py` `ext_modules`, Cython, Rust, pybind11, CMake). This section covers the last two. All three depend on the target OS as well as the CPU (libc, page size, CPU generation, OS packages; [../document_references/wheel-verification.md](../document_references/wheel-verification.md) §1).

**Preflight:** the scan needs `file`. Without it, `file {} +` prints nothing and an empty `raw/site-packages-so-scan.txt` is indistinguishable from "no binaries found".

```bash
command -v file >/dev/null || echo "WARN: 'file' missing; install it (yum/apt/microdnf install file) before trusting an empty scan"
```

### 1.2.1 Statically Bundled .so Scanning

Scan the project tree for every native file and record the architecture the file itself declares. Decide from the ELF header (the file's first bytes), never from its name, extension or folder: an executable can have no extension, a file named `libfoo-aarch64.so` can hold x86-64 code, and a Lambda layer zip or a vendored `py3-none-any` wheel can carry binaries. The scan opens every file and the members of zip archives. It skips installed environments (directories with `pyvenv.cfg` or `conda-meta`), whose packages are judged by wheel in §1.3 and scanned the same way in Phase 3.1. It needs only Python 3.6 or later, so it also runs where `file` and `readelf` are missing:

```bash
# native_scan DIR: every ELF file under DIR, found by its first bytes (not its name or extension),
# including members of zip archives (Lambda layer zips, vendored wheels, eggs).
# Installed environments (directories with pyvenv.cfg or conda-meta) are skipped: Phase 3 scans them.
native_scan() {
python3 - "$1" <<'EOF'
import collections, io, os, struct, sys, zipfile
ARCH = {3: "i386", 40: "arm", 62: "x86-64", 183: "aarch64", 243: "riscv"}
found = []

def elf(name, h):
    machine = struct.unpack("<H", h[18:20])[0]
    desc = "e_machine %d (%s)" % (machine, ARCH.get(machine, "other"))
    if machine == 183 and h[4] == 2:  # smallest PT_LOAD alignment; 64KB-page targets need 0x10000 or more
        off, n = struct.unpack("<Q", h[32:40])[0], struct.unpack("<H", h[56:58])[0]
        al = [struct.unpack("<Q", h[o + 48:o + 56])[0] for o in range(off, off + 56 * n, 56)
              if o + 56 <= len(h) and struct.unpack("<I", h[o:o + 4])[0] == 1]
        if al:
            desc += ", LOAD align %#x" % min(al)
    found.append((machine, name, desc))

def check(name, h, opener):
    if h[:4] == b"\x7fELF":
        elf(name, h)
    elif h[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(opener()) as z:
                for m in z.infolist():
                    if not m.filename.endswith("/"):
                        with z.open(m) as f:
                            check(name + "!" + m.filename, f.read(4096), lambda m=m: io.BytesIO(z.read(m)))
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
            print("could not open archive:", name)

for root, dirs, files in os.walk(sys.argv[1]):
    dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "graviton-validation")
               and not os.path.exists(os.path.join(root, d, "pyvenv.cfg"))
               and not os.path.isdir(os.path.join(root, d, "conda-meta"))]
    for n in files:
        p = os.path.join(root, n)
        if os.path.isfile(p) and not os.path.islink(p):
            with open(p, "rb") as f:
                check(p, f.read(4096), lambda p=p: p)

for machine, name, desc in sorted(found, key=lambda t: t[1]):
    print("%s: %s" % (name, desc))
print("ELF files by e_machine:", dict(sorted(collections.Counter(m for m, _, _ in found).items())))
for machine, name, desc in sorted(found, key=lambda t: t[1]):
    if machine != 183:
        print("not aarch64:", name)
EOF
}
native_scan . | tee graviton-validation/raw/site-packages-so-scan.txt
```

Executed on the fixture:

```
./vendor/_fixture_ext.cpython-311-x86_64-linux-gnu.so: e_machine 62 (x86-64)
./vendor/libfastsum-x86_64.so: e_machine 62 (x86-64)
ELF files by e_machine: {62: 2}
not aarch64: ./vendor/_fixture_ext.cpython-311-x86_64-linux-gnu.so
not aarch64: ./vendor/libfastsum-x86_64.so
```

Every `not aarch64:` line is a finding (e_machine 183 is aarch64, 62 is x86-64, 3 is 32-bit x86, 40 is 32-bit Arm). An x86-64 file is acceptable only next to an aarch64 build of the same library that this scan confirms and that the code selects on aarch64 (§1.4); a name that says aarch64 is not evidence. Executed on a test tree holding an x86-64 executable with no extension, an x86-64 library named `libfoo-aarch64.so`, a 32-bit x86 library, and x86-64 members of a Lambda layer zip and of a vendored `py3-none-any` wheel: the scan reported all eight non-aarch64 files and the one real aarch64 build. On a project that vendors `selenium-4.48.0-py3-none-any.whl` it reported `...!selenium/webdriver/common/linux/selenium-manager: e_machine 62 (x86-64)`. A CPython extension's filename states the target it was built for (`*.cpython-311-x86_64-linux-gnu.so` for x86_64 Python 3.11, `*.cpython-311-aarch64-linux-gnu.so` for Graviton; see the side-by-side listing in [configuring_your_sut.md](https://github.com/aws/aws-graviton-getting-started/blob/main/perfrunbook/configuring_your_sut.md)); the scan confirms that the content matches.

Lambda layers and vendored `site-packages` also carry package metadata. The scan above already checked their binaries; find them so their pins also get the wheel check of §1.3:

```bash
# Lambda layers and vendored site-packages (python/ at the zip root, *.dist-info directories)
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -type d -name 'python' -o -name '*.dist-info' -o -name '*.egg-info' -o -name 'layer*.zip' \) -print
```

For a Lambda layer or vendored directory, list `*.dist-info` to get `name==version` pins and feed them to §1.3; the repo's [aws-lambda/README.md](https://github.com/aws/aws-graviton-getting-started/blob/main/aws-lambda/README.md) asks for exactly this check of "binaries in dependencies, Lambda layers, and Lambda extensions".
Executed on the fixture: no layers or vendored `site-packages`.

For a target with 64KB pages (§1.1), an aarch64 object must also be linked for 64KB pages: the scan prints each aarch64 file's smallest `LOAD align`, which must be `0x10000` or more (`readelf -lW <file>` shows the same values; they matched for 101 aarch64 files from the fixture's wheels). Executed on Graviton2 with AlmaLinux 8: a library linked with `-z max-page-size=4096` (`0x1000`) failed to load with `ELF load command alignment not page-aligned`; linked with GNU ld's aarch64 default (`0x10000`, binutils 2.41), it loaded. A test library cross-linked both ways reported `LOAD align 0x1000` and `LOAD align 0x10000`.

Then find extensions the project builds and their sources:

```bash
grep -rnE --exclude-dir=.venv --exclude-dir=.git \
  --include=setup.py --include=setup.cfg --include=pyproject.toml --include=CMakeLists.txt --include=meson.build --include=Cargo.toml \
  "ext_modules|Extension\(|cythonize|cffi_modules|pybind11|setuptools-rust|setuptools_rust|maturin|scikit-build|scikit_build|meson-python|mesonpy|cmake" .
find . \( -path ./.venv -o -path ./.git \) -prune -o \
  \( -name '*.pyx' -o -name '*.pxd' -o -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.rs' -o -name 'Cargo.toml' \) -type f -print
```

Executed on the fixture: `setup.py:5: ext = Extension(`, `setup.py:15: ext_modules=[ext]`, sources `native/fastsum.c`, `native/fixture_ext.c`. An extension built from source is not a blocker by itself (it will be compiled on aarch64 in Phase 3); its **flags and headers** are checked in §1.4.

### 1.2.2 Runtime-Extracted Native Library Detection

Some packages and scripts download or unpack native binaries at run, build or deploy time instead of shipping them in a wheel, and packages from the OS arrive outside pip. None of them shows up in the dependency tree.

```bash
# Binary downloads in scripts and Dockerfiles
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.sh' --include='Dockerfile*' --include='Makefile' --include='*.py' \
  "(curl|wget).*(amd64|x86_64|x86-64)|releases/download/.*(amd64|x86_64)" .

# Packages installed from the OS by Dockerfiles and scripts
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='Dockerfile*' --include='*.sh' \
  '(apt-get|apt|dnf|yum|microdnf) install|apk add' .
```

Executed on the fixture: `scripts_deploy.sh:5: curl ... tool-linux-amd64`; no OS packages.

**Common packages that fetch or carry native binaries outside their wheel tags** (this list is a *prompt*, not an allowlist):
- **selenium**: its `py3-none-any` wheel carries Selenium Manager executables. Up to 4.48.0 the only Linux build is an x86-64 executable (`selenium/webdriver/common/linux/selenium-manager`); 4.49.0 is the first release that also carries `linux-arm64/selenium-manager`. On Linux aarch64, 4.48.0 stops before it starts any program, with `WebDriverException: Message: Unsupported platform/architecture combination: linux/aarch64` (its `selenium_manager.py` maps Linux to a binary only for `x86_64`); the bundled file itself, run directly on Graviton, fails with `Exec format error`. 4.50.0 runs the arm64 one
- **pyppeteer**: downloads Chromium on first use from the `Linux_x64` snapshot path on every Linux host (2.0.0), so on Graviton it fetches an x86 browser (executed: `pyppeteer-install` downloaded an x86-64 `chrome` that fails with `Exec format error`)
- **Browser and driver downloaders** (Selenium Manager, webdriver-manager): fetch Chrome for Testing builds at run time. The current Stable release lists `linux-arm64` for Chrome and ChromeDriver (154.0.8037.92), and on Graviton webdriver-manager 4.1.2 downloaded the `linux-arm64` ChromeDriver for that release; check the platform list for the version the project uses
- **duckdb**: downloads extensions for its platform at first use; `linux_arm64` builds are published (on Graviton, duckdb 1.5.6 installed and loaded the `linux_arm64` `httpfs` extension)

**Do not rely on the named list alone.** The authoritative signal is the ELF scan of the installed environment (Phase 3.1), which opens every file and so also reports executables inside `py3-none-any` wheels. Binaries a package downloads to a directory outside `site-packages` need the downloading code read instead.


For each OS package, check that the target's arm64 repository has it. From an x86 host this needs no emulation:

```bash
# Debian or Ubuntu target: read the arm64 package index from an amd64 container (no emulation).
# Enable the repositories the Dockerfile enables (non-free for MKL here).
$CONTAINER_CMD run --rm --init --platform linux/amd64 debian:13 timeout 300 sh -c \
  'sed -i "s/^Components: main$/Components: main non-free/" /etc/apt/sources.list.d/debian.sources &&
   dpkg --add-architecture arm64 && apt-get update -qq >/dev/null &&
   for p in libgeos-dev libmkl-dev; do echo "$p arm64: $(apt-cache policy "$p:arm64" | sed -n "s/^ *Candidate: //p")"; done'
# Amazon Linux 2023 (and other dnf distributions): query the aarch64 repository from an amd64 container.
$CONTAINER_CMD run --rm --init --platform linux/amd64 amazonlinux:2023 timeout 300 sh -c \
  'dnf -q --forcearch=aarch64 repoquery --available --latest-limit 1 --qf "%{name}-%{version}-%{release}.%{arch}" geos-devel python3.11 2>/dev/null'
```

Executed (22 seconds): `libgeos-dev arm64: 3.13.1-1`, `libmkl-dev arm64:` with no candidate, `geos-devel-3.13.0-2.amzn2023.0.1.aarch64` and `python3.11-3.11.16-1.amzn2023.0.1.aarch64`; natively on Graviton, `apt-cache policy` in a Debian 13 `linux/arm64` container gave the same answers. A package with no arm64 candidate is a MUST UPGRADE finding, and its substitute is a user decision (as for `mkl` in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md)).

### 1.2.3 Tiered Validation Policy

**FAIL immediately if:**
- the §1.2.1 scan reports the file as not aarch64 AND confirms no aarch64 build of the same library AND no source in the repository AND the user cannot provide an aarch64 build

**WARN but proceed if:**
- Source is present (the extension or library can be rebuilt on aarch64 in Phase 2.1), OR a pure-Python fallback path exists (for example `fast_sum` falling back to `sum()` when the load fails), OR the binary is an optional accelerator

**PASS if:**
- the scan reports `e_machine 183 (aarch64)`, OR both an x86_64 and an aarch64 build are present (each confirmed by the scan, not by its name) and the code selects the aarch64 one at runtime

For x86-only binaries: locate the source, document the rebuild, or ask the user for an aarch64 build. Validate with:
```bash
file libname.so  # Must show "ARM aarch64"
```

## 1.3 Dependency ARM64 Compatibility Analysis

> **Output: `graviton-validation/03-dependency-compatibility-report.md`** and **`graviton-validation/raw/wheel-availability.txt`**

**IMPORTANT:** ARM64-incompatible native code is introduced through transitive dependencies as often as direct ones. The fixture's `requirements.txt` names `mkl`; the resolved tree adds six Intel-only transitives. Probe the full flat list from §1.1, never just the manifest.

### Generate Filtered Tree

The Python equivalent of a "native-artifact-only tree" is the probe output: one verdict per pin, for the project's interpreter, against the aarch64 platform tags. The probe and its exact flags are defined and demonstrated in [../document_references/wheel-verification.md](../document_references/wheel-verification.md) §3; this is the loop over the resolved list:

```bash
PYVER=3.11; ABI="cp${PYVER/./}"
TARGET_LIBC=glibc; TARGET_LIBC_VER=2.41   # from the target probe in §1.1 (Alpine: TARGET_LIBC=musl TARGET_LIBC_VER=1.2)
platforms() { # $1=arch ; sets PLAT to one --platform flag per wheel tag the target's libc accepts, newest first
  local i="${TARGET_LIBC_VER#*.}"; PLAT=()
  if [ "$TARGET_LIBC" = musl ]; then
    while [ "$i" -ge 1 ]; do PLAT+=(--platform "musllinux_1_${i}_$1"); i=$((i - 1)); done
  else
    while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_$1"); i=$((i - 1)); done
    PLAT+=(--platform "manylinux2014_$1")
  fi
}
probe() { # $1=requirement $2=arch ; prints the wheel filename (rc 0), the from-versions list (rc 1),
          # nothing (rc 3) when an environment marker excluded the pin on this host, or why the index
          # did not answer (rc 4). --no-input and </dev/null: pip never reads the loop's list of pins;
          # --disable-pip-version-check: the only index requests in the log are the probe's.
  local d f; platforms "$2"; d=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
  if python3 -m pip download --no-input --disable-pip-version-check --only-binary=:all: --no-deps -vv -d "$d" "${PLAT[@]}" \
       --python-version "$PYVER" --implementation cp --abi "$ABI" "$1" </dev/null >"$d/log" 2>&1; then
    f=$(ls "$d" | grep '\.whl$' | head -n 1); rm -rf "$d"
    [ -n "$f" ] && { echo "$f"; return 0; }; return 3
  else
    if grep -q 'Could not fetch URL' "$d/log"; then   # 401, 403, 404, connection or TLS error from the index
      grep -m1 'Could not fetch URL' "$d/log" | sed -E 's/^.*Could not fetch URL ([^ ]+): (.*) - skipping$/\2 (\1)/' | cut -c1-160
      rm -rf "$d"; return 4
    fi
    grep -oE 'from versions: [^)]*' "$d/log" | head -n 1; rm -rf "$d"; return 1
  fi
}
sed -E 's/[[:space:]]*#.*//' graviton-validation/raw/requirements-resolved.txt | grep '==' | while read -r req; do
  out=$(probe "$req" aarch64); rc=$?
  if [ $rc -eq 4 ]; then echo "CHECK INDEX     $req  the index did not answer: $out"; continue; fi
  if [ $rc -eq 0 ]; then
    case "$out" in *-none-any.whl) echo "COMPATIBLE      $req  pure Python: $out";; *) echo "COMPATIBLE      $req  aarch64 wheel: $out";; esac
  elif [ $rc -eq 3 ]; then
    echo "CHECK MARKER    $req  skipped: its environment marker does not match this host; judge it for Linux aarch64 by hand"
  elif probe "$req" x86_64 >/dev/null; then
    echo "MUST UPGRADE    $req  x86_64 wheel exists for $ABI, no aarch64 wheel; $out"
  else
    echo "CHECK SDIST/ABI $req  no $ABI wheel for either arch: pure-Python sdist, interpreter ABI mismatch, or a libc older than every wheel (wheel-verification.md sections 5 to 7)"
  fi
done | tee graviton-validation/raw/wheel-availability.txt
```

Set `TARGET_LIBC` and `TARGET_LIBC_VER` from §1.1. `platforms` then offers pip every wheel tag the target's libc accepts, newest first as pip itself prefers them, and nothing above it. pip matches each `--platform` value exactly, so a shorter list misses wheels: executed, `polars==1.0.0`, whose only aarch64 wheel is `manylinux_2_24`, came out `MUST UPGRADE` when only `manylinux2014`, `_2_17`, `_2_28` and `_2_34` were offered, and `COMPATIBLE` with the full list. With `TARGET_LIBC=musl` the loop probes `musllinux` wheels for Alpine targets. A pin whose wheels all need a newer libc than the target's is a MUST UPGRADE finding with the OS or Lambda runtime as the user decision: rerun its aarch64 probe with a higher `TARGET_LIBC_VER` to show that (wheel-verification.md §7).

Run the loop in the same shell as §1.1, so `python3` is the project-version environment. pip evaluates environment markers (`; python_version < "3.12"`, `; platform_machine == "x86_64"`, `; sys_platform == "win32"`) against the interpreter and machine that run it, not against `--python-version` or `--platform`: executed with a Python 3.12 host and `--python-version 3.11`, a pin marked `python_version < "3.12"` was skipped and one marked `python_version >= "3.12"` was downloaded. With the project's interpreter the `python_version` markers resolve correctly; markers on the machine or platform still follow the analysis host, so a `CHECK MARKER` line, or a `MUST UPGRADE` line whose marker names `platform_machine`, needs a manual call for Linux aarch64. Exports from Poetry and uv carry such markers; requirement files from pip usually do not.

Executed on the fixture (25 pins): `MUST UPGRADE` for `blosc2==0.6.3` (with `from versions: 0.6.4, 0.6.5, ...`), `pygeos==0.14`, `mkl==2026.1.0` and its six transitives (`from versions: none`); `CHECK SDIST/ABI` for `docopt==0.6.2`; `COMPATIBLE` for the other 15, including `six==1.11.0` (`py2.py3-none-any`), `numpy==1.26.4` and `charset-normalizer==3.4.0`.

> **Skill config:** when `python.index_url` is set, run the loop twice, with `PIP_INDEX_URL` set to the configured index and then to `https://pypi.org/simple` (the loop has no index option; pip reads the variable). A pin that fails only on the configured index is COMPATIBLE with an **INFRA** note ("mirror lacks the aarch64 wheel"), not a dependency change (wheel-verification.md §9).

Then the hash-lock check for every hashed requirements file the deployment installs:

```bash
platforms aarch64   # the same tag list as the loop above
python3 -m pip install --dry-run --ignore-installed --only-binary=:all: --require-hashes -q "${PLAT[@]}" \
  --python-version "$PYVER" --implementation cp --abi "$ABI" --target /tmp/graviton-probe-target \
  -r requirements-locked.txt
```

Executed on the fixture: `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE ... Expected sha256 b91c0375... Got 6ec585f6...` for MarkupSafe 2.1.5. The pins themselves are COMPATIBLE (both have aarch64 wheels); the **lock file** is the MUST UPGRADE finding. `poetry.lock`, `uv.lock`, `pdm.lock`, `Pipfile.lock` and pip-tools output with `--generate-hashes` carry hashes for every published file and pass this check without changes (package-manager-mapping.md §1).

### Classify Each Dependency

Apply the decision tree in [../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md) to every line of `raw/wheel-availability.txt`:

**MUST UPGRADE (Blocking):** no aarch64 wheel for the pinned version and interpreter where a later version has one (upgrade to the **lowest** such version); no aarch64 wheel in any release and the package is x86-only by nature (substitute, user confirms); hash lock excludes the aarch64 wheel (regenerate); wheel tag exceeds the target glibc (user decision); documented aarch64 correctness bug at this version (NumPy < 1.21.1, SciPy < 1.7.2 per [python.md section 2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#2-scientific-and-numerical-application-numpy-scipy-blas-etc)).

**RECOMMENDED UPGRADE (Non-blocking):** installs and runs on aarch64, and a newer version has a documented Graviton improvement; record it with its source and evidence level and never apply it. Runtime settings go to `05-runtime-configuration.md` (Phase 2.5).

**COMPATIBLE (No action):** aarch64 wheel present, or `none-any` wheel, or pure-Python sdist. Age, CVEs and "newer is faster" do not move a package out of this class.

**CHECK SDIST/ABI lines need one more step before they get a label:** download the sdist and list compiled sources (wheel-verification.md §5); if there are none it is COMPATIBLE. If the package has aarch64 wheels for a *different* `cp` tag (probe again with `--python-version 3.10 --abi cp310`, and x86_64 with the project's tag), it is an interpreter-ABI blocker, reported in its own table and resolved only through the gate in §1.5.

**CHECK INDEX lines are not verdicts:** the index did not answer (credentials, network, or a mirror that lacks the project). Fix access, or probe PyPI as in the skill-config note above, and rerun the loop for those pins; never label a pin from a failed request.

**A pin the decision tree sends to a user decision stays CHECK until the user chooses** (pygeos in [agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md): a source build is COMPATIBLE, a move to `shapely>=2.0` is MUST UPGRADE). The loop's line for it records only the probe result; the report lists it under User Decisions Pending.

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

Executed on the fixture: `scripts_deploy.sh:5` downloads `tool-linux-amd64` from a placeholder host; no aarch64 asset can exist, so it is recorded as a blocker for the user to resolve.

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
  | xargs grep -LE "[\"'](aarch64|arm64)[\"']" 2>/dev/null

# Shell scripts, Makefiles, CI
grep -rnE --exclude-dir=.venv --exclude-dir=.git --include='*.sh' --include=Makefile --include='*.mk' --include='*.y*ml' \
  'uname -m|HOSTTYPE|x86_64|amd64' .

# x86-only compiler flags, intrinsics headers and macros in build files and extension sources
grep -rnE --exclude-dir=.venv --exclude-dir=.git \
  --include=setup.py --include=setup.cfg --include=pyproject.toml --include=CMakeLists.txt --include=meson.build \
  --include='*.c' --include='*.cc' --include='*.cpp' --include='*.h' --include='*.pyx' --include='*.rs' --include=Cargo.toml \
  -- '-m(avx|sse|fma|bmi|popcnt)|-march=|-mtune=|immintrin\.h|xmmintrin\.h|emmintrin\.h|__x86_64__|__SSE|__AVX|_mm[0-9]*_' .

# Dockerfiles and deployment descriptors
grep -nE -- '--platform=|@sha256:|BUILDPLATFORM|TARGETPLATFORM|TARGETARCH|pip install|uv (sync|pip)|poetry install|conda env' Dockerfile*
grep -rniE --exclude-dir=.venv --exclude-dir=.git --include='*.y*ml' --include='*.json' --include='*.tf' \
  'architectures"?[[:space:]]*[:=]|kubernetes\.io/arch|nodeselector|cpu_?architecture"?[[:space:]]*[:=]|ami_?type"?[[:space:]]*[:=]|instance_?types?"?[[:space:]]*[:=]|ami-[0-9a-f]{8,17}|x86_64|amd64' .
```

The descriptor pattern is case-insensitive and allows an optional quote and `:` or `=`, so it catches CloudFormation JSON (`"Architectures": ["x86_64"]`) and YAML, ECS task definitions (`"cpuArchitecture": "X86_64"`) and Terraform (`architectures = ["x86_64"]`, `cpu_architecture`, `ami_type`, `instance_type`). Executed on a Terraform file, a CloudFormation template, an ECS task definition, an eksctl file and a Kubernetes manifest, it matched all 14 architecture-specific lines; on a SAM template, a JSON template and a Kubernetes manifest it matched the `Architectures` and `nodeSelector` lines. Note the `--` before the pattern in the flags and Dockerfile greps: those patterns start with `-`, and without `--` grep reads them as options (`grep: unrecognized option '--platform=...'`). Keep the `--include` flags **before** the `--`, or grep treats them as file names.

Instance types and AMI IDs need arm64 counterparts. A Graviton instance type is a sizing decision: record it for the user. An AMI ID names one architecture: `aws ec2 describe-images --image-ids <id> --query 'Images[].[ImageId,Architecture,Name]'` shows which (executed: `al2023-ami-2023.12.20260930.0-kernel-6.18-x86_64` reports `x86_64` and its `-arm64` sibling `arm64`), and the arm64 AMI of the same release replaces it; the public SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` has an `-arm64` counterpart. ECS `cpuArchitecture` takes `X86_64` or `ARM64` (Fargate defaults to `X86_64`), and EKS `amiType` values come in pairs (`AL2023_x86_64_STANDARD` and `AL2023_ARM_64_STANDARD`). Change these only where the project ships the files ([../document_references/agent-scope-boundaries.md](../document_references/agent-scope-boundaries.md), IN SCOPE 6).

Executed on the fixture:
- `app/service.py:29: return ctypes.CDLL(path)` (the path is chosen by the architecture check below) and `app/service.py:46: ctypes.util.find_library("c")` (harmless: libc resolves everywhere). For each `CDLL`/`dlopen`, read the code that builds the path: a hard-coded x86 filename or a lookup table without an `aarch64` key is a FAIL.
- `app/service.py:19: if arch == "x86_64":` and `:21: if arch == "AMD64":` with no aarch64 branch; `app/service.py` is the only file comparing x86 but never aarch64
- `tests/test_service.py:13: if platform.machine() == "x86_64":` guards the test's only assertion, so on aarch64 the test passes without checking anything. The file mentions `aarch64` on another line, so the heuristic does not list it; only the first grep shows it
- `scripts_deploy.sh:4: if [ "$(uname -m)" != "x86_64" ]; then ... exit 1` and `:5` the `tool-linux-amd64` download
- `setup.py:8: extra_compile_args=["-O3", "-mavx2", "-march=haswell"]`; `native/fixture_ext.c:7-8` includes `<immintrin.h>` under `#ifdef __x86_64__` (guarded, so the header is fine; the flags are not)
- `Dockerfile:6: FROM --platform=$BUILDPLATFORM python:3.11-slim AS builder` whose `RUN pip install` output is copied into `Dockerfile:12: FROM --platform=linux/amd64 python:3.11-slim`

Flag code that checks for `x86_64`/`amd64` without `aarch64`/`arm64` handling, builds library paths or download URLs from the architecture without an aarch64 case, compiles with x86-only flags, or pins container images to amd64. A test whose assertions run only on x86 does not block the migration: record it in `04-code-scan-findings.md` as COMPATIBLE with that note, leave it unchanged, and check the path it would have covered directly in Phase 3.3. One Dockerfile rule needs particular care: **`pip install` must run on the target platform.** Wheels are architecture-specific, so a stage that installs packages and is copied into the runtime image must run on `$TARGETPLATFORM` (Phase 2.4).

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
   (The `-A` user agent matters: devguide.python.org returns 403 to urllib's default agent.) Executed for the fixture: `Python 3.11: status=security, first release 2022-10-24, end of life 2027-10`.
3. CPython itself is not the blocker: the official `python:` images are multi-architecture (the fixture's `python:3.11-slim` ran as `aarch64` in §1.1), and the repo's guidance ([python.md section 1.2](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#12-recommended-versions)) is to target at least 3.11 because older releases are end of life and package maintainers drop their wheels first (section 1.3 describes the AL2 and RHEL 8 cases). An end-of-life interpreter is recorded as a RECOMMENDED UPGRADE with the live date, not as a blocker, unless §1.3 produced interpreter-ABI blockers.
4. **DO NOT change the interpreter version by default.** The gate is `python.interpreter_bump` in `skill-config.md`:
   - `never` (default): report ABI blockers with evidence and options; make no change
   - `ask`: present the blockers and the lowest interpreter that resolves them, and wait for approval
   - `approved=<3.X>`: the team pre-approved that version; apply it as a consequence of the required fix and record it in `01-project-assessment.md` and `00-summary.md`
   A bump is only in scope when it is the sole path to an aarch64 wheel for a required package; "3.10 is end of life" alone never justifies it.

   **One interpreter for the whole dependency set.** The interpreter is one decision covering every pin, never made for one package at a time, because a bump made for one package changes the wheel every other pin needs. Before proposing or applying a bump, rerun the §1.3 loop for each candidate interpreter over the whole resolved list (`PYVER=3.Y`, run in a 3.Y environment from Phase 3.0), and record for each candidate which pins are not COMPATIBLE and the lowest versions that fix them (03 report, Interpreter-ABI Blockers). Keep the current interpreter when every MUST UPGRADE finding is fixable there; otherwise choose the lowest candidate at which every pin is, and apply the bump and all of its pin changes together. When no single interpreter works for every pin, report the table as a user decision and change nothing. Executed on the fixed fixture: at cp312 the two pins fixed for cp311, `blosc2==0.6.4` and `shapely==2.0.0`, have no wheel on either architecture (the lowest cp312 aarch64 releases are 2.2.8 and 2.0.2), so a move to 3.12 would be three changes decided together, not one.
5. Record `pip` on the target (§1.1): pip 19.3 is the first release that installs `manylinux2014` aarch64 wheels ([README, Python installation on some Linux distros](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md#python-installation-on-some-linux-distros)), and pip 20.3 the first that sees the `manylinux_2_N` tags most current aarch64 wheels carry ([../document_references/wheel-verification.md](../document_references/wheel-verification.md) §2); plan the upgrade in Phase 3 if it is older than 20.3.
