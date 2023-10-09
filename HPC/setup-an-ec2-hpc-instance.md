## Compile instructions on an EC2
If you are a developer who want to build and test your applications on Graviton. You can get started by launching a Ubuntu 20.04 C7g instance (4xlarge or larger) from the console. Follow the procedures below to set up the tools:
```
# get the build tools and upgrade GCC
sudo apt update -y
sudo apt install build-essential environment-modules cmake m4 zlib1g zlib1g-dev csh unzip flex -y

sudo add-apt-repository -y ppa:ubuntu-toolchain-r/test
sudo apt install -y gcc-11 g++-11 gfortran-11 -y
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 100 --slave /usr/bin/g++ g++ /usr/bin/g++-11 --slave /usr/bin/gcov gcov /usr/bin/gcov-11 --slave /usr/bin/gfortran gfortran /usr/bin/gfortran-11
```
You can check by `gcc --version` to confirm that you have gcc 11.4.0 installed.

```
# install Arm Compiler for Linux, Arm Performance Libraries under /shared
sudo mkdir -p /shared/tools/
sudo chown -R ubuntu: /shared

# check Arm's website for the latest link
cd /shared/tools
wget -O arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/23-04-1/arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar'
tar xf arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar
./arm-compiler-for-linux_23.04.1_Ubuntu-20.04/arm-compiler-for-linux_23.04.1_Ubuntu-20.04.sh \
-i /shared/arm -a --force
```

You can check if the Arm Compiler and Armpl are installed and loaded properly by the following commands:
```
source /etc/profile.d/modules.sh
module use /shared/arm/modulefiles
module av
module load acfl armpl
module list
```
You should be getting the following messages if the installation is successful.
```
Currently Loaded Modulefiles:
 1) binutils/12.2.0   2) acfl/23.04.1   3) armpl/23.04.1
```

After that, you need to install EFA driver which is not installed on an EC2 instance by default and [Open MPI](README.md#open-mpi).
```
# install EFA, Open MPI under /shared
cd /shared/tools
curl -O https://efa-installer.amazonaws.com/aws-efa-installer-1.25.0.tar.gz
tar xf aws-efa-installer-1.25.0.tar.gz
cd aws-efa-installer
sudo ./efa_installer.sh -y
```


