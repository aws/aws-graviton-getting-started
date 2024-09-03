#!/bin/bash

install_compilers() {
    if [ -f /opt/slurm/etc/slurm.sh ]; then
        . /opt/slurm/etc/slurm.sh
    else
        . /etc/profile.d/spack.sh
    fi

    spack install acfl
    spack load acfl
    spack compiler add --scope site
}

install_compilers