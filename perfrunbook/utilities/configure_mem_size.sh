#!/bin/bash

grub_loc=/etc/default/grub
#grub_loc=test

help_msg() {
  echo "usage: $0 <size in GB>"
}

set -e

config_mem () {
  perl -pi -e 's/GRUB_CMDLINE_LINUX="((.(?!mem=[0-9]+[KMG]))*)"$/GRUB_CMDLINE_LINUX="\1 mem='"${1}"'G"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="(.*?) mem=[0-9]+[KMG](.*?)"$/GRUB_CMDLINE_LINUX="\1\2 mem='"${1}"'G"/g' $grub_loc
}

update_grub() {
  if [[ -d /boot/grub2 ]]; then
    grub2-mkconfig -o /boot/grub2/grub.cfg
  else
    grub2-mkconfig -o /boot/grub/grub.cfg
  fi 
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
