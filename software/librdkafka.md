Building librdkafka for AWS Graviton (including Python module)
==============================================================

[librdkafka](https://github.com/confluentinc/librdkafka) is a C library
implementation of the Apache Kafka protocol, providing Producer, Consumer and
Admin clients. It was designed with message delivery reliability and high
performance in mind.

## Table of contents

<!-- no toc -->
- [Amazon Linux 2](#amazon-linux-2)
- [Red Hat Enterprise Linux 8 (and compatible EL 8 distributions e.g. Rocky Linux)](#red-hat-enterprise-linux-8-and-compatible-el-8-distributions-eg-rocky-linux)
- [Ubuntu 20.04 (Focal) and 22.04 (Jammy)](#ubuntu-2004-focal-and-2204-jammy)

## Amazon Linux 2

First, install the necessary dependencies, add the current user to the `mock` group, and log out.

```sh
sudo amazon-linux-extras install -y mock2
sudo yum -y install git
sudo usermod -G mock `id -un`
logout
```

Next, log back into the instance, and run:

```sh
export LIBRDKAFKA_VERSION=2.0.2 # Or whichever version you need. We tested with 2.0.2.
git clone -b v${LIBRDKAFKA_VERSION} https://github.com/confluentinc/librdkafka 
cd librdkafka/packaging/rpm
MOCK_CONFIG=/etc/mock/amazonlinux-2-aarch64.cfg make
# Packages will be placed in ./pkgs-${LIBRDKAFKA_VERSION}-1-/etc/mock/amazonlinux-2-aarch64.cfg/
cd ./pkgs-${LIBRDKAFKA_VERSION}-1-/etc/mock/amazonlinux-2-aarch64.cfg/
sudo yum -y install *.aarch64.rpm
```

Once you have installed the RPM packages, you can build and install the Python module:

```sh
sudo yum -y install gcc python3-devel
python3 -m pip install --user --no-binary confluent-kafka confluent-kafka
```

## Red Hat Enterprise Linux 8 (and compatible EL 8 distributions e.g. Rocky Linux)

First, install the necessary dependencies, add the current user to the `mock` group, and log out.

```
sudo dnf config-manager --set-enabled powertools
sudo dnf install -y git make epel-release
sudo dnf install -y mock
sudo usermod -G mock `id -un`
logout
```

Next, log back into the instance, and run:

```sh
export LIBRDKAFKA_VERSION=2.0.2 # Or whichever version you need. We tested with 2.0.2.
git clone -b v${LIBRDKAFKA_VERSION} https://github.com/confluentinc/librdkafka 
cd librdkafka/packaging/rpm
make
# Packages will be placed in ./pkgs-${LIBRDKAFKA_VERSION}-1-/etc/mock/amazonlinux-2-aarch64.cfg/
cd ./pkgs-2.0.2-1-default
sudo dnf -y install *.aarch64.rpm
```

Once you have installed the RPM packages, you can build and install the Python module:

```sh
sudo dnf -y install gcc python3-devel
python3 -m pip install --user --no-binary confluent-kafka confluent-kafka
```

## Ubuntu 20.04 (Focal) and 22.04 (Jammy)

```sh
export LIBRDKAFKA_VERSION=2.0.2 # Or whichever version you need. We tested with 2.0.2.
export EMAIL=builder@example.com
sudo apt-get update
sudo apt-get install -y git-buildpackage debhelper zlib1g-dev libssl-dev libsasl2-dev liblz4-dev
git clone https://github.com/confluentinc/librdkafka 
cd librdkafka
git checkout -b debian v${LIBRDKAFKA_VERSION}
dch --newversion ${LIBRDKAFKA_VERSION}-1 "Release version ${LIBRDKAFKA_VERSION}" --urgency low
dch --release --distribution unstable ""
git commit -am "Tag Debian release ${LIBRDKAFKA_VERSION}"
mkdir ../build-area
git archive --format=tgz --output=../build-area/librdkafka_${LIBRDKAFKA_VERSION}.orig.tar.gz HEAD
gbp buildpackage -us -uc --git-verbose --git-builder="debuild --set-envvar=VERSION=${LIBRDKAFKA_VERSION} --set-envvar=SKIP_TESTS=y -i -I" --git-ignore-new
```

This will yield a set of Debian packages in the build area. To install them:

```sh
sudo dpkg -i ../build-area/*_arm64.deb
```

Once you have installed the packages, you can build and install the Python module:

```sh
python3 -m pip install --user --no-binary confluent-kafka confluent-kafka
```

## Example Dockerfile for Python module

The following `Dockerfile` can be used to build a container image based on
Debian Bullseye containing the Python module. It produces a minimized image via
a multi-stage build.

```
FROM public.ecr.aws/docker/library/python:3.10.10-slim-bullseye AS build

ARG LIBRDKAFKA_VERSION=2.0.2
ENV EMAIL=nobody@build.example.com

WORKDIR /build
RUN apt-get update && \
    apt-get install -y git-buildpackage debhelper zlib1g-dev libssl-dev libsasl2-dev liblz4-dev python3-dev && \
    git clone https://github.com/confluentinc/librdkafka && \
    cd librdkafka && \
    git checkout -b debian v${LIBRDKAFKA_VERSION} && \
    dch --newversion ${LIBRDKAFKA_VERSION}-1 "Release version ${LIBRDKAFKA_VERSION}" --urgency low && \
    dch --release --distribution unstable "" && \
    git commit -am "Tag Debian release ${LIBRDKAFKA_VERSION}" && \
    mkdir ../build-area && \
    git archive --format=tgz --output=../build-area/librdkafka_${LIBRDKAFKA_VERSION}.orig.tar.gz HEAD && \
    gbp buildpackage -us -uc --git-verbose --git-builder="debuild --set-envvar=VERSION=${LIBRDKAFKA_VERSION} --set-envvar=SKIP_TESTS=y -i -I" --git-ignore-new && \
    apt-get -y install ../build-area/*.deb && \
    python3 -m pip install --no-binary confluent-kafka confluent-kafka


FROM public.ecr.aws/docker/library/python:3.10.10-slim-bullseye
ARG LIBRDKAFKA_VERSION=2.0.2
COPY --from=build /build/build-area/*.deb /tmp/
RUN apt-get update && apt-get -y install /tmp/*.deb && apt-get clean && rm -rf /var/cache/apt
COPY --from=build /usr/local/lib/python3.10/site-packages/confluent_kafka-${LIBRDKAFKA_VERSION}-py3.10.egg-info \
                  /usr/local/lib/python3.10/site-packages/confluent_kafka-${LIBRDKAFKA_VERSION}-py3.10.egg-info
COPY --from=build /usr/local/lib/python3.10/site-packages/confluent_kafka/ \
                  /usr/local/lib/python3.10/site-packages/confluent_kafka/
```