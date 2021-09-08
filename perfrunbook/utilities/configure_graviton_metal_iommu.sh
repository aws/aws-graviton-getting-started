#!/bin/bash

grub_loc=/etc/default/grub
#grub_loc=test

help_msg() {
  echo "usage: $0 on|off"
}

set -e

enable_iommu() {
  perl -pi -e 's/GRUB_CMDLINE_LINUX="((.(?!iommu.strict=[01]))*)"$/GRUB_CMDLINE_LINUX="\1 iommu.strict=1"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="(.*?) iommu.strict=[01](.*?)"$/GRUB_CMDLINE_LINUX="\1\2 iommu.strict=1"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="((.(?!iommu.passthrough=[01]))*)"$/GRUB_CMDLINE_LINUX="\1 iommu.passthrough=0"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="(.*?) iommu.passthrough=[01](.*?)"$/GRUB_CMDLINE_LINUX="\1\2 iommu.passthrough=0"/g' $grub_loc
}

disable_iommu() {
  perl -pi -e 's/GRUB_CMDLINE_LINUX="((.(?!iommu.strict=[01]))*)"$/GRUB_CMDLINE_LINUX="\1 iommu.strict=0"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="(.*?) iommu.strict=[01](.*?)"$/GRUB_CMDLINE_LINUX="\1\2 iommu.strict=0"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="((.(?!iommu.passthrough=[01]))*)"$/GRUB_CMDLINE_LINUX="\1 iommu.passthrough=1"/g' $grub_loc
  perl -pi -e 's/GRUB_CMDLINE_LINUX="(.*?) iommu.passthrough=[01](.*?)"$/GRUB_CMDLINE_LINUX="\1\2 iommu.passthrough=1"/g' $grub_loc
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
case $1 in
  on)
    enable_iommu
    update_grub
    ;;
  off)
    disable_iommu
    update_grub
    ;;
  *)
    rm ${grub_loc}.bak
    help_msg
    exit 1
esac

echo "To make changes take effect run: %> sudo shutdown now -r"
