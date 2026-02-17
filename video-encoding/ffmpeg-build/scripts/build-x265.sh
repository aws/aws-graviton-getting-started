#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
HIGH_BIT_DEPTH=${HIGH_BIT_DEPTH:-0}

BUILD_CONFIG_FLAGS=""

# Disable assembly for older compilers that can't handle ARM intrinsics
case "${CC:-gcc}" in
    gcc|gcc-[0-9]|gcc-1[0-3])
        BUILD_CONFIG_FLAGS="-DENABLE_ASSEMBLY=OFF"
        ;;
    clang|clang-[0-9]|clang-1[0-7])
        BUILD_CONFIG_FLAGS="-DENABLE_ASSEMBLY=OFF"
        ;;
esac

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
