#!/bin/bash

# Find the download link to ArmPL (Ubuntu 20.04, GCC-12) on https://developer.arm.com/downloads/-/arm-performance-libraries
# please check the download link for the appropriate version
mkdir -p /shared/tools && cd /shared/tools
wget -O arm-performance-libraries_23.04_Ubuntu-20.04_gcc-10.2.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-performance-libraries/23-04/ubuntu-20/arm-performance-libraries_23.04_Ubuntu-20.04_gcc-12.2.tar'
tar xf arm-performance-libraries_23.04_Ubuntu-20.04_gcc-10.2.tar
cd arm-performance-libraries_23.04_Ubuntu-20.04/
./arm-performance-libraries_23.04_Ubuntu-20.04.sh -i /shared/arm -a --force
