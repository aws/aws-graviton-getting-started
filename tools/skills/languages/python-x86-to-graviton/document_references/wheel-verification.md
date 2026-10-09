# Wheel Verification: Proving aarch64 Availability

This is the evidence standard for every dependency verdict in this skill:

> **Verify the wheel on PyPI, never the version number.** Whether a pinned version installs on Graviton is a fact about the files published for that exact version, interpreter, and glibc, not something a version number or release date can tell you.

Every version floor quoted in this skill was verified against PyPI on the date stated. Re-run the probe at migration time rather than trusting a table: maintainers add wheels (and occasionally drop them) between skill releases.

## 1. Why Wheels Are the Central Graviton Problem

`pip install` prefers a binary wheel whose tags match the target interpreter and platform. When no wheel matches, pip silently falls back to the source distribution (sdist) and compiles it. On Graviton that fallback is where migrations break:

- The sdist build needs compilers and headers that the image does not have, and fails.
- The build succeeds but takes minutes (the repo's [python.md](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md) section 1 notes up to 20 minutes for large packages), which breaks container build budgets and autoscaling.
- The build succeeds but yields a slower, untested binary than the maintainer's wheel.
- A hash-locked requirements file (`--require-hashes`) rejects the sdist or the aarch64 wheel outright because the lock only carries x86_64 hashes.

**Pure Python and native code.** Pure-Python code (a `py3-none-any` wheel, or an sdist with no compiled sources) is the same on every operating system and CPU, so it is COMPATIBLE unless it reaches native code itself: a `ctypes` or `cffi` load, a binary it runs or downloads, or a branch on `platform.machine()` (Phase 1.2 and 1.4 find those). Native code (compiled extension modules in wheels, sdists that compile, vendored `.so` files, executables shipped inside wheels, packages from the OS) depends on the target in six ways, and wheel tags record three of them:

| Native code depends on | Recorded in the wheel tags | Where the skill checks it |
|---|---|---|
| CPU architecture | yes (`aarch64`) | the probe (section 3) |
| Python ABI | yes (`cp311`, `abi3`) | the probe, run for the project's interpreter (section 6) |
| libc family and minimum version | yes (`manylinux_2_N` for glibc, `musllinux_1_N` for musl) | the probe, limited to the target's libc (Phase 1.1, section 7) |
| Kernel page size | no | Phase 1.1 (the deployment hosts) and Phase 3 (a validation host with the same page size) |
| CPU generation and features | no | Phase 2.5 (build flags) and Phase 3 (the oldest Graviton generation deployed) |
| Packages from the OS | no | Phase 1.2.2 (the target's arm64 repository) and the Phase 3 image build |

The last three fail on Graviton even when every wheel is tagged for aarch64. Executed on Graviton: polars 0.15.1 aborted at import with `<jemalloc>: Unsupported system page size` on AlmaLinux 8 (64KB pages) and imported on AlmaLinux 9 (4KB pages); a test library built with SVE instructions ran on Graviton3 and Graviton4 and stopped with `Illegal instruction` on Graviton2; Debian 13's arm64 repository has `libgeos-dev` but no `libmkl-dev`.

The skill therefore classifies every pinned dependency by **which files exist on the index for that exact pin**, using the probes below, before any ARM64 hardware is involved.

## 2. Tag Vocabulary (What the Probe Matches Against)

A wheel filename is `{name}-{version}-{python tag}-{abi tag}-{platform tag}.whl`. The three tags that decide a Graviton install:

| Tag | Graviton-relevant values | Meaning |
|---|---|---|
| python / abi | `cp311-cp311`, `cp312-cp312`, ... or `cp38-abi3` (stable ABI) | Must match the project's interpreter. A package can ship aarch64 wheels for cp310 but not cp311: that is an interpreter problem, not an architecture problem (see section 6). |
| platform | `manylinux2014_aarch64`, `manylinux_2_17_aarch64`, `manylinux_2_24_aarch64`, `manylinux_2_28_aarch64`, `manylinux_2_34_aarch64`, `musllinux_1_2_aarch64` | Linux ARM64. `manylinux2014_aarch64` and `manylinux_2_17_aarch64` are the same thing (see aliases). `musllinux` is for musl-based images (Alpine) only. pip matches each `--platform` value exactly, so a probe must offer every tag the target accepts (section 3). |
| platform (pure Python) | `py3-none-any`, `py2.py3-none-any` | No native code; installs on every architecture. Always COMPATIBLE. |

Legacy manylinux aliases, from [PEP 600](https://peps.python.org/pep-0600/): `manylinux1` = `manylinux_2_5`, `manylinux2010` = `manylinux_2_12`, `manylinux2014` = `manylinux_2_17`. Only `manylinux2014` and later have aarch64 variants; `manylinux1`/`manylinux2010` are x86 only.

pip version floors (from [pip's changelog](https://pip.pypa.io/en/stable/news/)): `manylinux2014` tags were added in **pip 19.3** (2019-10-14), which is why the repo's [python.md](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md) and [README](https://github.com/aws/aws-graviton-getting-started/blob/main/README.md#python-installation-on-some-linux-distros) require pip > 19.3 on Graviton; perennial `manylinux_2_N` tags (PEP 600) were added in **pip 20.3** (2020-11-30). An older pip on the target cannot see aarch64 wheels at all and will build everything from source. Check `python3 -m pip --version` on the target before interpreting any install failure, and upgrade with `python3 -m pip install --upgrade pip` (the repo's documented workaround). Current aarch64 wheels mostly carry `manylinux_2_N` tags only (numpy 2.5.3, pillow 12.3.0 and torch 2.14.1 publish no `manylinux2014` aarch64 wheel), so pip 20.3 is the floor that matters. Executed on an x86_64 host with Python 3.8 (pip applies the same tag rules on aarch64): pip 19.3.1 and 20.2.4 found no `confluent-kafka==2.5.0`, whose cp38 x86_64 wheel is tagged `manylinux_2_28` only, and pip 20.3 downloaded it.

## 3. The Probe: `pip download` Against the aarch64 Platform

This runs on any host (x86 laptops and CI included) because `pip download` with explicit platform flags never executes code from the package. It asks the index: "for this exact pin, Python X.Y, CPython ABI, and these Linux ARM64 platform tags, is there a binary wheel?"

```bash
# The target's libc from Phase 1.1 (Amazon Linux 2023: glibc 2.34; Alpine: TARGET_LIBC=musl TARGET_LIBC_VER=1.2)
TARGET_LIBC=glibc; TARGET_LIBC_VER=2.34
# pip matches each --platform value exactly: offer every tag the target's libc accepts, newest first
platforms() { # $1=arch ; sets PLAT
  local i="${TARGET_LIBC_VER#*.}"; PLAT=()
  if [ "$TARGET_LIBC" = musl ]; then
    while [ "$i" -ge 1 ]; do PLAT+=(--platform "musllinux_1_${i}_$1"); i=$((i - 1)); done
  else
    while [ "$i" -ge 17 ]; do PLAT+=(--platform "manylinux_2_${i}_$1"); i=$((i - 1)); done
    PLAT+=(--platform "manylinux2014_$1")
  fi
}
# Usage: probe <requirement> <arch>; prints the wheel filename on success.
# --only-binary=:all: is mandatory: without it pip accepts the sdist and the
# probe "passes" for a package that has no aarch64 wheel at all (false PASS).
# --no-input and </dev/null: pip never prompts, so it cannot consume the caller's input (a loop's list of pins).
# -vv logs every index request. pip skips an index whose request fails and decides from the others: a 403
# or 404 means that index does not have the project, and the verdict stands with a note naming the index.
# Any other failure (401, a server error, no connection, TLS), or a project that no index has, is reported
# as CHECK INDEX (return code 4) instead of reading like a missing wheel. --disable-pip-version-check keeps
# pip's own update check out of the log, so a failed request is always the probe's.
probe() {
  local req="$1" arch="$2" pyver="${PYVER:-3.11}" d miss
  platforms "$arch"; d=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
  if python3 -m pip download --no-input --disable-pip-version-check --only-binary=:all: --no-deps -vv -d "$d" "${PLAT[@]}" \
       --python-version "$pyver" --implementation cp --abi "cp${pyver/./}" \
       "$req" </dev/null >"$d/log" 2>&1; then
    ls "$d" | grep '\.whl$' || echo "nothing downloaded: an environment marker excluded the pin on this host (section 10)"
    rm -rf "$d"; return 0
  fi
  miss=$(sed -nE 's/^.*Could not fetch URL ([^ ]+): (40[34]) Client Error.*$/\1 (\2)/p' "$d/log" | awk 'NR > 1 {printf ", "} {printf "%s", $0}')
  if grep 'Could not fetch URL' "$d/log" | grep -qvE ': 40[34] Client Error'; then
    echo "CHECK INDEX: an index did not answer: $(grep 'Could not fetch URL' "$d/log" | grep -vE ': 40[34] Client Error' | head -n 1 | sed -E 's/^.*Could not fetch URL ([^ ]+): (.*) - skipping$/\2 (\1)/' | cut -c1-160)"
    rm -rf "$d"; return 4
  elif ! grep -q 'Fetched page' "$d/log"; then
    echo "CHECK INDEX: no index has the project: ${miss:-no index was searched}"
    rm -rf "$d"; return 4
  fi
  grep -E 'from versions|No matching' "$d/log" | head -n 2
  [ -z "$miss" ] || echo "not on $miss"
  rm -rf "$d"; return 1
}
```

Executed results (pip 26.2.1, `PYVER=3.11`, glibc 2.34):

| Call | Result | Reading |
|---|---|---|
| `probe numpy==1.26.4 aarch64` | `numpy-1.26.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl` | COMPATIBLE |
| `probe requests==2.32.3 aarch64` | `requests-2.32.3-py3-none-any.whl` | COMPATIBLE (pure Python) |
| `probe blosc2==0.6.3 aarch64` | `Could not find a version that satisfies the requirement blosc2==0.6.3 (from versions: 0.6.4, 0.6.5, 0.6.6, 2.0.0, ...)` | No aarch64 wheel at the pin; **the `from versions:` list enumerates every version that does have a matching aarch64 wheel**. Lowest is 0.6.4: that is the minimal fix. |
| `probe blosc2==0.6.3 x86_64` | `blosc2-0.6.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | Confirms the pin is x86-only, so the failure above is architectural, not an ABI or spelling problem. |
| `probe mkl==2026.1.0 aarch64` | `(from versions: none)` | No version of this package has an aarch64 wheel for cp311. Check the full files list (section 4) before concluding "x86-only by nature". |
| `probe pygeos==0.14 aarch64` | `(from versions: none)` | Same text as mkl, different cause: pygeos published aarch64 wheels up to 0.13 and dropped them in 0.14, and 0.13 has no cp311 wheel on any platform. See section 6. |
| `probe docopt==0.6.2 aarch64` | `(from versions: none)` | Also fails for x86_64: the package ships an sdist only. Inspect the sdist (section 5) before labelling it. It is pure Python and COMPATIBLE. |
| `probe polars==1.0.0 aarch64` | `polars-1.0.0-cp38-abi3-manylinux_2_24_aarch64.whl` | COMPATIBLE. A probe that offers only `manylinux2014`, `_2_17`, `_2_28` and `_2_34` misses this `_2_24` wheel and reports `from versions: 0.14.8, ...` while the x86_64 probe passes: a false MUST UPGRADE. |
| `probe numpy==1.26.4 aarch64` with `PIP_INDEX_URL` set to an index that answers 401 | `CHECK INDEX: an index did not answer: 401 Client Error: Unauthorized for url: <index>/numpy/ (<index>/numpy/)` (return code 4) | Not a verdict: the index refused the request. Without `-vv` the same failure reads `from versions: none`, like a missing wheel; with no `--no-input` pip prompts for a user name and reads it from the caller's input. Fix access to the index (section 9) and probe again. |
| `probe blosc2==0.6.3 aarch64` with `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu` | `(from versions: 0.6.4, 0.6.5, ...)`, then `not on https://download.pytorch.org/whl/cpu/blosc2/ (403)` (return code 1) | The verdict PyPI alone gives: that index answers 403 for a project it does not carry, and pip used PyPI's files. `docopt==0.6.2` gave `from versions: none` the same way, and an extra index that answers 404 gave the same results (section 9). |
| `probe graviton-skill-review-no-such-project==1.0 aarch64`, a project on no index | `CHECK INDEX: no index has the project: https://pypi.org/simple/graviton-skill-review-no-such-project/ (404)` (return code 4) | Not a verdict: check the name and which index carries the project. |

The three distinct meanings of a FAIL are why the probe is always run twice (aarch64, then x86_64 with the same ABI):

| aarch64 | x86_64 | Verdict |
|---|---|---|
| PASS | any | COMPATIBLE |
| FAIL with `from versions: <list>` | PASS | MUST UPGRADE to the **lowest** listed version (then confirm it with another PASS) |
| FAIL `from versions: none` | PASS | Either x86-only by nature (section 4) or aarch64 dropped in later releases (pygeos case): decide from the full files list |
| FAIL | FAIL | Not an architecture finding: sdist-only package (section 5) or interpreter ABI mismatch (section 6) |
| CHECK INDEX | any | No verdict: an index that may have the wheel did not answer (credentials, network, a server error), or no index has the project. Fix access or the index settings and probe again (section 9) |

Transitive dependencies get the same treatment, but you do not need to enumerate them by hand. `pip install --dry-run --report` resolves the whole tree for the target platform:

```bash
platforms aarch64   # the function above: one --platform per tag the target's libc accepts
python3 -m pip install --dry-run --ignore-installed --only-binary=:all: \
  --report graviton-validation/raw/wheel-availability.json -q "${PLAT[@]}" \
  --python-version 3.11 --implementation cp --abi cp311 \
  --target /tmp/graviton-probe-target -r graviton-validation/raw/requirements-resolved.txt
```

Executed on three direct pins (numpy, requests, pandas) this produced a `version: 1` report with 11 entries; each `install[].download_info.url` ends in the wheel filename that would be used on aarch64, and `install[].requested` is `true` for direct dependencies and `false` for transitives (`charset_normalizer-3.5.2-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl` was pulled in by requests, for example). If the resolution fails, pip names the first package without an aarch64 wheel; fix or exclude it and re-run until the report completes, recording each failure as you go.

## 4. The Files List: PyPI JSON API

When the probe says `from versions: none`, or you need to establish a floor, read the index directly. No pip involved, stdlib only:

```bash
# All files for one version (replace project and version):
curl -sS --fail "https://pypi.org/pypi/pygeos/0.14/json" \
  | python3 -c "import sys,json; [print(f['filename']) for f in json.load(sys.stdin)['urls']]"

# All releases, flagging which have a Linux aarch64 wheel and for which cp tags:
curl -sS --fail "https://pypi.org/pypi/blosc2/json" | python3 -c '
import sys, json, re
d = json.load(sys.stdin)
for v, files in d["releases"].items():
    tags = sorted({re.search(r"-(cp\d+|py\d)", f["filename"]).group(1)
                   for f in files if "linux" in f["filename"] and "aarch64" in f["filename"]
                   and re.search(r"-(cp\d+|py\d)", f["filename"])})
    print(v.ljust(12), "aarch64:", ",".join(tags) or "-")'
```

Rules for reading the output:

- **Make a missing version fail loudly.** `curl` without `--fail` saves the 404 body, and the Python step then prints nothing, which is indistinguishable from "no aarch64 wheel". Executed check: `curl -sS --fail https://pypi.org/pypi/pygeos/0.99/json` exits 22 with HTTP 404. Keep `--fail` and check the exit status before reading an empty list as evidence.
- **The floor is the lowest version with a wheel for the project's ABI, not the lowest with any aarch64 wheel.** numpy's first aarch64 wheel is 1.19.0 (cp36, cp37, cp38), but the lowest numpy with a cp311 aarch64 wheel is 1.23.2. Quoting 1.19.0 to a Python 3.11 project is wrong.
- **Availability is not monotonic.** blosc2 shipped aarch64 wheels for 0.2.0 and 0.3.0, none from 0.3.1 through 0.6.3, and resumed at 0.6.4. pygeos shipped them through 0.13 and dropped them at 0.14. Always check the exact pinned version.
- **"x86-only by nature" needs the whole release history.** mkl, intel-openmp, tensorflow-intel and tfx-bsl have no Linux aarch64 file in any release (tfx-bsl 1.21.0 ships macOS arm64 wheels, which do not help Graviton). That is the evidence for a substitution verdict; `from versions: none` alone is not.

Verified floors for packages this repo documents (source: `https://pypi.org/pypi/<project>/json`; column 3 is the first release with any Linux aarch64 wheel; re-verify before relying on them):

| Package | Repo reference | First aarch64 wheel | Evidence file |
|---|---|---|---|
| numpy | [python.md](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md) section 2: "NumPy>=1.19.0 vend binary wheel packages for Aarch64"; correctness floor 1.21.1 | 1.19.0 (cp36-cp38); cp311 from 1.23.2 | `numpy-1.19.0-cp36-cp36m-manylinux2014_aarch64.whl` |
| scipy | python.md section 2: "SciPy>=1.5.3"; correctness floor 1.7.2 | 1.5.3 (cp36-cp38) | `scipy-1.5.3-cp36-cp36m-manylinux2014_aarch64.whl` |
| sentencepiece | python.md section 3.4 | 0.1.94 | `sentencepiece-0.1.94-cp35-cp35m-manylinux2014_aarch64.whl` |
| torch | [pytorch.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/pytorch.md) | 1.8.0 | `torch-1.8.0-cp36-cp36m-manylinux2014_aarch64.whl` |
| torchaudio | pytorch.md | 0.10.0 | `torchaudio-0.10.0-cp36-cp36m-manylinux2014_aarch64.whl` |
| tensorflow | [tensorflow.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/tensorflow.md) | 2.10.0 | `tensorflow-2.10.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl` |
| onnxruntime | [onnx.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/onnx.md) | 1.3.0 | `onnxruntime-1.3.0-cp35-cp35m-manylinux2014_aarch64.whl` |
| confluent-kafka | python.md section 4 | 2.1.0, but `manylinux_2_28_aarch64` only (glibc >= 2.28; see section 7) | `confluent_kafka-2.1.0-cp310-cp310-manylinux_2_28_aarch64.whl` |
| open3d | python.md section 4: glibc >= 2.27 | 0.14.1 | `open3d-0.14.1-cp36-cp36m-manylinux2014_aarch64.whl` |
| vllm | [vllm.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/vllm.md) points to the AWS vLLM Deep Learning Container image for Graviton (`vllm-arm64` on the Amazon ECR Public Gallery) and describes a source build | PyPI has aarch64 wheels from 0.10.2 (`cp38-abi3`), but they are CUDA builds (0.10.2's `_C.abi3.so` links `libcudart.so.12` and `libcuda.so.1`; 0.30.0's `_C_stable_libtorch.abi3.so` links `libcudart.so.13` and `libcuda.so.1`); the CPU build is the `+cpu` wheel attached to the vLLM release | `vllm-0.29.0+cpu-cp38-abi3-manylinux_2_34_aarch64.whl` (ran on Graviton); 0.30.0's is `manylinux_2_39` |
| llama-cpp-python | [llama.cpp.md](https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/llama.cpp.md) source build | none (sdist only); source build remains the path | sdist |
| pandas | wheel tester | 1.1.3; cp311 from 1.5.0 | `pandas-1.1.3-cp36-cp36m-manylinux2014_aarch64.whl` |
| pillow | wheel tester | 7.2.0; cp311 from 9.2.0 | `Pillow-7.2.0-cp35-cp35m-manylinux2014_aarch64.whl` |

The repo's [arm64 Python wheel tester](https://geoffreyblake.github.io/arm64-python-wheel-tester/) (linked from python.md) installs and imports about 230 popular packages daily on AL2, AL2023, Ubuntu 20.04/22.04/24.04 and conda, on real Graviton hardware. Use it as a cross-check for *runtime* breakage that a files list cannot show (a wheel that exists but fails to import), not as a substitute for the per-pin probe: it tests the latest version, not your pin.

## 5. Sdist-Only Packages: Inspect Before Labelling

A FAIL on both architectures usually means the project publishes no wheels at all. That is a Graviton finding only if the sdist contains native code.

Read the sdist from the files list (section 4) and list its members. Do not use `pip download --no-binary=:all:` for this: pip prepares the sdist's metadata, which runs its build backend (`setup.py` or the `pyproject.toml` backend), and on an interpreter without setuptools it stops with `BackendUnavailable`.

```bash
# Lists the files of one release's sdist (replace project and version); nothing is built or run.
curl -sS --fail "https://pypi.org/pypi/docopt/0.6.2/json" | python3 -c '
import io, json, sys, tarfile, urllib.request, zipfile
sd = [u for u in json.load(sys.stdin)["urls"] if u["packagetype"] == "sdist"]
if not sd:
    sys.exit("no sdist for this release")
data = urllib.request.urlopen(sd[0]["url"], timeout=120).read()
names = (zipfile.ZipFile(io.BytesIO(data)).namelist() if sd[0]["filename"].endswith(".zip")
         else tarfile.open(fileobj=io.BytesIO(data)).getnames())
native = [n for n in names if n.rsplit(".", 1)[-1] in ("c", "cc", "cpp", "cxx", "h", "hpp", "pyx", "pxd", "rs", "f", "f90")]
print("%s: %d files" % (sd[0]["filename"], len(names)))
print("native sources: %s; needs the build prerequisites from python.md section 1.1 on aarch64" % ", ".join(native[:10])
      if native else "pure Python sdist: COMPATIBLE, installs anywhere")'
```

Executed with Python 3.12 and no setuptools installed: docopt 0.6.2 (32 files) has no C, C++, Cython, Rust or Fortran sources, so its verdict is COMPATIBLE; pygeos 0.14 (68 files) lists `pygeos-0.14/pygeos/_geometry.pyx`, `.pxd` files and `pygeos-0.14/src/c_api.c`. Do not write "no wheel available" as a finding for a pure-Python sdist; the wheel tester marks these as "build required" and passing. For a package published only on a private index, download its sdist from that index with the index's credentials and list it with `tar tzf` (or `unzip -l`); do not `pip download` it.

When the sdist does contain native code, the finding is COMPATIBLE-with-build-prerequisites if it compiles on aarch64 (document the toolchain from [python.md section 1.1](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#11-prerequisites-for-installing-python-packages-from-source): `"@Development tools" python3-devel` on AL/RHEL, `build-essential python3-dev` on Debian/Ubuntu, plus whatever headers the package needs) and MUST UPGRADE if the sources themselves are x86-only (intrinsics, inline assembly; see phase 1.4).

## 6. Interpreter ABI Mismatches Are Not Architecture Findings

Executed: `pygeos==0.13` FAILS the aarch64 probe for cp311, PASSES for cp310 (`pygeos-0.13-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`), and also FAILS for x86_64 cp311. The package has aarch64 wheels; it simply predates Python 3.11. Record this as:

> `pygeos==0.13`: aarch64 wheels exist for cp36-cp310 but the project runs Python 3.11, for which no wheel exists on any platform. Blocker is the interpreter/package combination, not Graviton.

Resolution follows the interpreter policy in [skill-configuration.md](skill-configuration.md) (`python.interpreter_bump`): by default the skill never changes the interpreter; it reports the blocker with this evidence and the options (newer package version that ships the needed cp tag, sdist build, or an approved interpreter change). An interpreter change is one decision for the whole dependency set, never made for one package at a time (Phase 1.5).

A quick way to separate the two causes: run the probe for x86_64 with the project's ABI. If x86_64 also fails, it is ABI or sdist; if x86_64 passes, it is architecture.

## 7. glibc: The Wheel Exists but Will Not Install on the Target OS

Each `manylinux_2_N` tag promises compatibility with glibc >= 2.N. pip on the target only accepts tags its glibc satisfies, and rejects the rest with the **same error text as a missing wheel**. Executed on an AL2 arm64 container (glibc 2.26, Python 3.7, pip 24.0): `pip debug --verbose` lists `manylinux_2_26_aarch64` as the highest accepted tag, and `pip download --only-binary=:all: confluent-kafka==2.1.0` (whose cp37 wheel is `manylinux_2_28_aarch64`) fails with `(from versions: none)`. Without a platform check that would be misread as "no aarch64 wheel".

Distribution and runtime glibc versions, measured inside `linux/arm64` containers of the current image tags (`ldd --version`, and the Phase 1.1 probe natively on Graviton4):

| Image | glibc | Highest wheel tag it accepts |
|---|---|---|
| Amazon Linux 2 | 2.26 | `manylinux_2_26` (so `manylinux2014`/`_2_17` yes, `_2_28` no) |
| Amazon Linux 2023 | 2.34 | `manylinux_2_34` |
| Ubuntu 20.04 | 2.31 | `manylinux_2_31` |
| Ubuntu 22.04 | 2.35 | `manylinux_2_35` |
| Ubuntu 24.04 | 2.39 | `manylinux_2_39` |
| Debian 12 | 2.36 | `manylinux_2_36` |
| `python:3.11-slim` (Debian 13) | 2.41 | `manylinux_2_41` |
| AlmaLinux 8, `ubi8/python-311` | 2.28 | `manylinux_2_28` |
| AlmaLinux 9, `ubi9/python-311` | 2.34 | `manylinux_2_34` |
| `gcr.io/distroless/python3-debian12` | 2.36 | `manylinux_2_36` |
| Lambda `python3.10`, `python3.11` (Amazon Linux 2; `public.ecr.aws/lambda/python:3.11`) | 2.26 | `manylinux_2_26` |
| Lambda `python3.12` and later (Amazon Linux 2023; `public.ecr.aws/lambda/python:3.12`, `:3.13`) | 2.34 | `manylinux_2_34` |
| `python:3.11-alpine` | none (musl 1.2) | `musllinux_1_2`; no `manylinux` wheel installs |

The repo documents the symptom for the opposite order of events (a wheel that installs but fails at import with `ImportError: /lib64/libm.so.6: version 'GLIBC_2.27' not found`) in [python.md "Python wheel glibc requirements"](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#python-wheel-glibc-requirements) and for open3d in section 4. Both are the same finding: the wheel's glibc requirement exceeds the target OS. Options, in the repo's order: a version of the package whose wheel tag the OS accepts, the distro's own package (`yum install python3-<name>`), or a newer OS (AL2023, Ubuntu 22.04 or later). Record it as MUST UPGRADE with "user decision" because changing the OS is outside the skill's scope.

To probe for a specific target OS, set `TARGET_LIBC_VER` to its glibc (2.26 for AL2): section 3's `platforms` then offers `manylinux_2_26` down to `manylinux_2_17` and `manylinux2014`, and nothing higher. Read the target's libc in Phase 1.1 and confirm with `pip debug --verbose` on the target in Phase 3. A Lambda function's runtime sets its OS (Phase 1.1): executed on `arm64` functions, a confluent-kafka 2.15.1 layer built from its `manylinux_2_28_aarch64` wheel imported on `python3.12` and failed on `python3.11` with `ImportError: /lib64/libpthread.so.0: version 'GLIBC_2.28' not found`; with `TARGET_LIBC_VER=2.26` the Phase 1.3 loop finds no cp311 wheel for that pin on either architecture, and labels `confluent-kafka==2.0.2` (a `manylinux2014` x86_64 wheel) `MUST UPGRADE` with `from versions: none`.

**musl (Alpine).** A musl-based image accepts only `musllinux` wheels: set `TARGET_LIBC=musl` and `TARGET_LIBC_VER=1.2` (from the Phase 1.1 probe). Executed for the fixture's pins, inside `python:3.11-alpine` natively on Graviton and with the probe: numpy 1.26.4, pandas 2.2.2, pillow 10.4.0, msgpack 1.2.3, MarkupSafe 2.1.5 and charset-normalizer 3.4.0 have `musllinux` aarch64 wheels; blosc2 0.6.4, shapely 2.0.0 and confluent-kafka 2.15.1, which all have `manylinux` aarch64 wheels, have no `musllinux` wheel for either architecture, so on Alpine they build from source on x86 as well (an sdist build to validate on aarch64 hardware, not an architecture gap).

## 8. Hash-Locked Requirements Only Cover the Wheels They Were Generated From

`pip-compile --generate-hashes`, `pip hash`, and lock exporters record hashes of specific files. A lock generated on an x86 CI runner from `pip download` output carries x86_64 wheel hashes only; on Graviton pip downloads the aarch64 wheel, whose hash differs, and `--require-hashes` aborts.

Executed (pip 26.2.1): a requirements file pinning `numpy==1.26.4` with only the x86_64 wheel hash (`sha256:666dbfb6...`), installed with `--require-hashes` against the aarch64 platform, fails with:

```
ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE. ...
    Expected sha256 666dbfb6ec68962c033a450943ded891bed2d54e6755e35e5835d63f4f6931d5
         Got        7ab55401287bfec946ced39700c053796e7cc0e3acbef09993a9ad2adba6ca6e
```

Adding the aarch64 wheel's hash as a second `--hash=` on the same line makes the install pass. Detect the condition statically:

```bash
# Any hashed requirement that resolves to a different file on aarch64 fails this dry run:
platforms aarch64   # section 3: one --platform per tag the target's libc accepts
python3 -m pip install --dry-run --ignore-installed --only-binary=:all: --require-hashes -q "${PLAT[@]}" \
  --python-version 3.11 --implementation cp --abi cp311 --target /tmp/graviton-probe-target \
  -r requirements-locked.txt
```

Fix per manager (details in [package-manager-mapping.md](package-manager-mapping.md)): `pip-compile --generate-hashes` records hashes for **all** published files of each version, so a lock produced that way already contains the aarch64 hashes; a hand-made lock needs `pip hash` of the aarch64 wheel appended; `poetry.lock` and `uv.lock` are cross-platform and already carry every wheel's hash (verified on the fixture: both locks list `*_aarch64.whl` entries), so they only need regenerating if they predate the aarch64 wheel. A hash lock is also tied to the interpreter version: under Python 3.12, the fixture's lock (x86_64 and aarch64 hashes for the cp311 wheels) failed with `Expected sha256 6ec585f6... or b91c0375... Got ac07bad8...`, because pip downloaded the cp312 wheel.

## 9. Private Indexes and Mirrors

The 2024 Python Developers Survey reports about one in ten developers installing from a private index or an internal PyPI mirror. A mirror that was populated from x86 builds will fail the probe for packages PyPI serves fine. Run the probe twice when `skill-config.md` sets `python.index_url` (or `PIP_INDEX_URL`/`pip.conf` points somewhere other than PyPI): once with `PIP_INDEX_URL=<mirror>` and once with `PIP_INDEX_URL=https://pypi.org/simple` (pip reads the variable, and an explicit PyPI URL overrides a `pip.conf` that points at the mirror). Executed with a local index that carried only the x86_64 numpy 1.26.4 wheel: the Phase 1.3 loop reported `MUST UPGRADE numpy==1.26.4 ... x86_64 wheel exists for cp311, no aarch64 wheel` against it and `COMPATIBLE` against PyPI. If the mirror fails and PyPI passes, the dependency is COMPATIBLE and the finding is **INFRA**: "mirror lacks the aarch64 wheel for X; populate the mirror or allow PyPI fallback". Never upgrade a package to work around a mirror gap.

An extra index (`PIP_EXTRA_INDEX_URL`, `extra-index-url` in `pip.conf`, or `python.extra_index_url` in `skill-config.md`) is asked for every pin, and most extra indexes carry only a few projects. pip skips an index that answers 403 or 404 for a project page and uses the others, so the probe keeps that verdict and adds `not on <url> (403)`. Executed with `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu`, which answers 403 for projects it does not carry, the Phase 1.3 loop gave the fixture's pins the same verdicts as with PyPI alone. A 403 or 404 can also come from an index the probe may not read: 403 means the server refuses the request, and [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110#section-15.5.4) lets a server answer 404 instead to hide a resource. When the note names a private index that should carry the package (an internal package, or an aarch64 wheel built in-house), check that the probe can read that index: probe a pin it carries with `PIP_INDEX_URL` set to that index alone.

## 10. False-Verdict Traps (Checklist)

| Trap | What you see | Correct handling |
|---|---|---|
| `--only-binary=:all:` omitted | probe PASSES by downloading the sdist | Always include it; the probe is about wheels |
| Wrong `--abi`/`--python-version` | FAIL for a package that has aarch64 wheels | Use the project's interpreter (phase 1.1), then cross-check x86_64 with the same ABI |
| Target OS glibc below the wheel tag | `from versions: none` on the target, PASS in the probe | Probe with the target's glibc tag set (section 7); confirm with `pip debug --verbose` on the target |
| Old pip on the target (< 19.3, or < 20.3 for `manylinux_2_N`) | every native package builds from source on Graviton | Upgrade pip first ([python.md section 1](https://github.com/aws/aws-graviton-getting-started/blob/main/python.md#1-installing-python-packages)) |
| `curl` without `--fail` | empty files list for a typo or unpublished version | Check the exit status; a 404 is not evidence |
| Reading the first aarch64 release as the floor | quoting numpy 1.19.0 to a Python 3.11 project | The floor is per interpreter ABI (numpy 1.23.2 for cp311) |
| Assuming availability is monotonic | upgrading blosc2 0.6.3 to 0.6.1, or pygeos 0.14 to "latest" | Check the exact candidate version; blosc2 0.3.1-0.6.3 and pygeos >= 0.14 have no aarch64 wheels |
| Mirror gap read as package gap | FAIL against the internal index, PASS against PyPI | INFRA finding, not a dependency change |
| Failed index request read as a missing wheel | `from versions: none` for every pin on both architectures (401, no connection, a server error) | The probe prints CHECK INDEX with the reason; fix access to the index and probe again. Never label a pin from a failed request. A 403 or 404 from one index means only that it lacks the project: the probe keeps the verdict from the others and names that index (section 9) |
| A prompt that reads the caller's input | a loop over pins prints fewer verdicts than pins, with no error | `--no-input` and `</dev/null` on every pip call in a loop (section 3) |
| Pure-Python sdist read as missing wheel | docopt "has no wheel" | Inspect the sdist (section 5); COMPATIBLE |
| Trusting the wheel tester for your pin | "package X passes" | It tests the latest version on the tester's interpreters; probe your pin |
| Environment markers in the pin list (`; python_version < "3.12"`, `; platform_machine == "x86_64"`) | a pin is skipped ("nothing downloaded") or probed although the target would not install it | pip evaluates markers against the interpreter and machine running it, not against `--python-version`/`--platform`: probe with the project's interpreter, and judge pins with machine or platform markers by hand |

## 11. Recording the Evidence

Every verdict in `03-dependency-compatibility-report.md` cites the probe or files-list result that produced it, in this shape:

```
Dependency: blosc2 (direct)
Pinned: 0.6.3
Status: MUST UPGRADE
Reason: no Linux aarch64 wheel for cp311 at 0.6.3; x86_64 wheel exists (blosc2-0.6.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl)
Evidence: pip download --only-binary=:all: --platform manylinux_2_17_aarch64 ... blosc2==0.6.3 -> "from versions: 0.6.4, 0.6.5, ..."
Minimum aarch64 version for cp311: 0.6.4 (blosc2-0.6.4-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl)
Resolution: pin blosc2==0.6.4 (lowest version restoring the wheel; not latest)
```

A finding without a command and a filename is not a finding.
