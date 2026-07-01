#!/bin/bash

# The analysis utilities import their Python dependencies as libraries and are
# shebang'd against this interpreter. We install those dependencies into a
# dedicated virtual environment rather than the system interpreter: newer
# distributions mark the system Python as externally-managed (PEP 668), and a
# venv keeps the dependencies self-contained on every distribution.
PERFRUNBOOK_VENV="/opt/perfrunbook-venv"

install_python_dependencies () {
  python3 -m venv "${PERFRUNBOOK_VENV}"
  "${PERFRUNBOOK_VENV}/bin/pip" install --upgrade pip
  "${PERFRUNBOOK_VENV}/bin/pip" install pandas numpy scipy matplotlib sh seaborn plotext
}

install_al2023_dependencies () {
  echo "------ INSTALLING UTILITIES ------"
  dnf install -y -q vim unzip git

  echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
  dnf install -y -q sysstat htop hwloc tcpdump

  echo "------ INSTALLING LOW LEVEL PERFORAMANCE TOOLS ------"
  dnf install -y -q perf kernel-devel-$(uname -r) bcc

  echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
  dnf install -y -q python3 python3-pip
  install_python_dependencies
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}
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
  install_python_dependencies
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
  apt-get install -y -q python3-dev python3-pip python3-venv
  install_python_dependencies
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}

install_ubuntu2404_dependencies () {
  echo "------ INSTALLING UTILITIES ------"
  apt-get update
  apt-get install -y -q vim unzip git lsb-release grub2-common net-tools
  ln -s /usr/sbin/grub-mkconfig /usr/sbin/grub2-mkconfig

  echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
  apt-get install -y -q sysstat htop hwloc tcpdump dstat

  echo "------ INSTALLING LOW LEVEL PERFORAMANCE TOOLS ------"
  apt-get install -y -q linux-tools-$(uname -r) linux-headers-$(uname -r) linux-modules-extra-$(uname -r) bpfcc-tools

  echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
  apt-get install -y -q python3-dev python3-pip python3-venv
  install_python_dependencies
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}

install_rhel_9_5_dependencies () {
  echo "------ INSTALLING UTILITIES ------"
  dnf install -y -q vim unzip git perl-open.noarch

  echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
  dnf install -y -q sysstat htop hwloc tcpdump

  echo "------ INSTALLING LOW LEVEL PERFORAMANCE TOOLS ------"
  dnf install -y -q perf kernel-devel-$(uname -r) bcc

  echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
  dnf install -y -q python3 python3-pip
  install_python_dependencies
  git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

  echo "------ DONE ------"
}

install_sles_15_sp6_dependencies() {
    echo "------ INSTALLING UTILITIES ------"
    zypper --quiet --non-interactive install vim unzip git

    echo "------ INSTALLING HIGH LEVEL PERFORMANCE TOOLS ------"
    zypper --quiet --non-interactive install sysstat htop hwloc tcpdump

    echo "------ INSTALLING LOW LEVEL PERFORMANCE TOOLS ------"
    # Install perf and related tools
    zypper --quiet --non-interactive install perf
    zypper --quiet --non-interactive install kernel-default-devel
    zypper --quiet --non-interactive install bcc-tools

    echo "------ INSTALL ANALYSIS TOOLS AND DEPENDENCIES ------"
    # Install Python and pip
    zypper --quiet --non-interactive install python3 python3-pip
    install_python_dependencies

    # Get FlameGraph tools
    git clone https://github.com/brendangregg/FlameGraph.git FlameGraph

    echo "------ DONE ------"
}

if [[ $(id -u) -ne 0 ]]; then
  echo "Must run with sudo privileges"
  exit 1
fi

os_name=$(cat /etc/os-release | grep "PRETTY_NAME" | awk -F"=" '{print $2}' | tr -d '[="=]' | tr -d [:cntrl:])


case "$os_name" in
  "Amazon Linux 2023"*)
    install_al2023_dependencies
    ;;
  "Amazon Linux 2")
    install_al2_dependencies
    ;;
  "Ubuntu 20.04"*)
    install_ubuntu2004_dependencies
    ;;
  "Ubuntu 22.04"*)
    install_ubuntu2004_dependencies
    ;;
  "Ubuntu 24.04"*)
    install_ubuntu2404_dependencies
    ;;
  "Red Hat Enterprise Linux 9"*)
    install_rhel_9_5_dependencies
    ;;
  "SUSE Linux Enterprise Server 15 SP6")
    install_sles_15_sp6_dependencies
    ;;
  *)
    echo "$os_name not supported"
    exit 1
    ;;
esac

echo "DEPENDENCIES SUCCESSFULLY INSTALLED! -- RUN UTILITIES FROM THIS DIRECTORY"
