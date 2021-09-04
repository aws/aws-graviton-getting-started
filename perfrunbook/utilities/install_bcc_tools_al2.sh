#!/bin/bash

if [[ $(id -u) -ne 0 ]]; then
  echo "Must run with sudo privileges"
  exit 1
fi

echo "------ INSTALLING BCC PERFORAMANCE TOOLS ------"
amazon-linux-extras enable BCC
yum install -y -q perf kernel-devel-$(uname -r) bcc
