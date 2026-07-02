#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
AOM_SRC="${SCRIPT_DIR}"/../sources/aom

# Apply nasm 3.x compatibility patch
# nasm 3.x changed how -O optimization is documented; the patch adjusts aom's
# CMake detection so it works with both nasm 2.x and 3.x.
# Use --dry-run with -R to check if already applied; only apply if needed.
# If the patch fails (e.g. aom version bump), check whether aom already handles
# nasm 3.x natively before failing — future aom releases may incorporate the fix.
if [ "${SKIP_AOM_NASM_PATCH:-0}" = "1" ]; then
    echo "Skipping nasm 3.x patch (SKIP_AOM_NASM_PATCH=1)"
else
    PATCH_FILE="${SCRIPT_DIR}"/../patches/aom-nasm3-compat.patch
    AOM_NASM_CMAKE="${AOM_SRC}/build/cmake/aom_optimization.cmake"
    if patch -d "${AOM_SRC}" -p1 -R --dry-run < "$PATCH_FILE" >/dev/null 2>&1; then
        echo "nasm 3.x patch already applied, skipping"
    elif patch -d "${AOM_SRC}" -p1 -N --dry-run < "$PATCH_FILE" >/dev/null 2>&1; then
        patch -d "${AOM_SRC}" -p1 -N < "$PATCH_FILE"
    elif grep -q "select optimization" "$AOM_NASM_CMAKE" 2>/dev/null; then
        echo "aom already supports nasm 3.x natively, patch not needed"
    else
        echo "Error: nasm 3.x compatibility patch failed to apply and aom does not"
        echo "       appear to have native nasm 3.x support."
        echo "       Regenerate the patch for the current aom version, or set"
        echo "       SKIP_AOM_NASM_PATCH=1 to bypass if you are using nasm 2.x."
        exit 1
    fi
fi

cd "${AOM_SRC}"
rm -rf aom_build
mkdir -p aom_build
cd aom_build
cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="${PREFIX}" -DENABLE_SHARED=off -DENABLE_NASM=on -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_C_FLAGS="$CFLAGS" -DCMAKE_CXX_FLAGS="$CXXFLAGS" ..
make -j$(nproc) install
