#!/bin/bash

grub_loc=/etc/default/grub
#grub_loc=test

help_msg() {
  echo "usage: $0 <size in GB>"
}

set -e

config_mem () {
  perl -pi -e 's/GRUB_CMDLINE_LINUX_DEFAULT="((.(?!mem=[0-9]+[KMG]))*)"$/GRUB_CMDLINE_LINUX_DEFAULT="\1 mem='"${1}"'G"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX_DEFAULT="(.*?) mem=[0-9]+[KMG](.*?)"$/GRUB_CMDLINE_LINUX_DEFAULT="\1\2 mem='"${1}"'G"/g' $grub_loc
}

update_grub() {
  grub2-mkconfig -o /boot/grub2/grub.cfg
}

if [[ $# -ne 1 ]]; then
  help_msg
  exit 1
fi

if [[ $(id -u) -ne 0 ]]; then
  echo "Must be run with sudo privileges"
  exit 1
fi

cp $grub_loc ${grub_loc}.bak

config_mem $1
update_grub

echo "To make changes take effect run: %> sudo shutdown now -r"
