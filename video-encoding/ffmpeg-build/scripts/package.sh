#!/bin/bash
# Package FFmpeg installation into RPM or DEB
set -euxo pipefail

PREFIX=${PREFIX:-/usr/local}
PKG_NAME=${PKG_NAME:-ffmpeg-optimized}
PKG_VERSION=${PKG_VERSION:-1.0.0}
OUTPUT_DIR=${OUTPUT_DIR:-/output}

# Note: Input validation is performed in build_ffmpeg.py before Docker build

mkdir -p /staging/usr/local
cp -a ${PREFIX}/bin ${PREFIX}/lib ${PREFIX}/include /staging/usr/local/
mkdir -p /staging/usr/local/share/doc/${PKG_NAME}
cp sources/revisions.json /staging/usr/local/share/doc/${PKG_NAME}/revisions.json

DOC_PATH=/usr/local/share/doc/${PKG_NAME}/revisions.json

os_name=$(cat /etc/os-release | grep "^ID=" | cut -d= -f2 | tr -d '"')

if [[ "$os_name" == "amzn" ]]; then
    # RPM package
    mkdir -p /root/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    cat > /root/rpmbuild/SPECS/ffmpeg.spec << EOF
Name: ${PKG_NAME}
Version: ${PKG_VERSION}
Release: 1%{?dist}
Summary: Optimized FFmpeg build
License: GPL
AutoReqProv: no

%description
FFmpeg optimized build with x264, x265, aom, SVT-AV1, and opus.

%post
echo "Build information: ${DOC_PATH}"
cat ${DOC_PATH}

%install
mkdir -p %{buildroot}/usr/local
cp -a /staging/usr/local/* %{buildroot}/usr/local/

%files
/usr/local/*
EOF
    rpmbuild -bb /root/rpmbuild/SPECS/ffmpeg.spec
    mkdir -p ${OUTPUT_DIR}
    cp /root/rpmbuild/RPMS/*/*.rpm ${OUTPUT_DIR}/
else
    # DEB package
    ARCH=$(dpkg --print-architecture)
    mkdir -p /staging/DEBIAN
    cat > /staging/DEBIAN/control << EOF
Package: ${PKG_NAME}
Version: ${PKG_VERSION}
Architecture: ${ARCH}
Maintainer: Builder
Description: Optimized FFmpeg build
 FFmpeg optimized build with x264, x265, aom, SVT-AV1, and opus.
EOF
    cat > /staging/DEBIAN/postinst << EOF
#!/bin/sh
echo "Build information: ${DOC_PATH}"
cat ${DOC_PATH}
EOF
    chmod 755 /staging/DEBIAN/postinst
    mkdir -p ${OUTPUT_DIR}
    dpkg-deb --build /staging ${OUTPUT_DIR}/${PKG_NAME}_${PKG_VERSION}_${ARCH}.deb
fi
