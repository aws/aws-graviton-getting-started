#!/bin/bash

install_al2_dependencies () {
  echo "------ INSTALLING UTILITIES ------"
  yum install -y -q vim unzip git

  echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
  yum install -y -q sysstat dstat htop hwloc tcpdump

  echo "------ INSTALLING LOW LEVEL PERFORAMANCE TOOLS ------"
  amazon-linux-extras enable BCC
  yum install -y -q perf kernel-devel-$(uname -r) bcc

  echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
  yum install -y -q python3 python3-pip
  python3 -m pip install --upgrade pip
  python3 -m pip install pandas numpy scipy matplotlib sh seaborn plotext
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}

install_ubuntu2004_dependencies () {
  echo "------ INSTALLING UTILITIES ------"
  apt-get update
  apt-get install -y -q vim unzip git lsb-release grub2-common net-tools
  ln -s /usr/sbin/grub-mkconfig /usr/sbin/grub2-mkconfig

  echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
  apt-get install -y -q sysstat htop hwloc tcpdump dstat

  echo "------ INSTALLING LOW LEVEL PERFORAMANCE TOOLS ------"
  apt-get install -y -q linux-tools-$(uname -r) linux-headers-$(uname -r) linux-modules-extra-$(uname -r) bpfcc-tools

  echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
  apt-get install -y -q python3-dev python3-pip
  python3 -m pip install --upgrade pip
  python3 -m pip install pandas numpy scipy matplotlib sh seaborn plotext
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}

if [[ $(id -u) -ne 0 ]]; then
  echo "Must run with sudo privileges"
  exit 1
fi

os_name=$(cat /etc/os-release | grep "PRETTY_NAME" | awk -F"=" '{print $2}' | tr -d '[="=]' | tr -d [:cntrl:])


if [[ "$os_name" == "Amazon Linux 2" ]]; then
  install_al2_dependencies
elif [[ "$os_name" =~ "Ubuntu 20.04" ]]; then
  install_ubuntu2004_dependencies
elif [[ "$os_name" =~ "Ubuntu 22.04" ]]; then
  install_ubuntu2004_dependencies
else
  echo "$os_name not supported"
  exit 1
fi

echo "DEPENDENCIES SUCCESSFULLY INSTALLED! -- RUN UTILITIES FROM THIS DIRECTORY"
