#!/bin/bash

# download acfl for ubuntu 20.04 from arm website - https://developer.arm.com/downloads/-/arm-compiler-for-linux
# please check the download link for the appropriate version
# install acfl will include armpl automatically
mkdir -p /shared/tools
cd /shared/tools
wget -O arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/23-04-1/arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar'
tar xf arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar
./arm-compiler-for-linux_23.04.1_Ubuntu-20.04/arm-compiler-for-linux_23.04.1_Ubuntu-20.04.sh \
-i /shared/arm -a --force
