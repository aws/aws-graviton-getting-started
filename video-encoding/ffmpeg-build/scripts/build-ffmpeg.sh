#!/bin/bash
# Build FFmpeg with enabled libraries.
#
# CUSTOMIZATION: To add a new library, add --enable-lib<name> to configure below.
#
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
SUFFIX=${SUFFIX:-}

compiler_flags=""
[ -n "$CC" ] && compiler_flags="$compiler_flags --cc=$CC"
[ -n "$CXX" ] && compiler_flags="$compiler_flags --cxx=$CXX"

extra_cflags="-I${PREFIX}/include"
[ -n "$CFLAGS" ] && extra_cflags="$extra_cflags $CFLAGS"

# SVT-AV1 is built but not linked to FFmpeg due to API incompatibilities.
# The standalone SvtAv1EncApp binary is available for direct use.
export PKG_CONFIG_PATH="${PREFIX}/lib/pkgconfig"
cd "${SCRIPT_DIR}"/../sources/ffmpeg
make distclean 2>/dev/null || true
./configure $compiler_flags \
    --prefix="${PREFIX}" \
    --pkg-config-flags="--static" \
    --extra-libs="-lpthread -lm -lstdc++" \
    --extra-ldflags="-L${PREFIX}/lib -Wl,--allow-multiple-definition" \
    --extra-cflags="$extra_cflags" \
    --enable-gpl \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libaom \
    --enable-libopus \
    --disable-doc \
    ${SUFFIX:+--progs-suffix=$SUFFIX}
make -j$(nproc)
make install
