#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}

cd "${SCRIPT_DIR}"/../sources/SVT-AV1
rm -rf Build
mkdir -p Build
cd Build
cmake .. -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="${PREFIX}" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCMAKE_C_FLAGS="$CFLAGS" -DCMAKE_CXX_FLAGS="$CXXFLAGS"
make -j$(nproc) install
