#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
HIGH_BIT_DEPTH=${HIGH_BIT_DEPTH:-0}

# Enable assembly optimizations. This is the bulk of x265's performance on both
# ARM (Neon/DotProd/I8MM/SVE/SVE2) and x86 (nasm), so it must stay on whenever
# the toolchain can build it.
#
# x265's CMake already degrades gracefully across most aarch64 extensions, with
# one gap: its SVE2 assembly (.S) is *always* compiled with
# -march=armv9-a+i8mm+sve2 regardless of target platform. Toolchains that cannot
# assemble that fail the whole build. Empirically (x265 4.1, validated on a
# Graviton4 host) this affects:
#   - gcc   < 12  (cc1 has no armv9-a)
#   - clang < 15  (integrated assembler rejects the SVE2 .S files)
# Every other aarch64 assembly path (~20 objects) still builds on those
# compilers. So instead of disabling ALL assembly (the previous behavior, which
# also needlessly dropped the x86 nasm paths for the default gcc/clang names),
# keep assembly on and disable ONLY SVE2 when the active compiler cannot build
# it. Capability is probed directly so this stays correct for future toolchains
# without per-version maintenance.
BUILD_CONFIG_FLAGS="-DENABLE_ASSEMBLY=ON"

CC_BIN="${CC:-gcc}"
# x265's hand-written SVE2 assembly requires a compiler that can assemble
# -march=armv9-a+i8mm+sve2. Probe whether it can, then:
#   - If target CFLAGS request +sve2 but compiler can't: error (silent perf loss)
#   - If target doesn't need SVE2 but compiler can't: just disable SVE2 assembly
#
# NOTE: The probe uses -march=armv9-a+i8mm+sve2 because that's the exact flag
# x265 4.1 passes to compile its SVE2 .S files (source/common/aarch64/CMakeLists.txt).
# The .arch directive in the probe (.arch armv8-a+sve2) tests assembler acceptance
# of SVE2 mnemonics. Both gates must pass for x265's SVE2 objects to build.
# Re-verify this flag if x265 is bumped beyond 4.1.
if echo "${CFLAGS:-}" | grep -q "+sve2"; then
    SVE2_PROBE="$(mktemp --suffix=.S)"
    printf '.arch armv8-a+sve2\nptrue p0.b, vl8\nsqrdmlah z0.s, z1.s, z2.s\nret\n' > "$SVE2_PROBE"
    if ! "${CC_BIN}" -march=armv9-a+i8mm+sve2 -c "$SVE2_PROBE" -o /dev/null >/dev/null 2>&1; then
        rm -f "$SVE2_PROBE"
        echo "Error: ${CC_BIN} cannot assemble SVE2, but target platform requires it."
        echo "       Use GCC >= 12 or Clang >= 15."
        exit 1
    fi
    rm -f "$SVE2_PROBE"
elif echo "${CFLAGS:-}" | grep -q "armv8"; then
    # ARM target without SVE2 (graviton2/3) — disable SVE2 assembly, keep the rest
    SVE2_PROBE="$(mktemp --suffix=.S)"
    printf '.arch armv8-a+sve2\nptrue p0.b, vl8\nsqrdmlah z0.s, z1.s, z2.s\nret\n' > "$SVE2_PROBE"
    if ! "${CC_BIN}" -march=armv9-a+i8mm+sve2 -c "$SVE2_PROBE" -o /dev/null >/dev/null 2>&1; then
        BUILD_CONFIG_FLAGS="${BUILD_CONFIG_FLAGS} -DENABLE_SVE2=OFF"
    fi
    rm -f "$SVE2_PROBE"
fi

# CMake 4.x (shipped by e.g. Ubuntu resolute) removed support for the legacy
# cmake_minimum_required (<3.5) and for setting policies CMP0025/CMP0054 to OLD
# behavior, all of which x265 4.1's CMakeLists still uses. Make the project
# configure under modern CMake while staying compatible with older CMake:
#   - rewrite the two policies to NEW (accepted by every CMake >= 3.0; on Linux
#     the OLD/NEW distinction for these two is immaterial). Idempotent.
#   - allow the old minimum-version declaration via CMAKE_POLICY_VERSION_MINIMUM
#     (silently ignored by CMake versions predating that variable).
X265_CMAKELISTS="${SCRIPT_DIR}/../sources/x265/source/CMakeLists.txt"
sed -i -e 's/cmake_policy(SET CMP0025 OLD)/cmake_policy(SET CMP0025 NEW)/' \
       -e 's/cmake_policy(SET CMP0054 OLD)/cmake_policy(SET CMP0054 NEW)/' \
       "${X265_CMAKELISTS}"
BUILD_CONFIG_FLAGS="${BUILD_CONFIG_FLAGS} -DCMAKE_POLICY_VERSION_MINIMUM=3.5"

cd "${SCRIPT_DIR}"/../sources/x265/build/linux
rm -rf *

if [ "${HIGH_BIT_DEPTH}" = "1" ]; then
    cmake -G "Unix Makefiles" \
        -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
        -DENABLE_SHARED=off \
        -DHIGH_BIT_DEPTH=on \
        -DENABLE_LIBNUMA=OFF \
        -DCMAKE_C_FLAGS="$CFLAGS" \
        -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
        $BUILD_CONFIG_FLAGS \
        ../../source
else
    cmake -G "Unix Makefiles" \
        -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
        -DENABLE_SHARED=off \
        -DENABLE_LIBNUMA=OFF \
        -DCMAKE_C_FLAGS="$CFLAGS" \
        -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
        $BUILD_CONFIG_FLAGS \
        ../../source
fi

make -j$(nproc) install

# Rename 10-bit CLI binary
if [ "${HIGH_BIT_DEPTH}" = "1" ] && [ -f "${PREFIX}/bin/x265" ]; then
    mv "${PREFIX}/bin/x265" "${PREFIX}/bin/x265-10bit"
fi
