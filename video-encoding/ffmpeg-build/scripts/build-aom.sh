#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
AOM_SRC="${SCRIPT_DIR}"/../sources/aom

# Apply nasm 3.x compatibility patch
# nasm 3.x moved -O optimization docs from "nasm -hf" to "nasm -h"
patch -d "${AOM_SRC}" -p1 -N < "${SCRIPT_DIR}"/../patches/aom-nasm3-compat.patch || true

cd "${AOM_SRC}"
rm -rf aom_build
mkdir -p aom_build
cd aom_build
cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="${PREFIX}" -DENABLE_SHARED=off -DENABLE_NASM=on -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_C_FLAGS="$CFLAGS" -DCMAKE_CXX_FLAGS="$CXXFLAGS" ..
make -j$(nproc) install
