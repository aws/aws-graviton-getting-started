# FFmpeg Builder Dockerfile
# 
# CUSTOMIZATION: To add a new library:
#   1. Add a build stage below (copy the opus stage as template)
#   2. Add COPY --from=<stage> lines to both ffmpeg stages
#   3. Add --enable-lib* flag in scripts/build-ffmpeg.sh
#
# Library stages run in parallel for faster builds.

ARG BASE_IMAGE=public.ecr.aws/amazonlinux/amazonlinux:2023
ARG COMPILER=gcc
ARG TARGET_PLATFORM=graviton2

FROM ${BASE_IMAGE} AS base
ARG COMPILER
ARG TARGET_PLATFORM
ENV COMPILER=${COMPILER}
ENV TARGET_PLATFORM=${TARGET_PLATFORM}
COPY scripts /build/scripts
RUN /build/scripts/install-dependencies.sh
RUN /build/scripts/setup-compiler.sh
SHELL ["/bin/bash", "-lc"]
WORKDIR /build

# == x264 ==
FROM base AS x264
COPY sources/x264 sources/x264
RUN PREFIX=/usr/local scripts/build-x264.sh

# == x265 8-bit ==
FROM base AS x265-8bit
COPY sources/x265 sources/x265
RUN HIGH_BIT_DEPTH=0 PREFIX=/usr/local scripts/build-x265.sh

# == x265 10-bit ==
FROM base AS x265-10bit
COPY sources/x265 sources/x265
RUN HIGH_BIT_DEPTH=1 PREFIX=/usr/local scripts/build-x265.sh

# == aom ==
FROM base AS aom
COPY sources/aom sources/aom
RUN PREFIX=/usr/local scripts/build-aom.sh

# == svtav1 ==
FROM base AS svtav1
COPY sources/SVT-AV1 sources/SVT-AV1
RUN PREFIX=/usr/local scripts/build-svtav1.sh

# == opus ==
FROM base AS opus
COPY sources/opus sources/opus
RUN PREFIX=/usr/local scripts/build-opus.sh

# == ffmpeg 8-bit ==
FROM base AS ffmpeg-8bit
COPY sources/ffmpeg sources/ffmpeg
COPY sources/revisions.json sources/revisions.json
COPY --from=x264 /usr/local /usr/local
COPY --from=x265-8bit /usr/local /usr/local
COPY --from=aom /usr/local /usr/local
COPY --from=svtav1 /usr/local /usr/local
COPY --from=opus /usr/local /usr/local
RUN PREFIX=/usr/local scripts/build-ffmpeg.sh

# == ffmpeg 10-bit ==
FROM base AS ffmpeg-10bit
COPY sources/ffmpeg sources/ffmpeg
COPY --from=x264 /usr/local /usr/local
COPY --from=x265-10bit /usr/local /usr/local
COPY --from=aom /usr/local /usr/local
COPY --from=svtav1 /usr/local /usr/local
COPY --from=opus /usr/local /usr/local
RUN SUFFIX=-10bit PREFIX=/usr/local scripts/build-ffmpeg.sh

# == combine and package ==
FROM ffmpeg-8bit AS ffmpeg_combined
COPY --from=ffmpeg-10bit /usr/local/bin/*-10bit /usr/local/bin/

FROM ffmpeg_combined AS packager
ARG PKG_NAME=ffmpeg-optimized
ARG PKG_VERSION=1.0.0
RUN PKG_NAME=${PKG_NAME} PKG_VERSION=${PKG_VERSION} OUTPUT_DIR=/output scripts/package.sh

FROM scratch AS output
COPY --from=packager /output /
