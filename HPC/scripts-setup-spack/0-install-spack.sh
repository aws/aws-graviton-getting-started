#!/bin/bash

##############################################################################################
# # This script will download and setup Spack.                                               #
# # It is a streamlined version of the script available at:                                  #
# # (https://github.com/spack/spack-configs/blob/main/AWS/parallelcluster/postinstall.sh)    #
# # Use as postinstall in AWS ParallelCluster (https://docs.aws.amazon.com/parallelcluster/) #
##############################################################################################

print_help() {
    cat <<EOF
Usage: postinstall.sh [-fg] [-v] [spec] [spec...]

Installs spack on a parallel cluster with recommended configurations.
Spack directory is cloned into a shared directory and recommended packages are
configured.

As the install can take more than an hour (especially on smaller instances), the
default is to run the script in the background so that it can be used as
pcluster's postinstall CloudFormation script without timing out during cluster
initialization.  Output can be monitored in /var/log/spack-postinstall.log

Options:
 -h|--help              Print this help message.
 -v                     Be verbose during execution
Developer Options:
 --config-branch        Pull configuration (e.g., packages.yaml) from this
                        branch.  Default is "main".
 --config-repo          Pull configuration (e.g., packages.yaml) from this
                        github user/repo.  Default is "spack/spack-configs".
 --spack-branch         Clone spack using this branch.  Default is "develop"
 --spack-repo           Clone spack using this github user/repo. Default is
                        "spack/spack".
EOF
}

# CONFIG_REPO: a the user/repo on github to use for configuration.a custom user/repo/branch in case users wish to
# provide or test their own configurations.
export CONFIG_REPO="spack/spack-configs"
export CONFIG_BRANCH="main"
export SPACK_REPO="spack/spack"
export SPACK_BRANCH="develop"
install_specs=()
install_in_foreground=false
while [ $# -gt 0 ]; do
    case $1 in
        --config-branch )
            CONFIG_BRANCH="$2"
            shift 2
            ;;
        --config-repo )
            CONFIG_REPO="$2"
            shift 2
            ;;
        -h|--help )
            print_help
            exit 0
            ;;
        --spack-branch )
            SPACK_BRANCH="$2"
            shift 2
            ;;
        --spack-repo )
            SPACK_REPO="$2"
            shift 2
            ;;
        -v )
            set -v
            shift
            ;;
        -* )
            print_help
            echo
            echo "ERROR: Unknown option: $1"
            exit 1
            ;;
        * )
            echo "Going to install: $1"
            install_specs+=("${1}")
            shift
            ;;
    esac
done

setup_variables() {
    # Install onto first shared storage device
    cluster_config="/opt/parallelcluster/shared/cluster-config.yaml"
    pip3 install pyyaml
    if [ -f "${cluster_config}" ]; then
        os=$(python3 << EOF
#/usr/bin/env python
import yaml
with open("${cluster_config}", 'r') as s:
    print(yaml.safe_load(s)["Image"]["Os"])
EOF
          )

        case "${os}" in
            alinux*)
                cfn_cluster_user="ec2-user"
                ;;
            centos*)
                cfn_cluster_user="centos"
                ;;
            ubuntu*)
                cfn_cluster_user="ubuntu"
                ;;
            *)
                cfn_cluster_user=""
        esac

        cfn_ebs_shared_dirs=$(python3 << EOF
#/usr/bin/env python
import yaml
with open("${cluster_config}", 'r') as s:
    print(yaml.safe_load(s)["SharedStorage"][0]["MountDir"])
EOF
                           )
        scheduler=$(python3 << EOF
#/usr/bin/env python
import yaml
with open("${cluster_config}", 'r') as s:
    print(yaml.safe_load(s)["Scheduling"]["Scheduler"])
EOF
                 )
    elif [ -f /etc/parallelcluster/cfnconfig ]; then
        . /etc/parallelcluster/cfnconfig
    else
        echo "Cannot find ParallelCluster configs"
        cfn_ebs_shared_dirs=""
    fi

    # If we cannot find any shared directory, use $HOME of standard user
    if [ -z "${cfn_ebs_shared_dirs}" ]; then
        for cfn_cluster_user in ec2-user centos ubuntu; do
            [ -d "/home/${cfn_cluster_user}" ] && break
        done
        cfn_ebs_shared_dirs="/home/${cfn_cluster_user}"
    fi

    install_path=${SPACK_ROOT:-"${cfn_ebs_shared_dirs}/spack"}
    echo "Installing Spack into ${install_path}."
}

major_version() {
    pcluster_version=$(grep -oE '[0-9]*\.[0-9]*\.[0-9]*' /opt/parallelcluster/.bootstrapped)
    echo "${pcluster_version/\.*}"
}

download_spack() {
    if [ -z "${SPACK_ROOT}" ]
    then
        [ -d "${install_path}" ] || \
            if [ -n "${SPACK_BRANCH}" ]
            then
                git clone -c feature.manyFiles=true "https://github.com/${SPACK_REPO}" -b "${SPACK_BRANCH}" "${install_path}"
            elif [ -n "${spack_commit}" ]
            then
                git clone -c feature.manyFiles=true "https://github.com/${SPACK_REPO}" "${install_path}"
                cd "${install_path}" && git checkout "${spack_commit}"
            fi
        return 0
    else
        # Let the script know we did not download spack, so the owner will not be fixed on exit.
        return 1
    fi
}

# zen3 EC2 instances (e.g. hpc6a) is misidentified as zen2 so zen3 packages are found under packages-zen2.yaml.
target() {
    (
        . "${install_path}/share/spack/setup-env.sh"
        spack arch -t
    )
}

download_packages_yaml() {
    # $1: spack target
    . "${install_path}/share/spack/setup-env.sh"
    target="${1}"
    curl -Ls "https://raw.githubusercontent.com/${CONFIG_REPO}/${CONFIG_BRANCH}/AWS/parallelcluster/packages-${target}.yaml" -o /tmp/packages.yaml
    if [ "$(cat /tmp/packages.yaml)" = "404: Not Found" ]; then
        # Pick up parent if current generation is not available
        for target in $(spack-python -c 'print(" ".join(spack.platforms.host().target("'"${target}"'").microarchitecture.to_dict()["parents"]))'); do
            if [ -z "${target}" ] ; then
                echo "Cannot find suitable packages.yaml"
                exit 1
            fi
            download_packages_yaml "${target}"
        done
    else
        # Exit "for target in ..." loop.
        break &>/dev/null
    fi
}

set_modules() {
    mkdir -p "${install_path}/etc/spack"
    curl -Ls "https://raw.githubusercontent.com/${CONFIG_REPO}/${CONFIG_BRANCH}/AWS/parallelcluster/modules.yaml" \
         -o "${install_path}/etc/spack/modules.yaml"
}

set_pcluster_defaults() {
    # Set versions of pre-installed software in packages.yaml
    [ -z "${SLURM_VERSION}" ] && SLURM_VERSION=$(strings /opt/slurm/lib/libslurm.so | grep  -e '^VERSION'  | awk '{print $2}'  | sed -e 's?"??g')
    [ -z "${LIBFABRIC_VERSION}" ] && LIBFABRIC_VERSION=$(awk '/Version:/{print $2}' "$(find /opt/amazon/efa/ -name libfabric.pc | head -n1)" | sed -e 's?~??g' -e 's?amzn.*??g')
    export SLURM_VERSION LIBFABRIC_VERSION

    # Write the above as actual yaml file and only parse the \$.
    mkdir -p "${install_path}/etc/spack"
    ( download_packages_yaml "$(target)" )

    if [ "$(cat /tmp/packages.yaml)" != "404: Not Found" ]; then
        envsubst < /tmp/packages.yaml > "${install_path}/etc/spack/packages.yaml"
    fi
}

load_spack_at_login() {
    if [ -z "${SPACK_ROOT}" ]
    then
        case "${scheduler}" in
            slurm)
                echo -e "\n# Spack setup from Github repo spack-configs" | sudo tee -a /opt/slurm/etc/slurm.sh
                echo -e "\n# Spack setup from Github repo spack-configs" | sudo tee -a /opt/slurm/etc/slurm.csh
                echo ". ${install_path}/share/spack/setup-env.sh &>/dev/null || true" | sudo tee -a /opt/slurm/etc/slurm.sh
                echo ". ${install_path}/share/spack/setup-env.csh &>/dev/null || true" | sudo tee -a /opt/slurm/etc/slurm.csh
                ;;
            *)
                echo "WARNING: Spack will need to be loaded manually when ssh-ing to compute instances."
                echo ". ${install_path}/share/spack/setup-env.sh" | sudo tee /etc/profile.d/spack.sh
                echo ". ${install_path}/share/spack/setup-env.csh" | sudo tee /etc/profile.d/spack.csh
        esac
    fi
}


setup_spack() {
    . "${install_path}/share/spack/setup-env.sh"
    spack compiler add --scope site
    # Do not add  autotools/buildtools packages. These versions need to be managed by spack or it will
    # eventually end up in a version mismatch (e.g. when compiling gmp).
    spack external find --scope site --tag core-packages
}

if [ "3" != "$(major_version)" ]; then
    echo "ParallelCluster version $(major_version) not supported."
    exit 1
fi

setup_variables
download_spack | true
set_modules
load_spack_at_login
set_pcluster_defaults
setup_spack
echo \"*** Spack setup completed ***\"