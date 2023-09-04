# Python on Graviton

Python is an interpreted, high-level, general-purpose programming language, with interpreters available for many operating systems and architectures, including arm64. _[Read more on Wikipedia](https://en.wikipedia.org/wiki/Python_(programming_language))_

## 1. Installing Python packages

When *pip* (the standard package installer for Python) is used, it pulls the packages from [Python Package Index](https://pypi.org) and other indexes. To ensure you
can install binary packages from [Python Package Index](https://pypi.org), make sure to update your pip installation to a new enough version \(>19.3\).

```
# To ensure an up-to-date pip version
sudo python3 -m pip install --upgrade pip
```

AWS is actively working to make pre-compiled packages available for Graviton. You can see a current list of the over 200 popular python packages we track nightly
for AL2 and Ubuntu for Graviton support status at our [Python wheel tester](https://geoffreyblake.github.io/arm64-python-wheel-tester/).  

In the case *pip* could not find a pre-compiled package, it automatically downloads, compiles, and builds the package from source code. 
Normally it may take a few more minutes to install the package from source code than from pre-built.  For some large packages,
it may take up to 20 minutes. In some cases, compilation may fail due to missing dependencies.  Before trying to build a python package from source, try
`python3 -m pip install --prefer-binary <package>` to attempt to install a wheel that is not the latest version.  Sometimes automated package builders
will push a release without all the wheels due to failures during a build that will be corrected at a later date.  If this is not an option, follow
the following instructions to build a python package from source.

### 1.1 Prerequisites for installing Python packages from source

For installing common Python packages from source code, we need to install the following development tools:

On **AmazonLinux2 or RedHat**:
```
sudo yum install "@Development tools" python3-pip python3-devel blas-devel gcc-gfortran lapack-devel
python3 -m pip install --user --upgrade pip
```

On **Debian/Ubuntu**:
```
sudo apt update
sudo apt-get install build-essential python3-pip python3-dev libblas-dev gfortran liblapack-dev
python3 -m pip install --user --upgrade pip
```

On all distributions, additional compile time dependencies might be needed depending on the Python modules you are trying to install.

### 1.2 Recommended versions

When adopting Graviton, it is recommended to use recent software versions as much as possible, and Python is no exception.

Python 2.7 is EOL since January the 1st 2020, it is definitely recommended to upgrade to a Python 3.x version before moving to Graviton.

Python 3.7 will reach [EOL in July, 2023](https://devguide.python.org/versions/), so when starting to port an application to Graviton, it is recommended to target at least Python 3.8.

### 1.3 Python on AL2 and RHEL 8

AL2 and RHEL 8 distribute older Pythons by default: 3.7 and 3.6 respectively.  Python 3.6 is EOL 
[since December, 2021](https://endoflife.date/python) and Python 3.7 will be EOL [on June 2023](https://endoflife.date/python).
Therefore, some package maintainers have already begun dropping support for
Python 3.6 and 3.7 by omitting prebuilt wheels published to [pypi.org](https://pypi.org).
For some packages, it is still possible to use the default Python by using the distribution
from the package manager. For example `numpy` no longer publishes Python 3.6 wheels,
but can be installed from the package manager: `yum install python3-numpy`.

Another option is to use Python 3.8 instead of the default Python pacakge. You can
install Python 3.8 and pip: `yum install python38-pip`. Then use pip to install
the latest versions of packages: `pip3 install numpy`.  On AL2, you will need to use `amazon-linux-extras enable python3.8` to expose Python 3.8 packages.

Some common Python packages that are distributed by the package manager are:
1. python3-numpy
2. python3-markupsafe
3. python3-pillow

To see a full list run: `yum search python3`


### Python wheel glibc requirements

Some python wheel packages installed with `pip` require newer libc versions implicitly and will fail to import properly in some cases with a similar
error message as below:

```
ImportError: /lib64/libm.so.6: version `GLIBC_2.27' not found
```

This can be a problem on distributions such as Amazon Linux 2 that ship with a relatively old glibc (v2.26 in case of Amazon Linux 2).
This happens because  `pip` does a simple string match on the wheel filename to determine if a wheel will be compatible with the system.
In these cases, it is recommended to first identify if a version of the package is available through the distro's package manager,
install an older version of the package if able, or finally upgrade to a distro that uses a newer glibc -- such as AL2023, Ubuntu 20.04, or Ubuntu 22.04.


## 2. Scientific and numerical application (NumPy, SciPy, BLAS, etc)

Python relies on native code to achieve high performance.  For scientific and
numerical applications NumPy and SciPy provide an interface to high performance
computing libraries such as ATLAS, BLAS, BLIS, OpenBLAS, etc.  These libraries
contain code tuned for Graviton processors.

It is recommended to use the latest software versions as much as possible. If the latest
version migration is not feasible, please ensure that it is at least the minimum version
recommended below because multiple fixes related to data precision and correctness on
aarch64 went into OpenBLAS between v0.3.9 and v0.3.17 and the below SciPy and NumPy versions
upgraded OpenBLAS from v0.3.9 to OpenBLAS v0.3.17.

OpenBLAS:  >= v0.3.17
SciPy: >= v1.7.2
NumPy: >= 1.21.1

Both [SciPy>=1.5.3](https://pypi.org/project/scipy/1.5.3/#files) and [NumPy>=1.19.0](https://pypi.org/project/numpy/1.19.0/#files)
vend binary wheel packages for Aarch64, but if you need better performance, then
compiling the best performance numerical library is an option.  To do so, follow the below instructions.


### 2.1 BLIS may be a faster BLAS

The default SciPy and NumPy binary installations with `pip3 install numpy scipy`
are configured to use OpenBLAS.  The default installations of SciPy and NumPy
are easy to setup and well tested.

Some workloads will benefit from using BLIS. Benchmarking SciPy and NumPy
workloads with BLIS might allow to identify additional performance improvement.

### 2.2 Install NumPy and SciPy with BLIS on Ubuntu and Debian

On Ubuntu and Debian `apt install python3-numpy python3-scipy` will install NumPy
and SciPy with BLAS and LAPACK libraries. To install SciPy and NumPy with BLIS
and OpenBLAS on Ubuntu and Debian:
```
sudo apt -y install python3-scipy python3-numpy libopenblas-dev libblis-dev
sudo update-alternatives --set libblas.so.3-aarch64-linux-gnu \
    /usr/lib/aarch64-linux-gnu/blis-openmp/libblas.so.3
```

To switch between available alternatives:

```
sudo update-alternatives --config libblas.so.3-aarch64-linux-gnu
sudo update-alternatives --config liblapack.so.3-aarch64-linux-gnu
```

### 2.3 Install NumPy and SciPy with BLIS on AmazonLinux2 (AL2) and RedHat

Prerequisites to build SciPy and NumPy with BLIS on arm64 AL2 and RedHat:
```
# Install AL2/RedHat prerequisites
sudo yum install "@Development tools" python3-pip python3-devel blas-devel gcc-gfortran

# Install BLIS
git clone https://github.com/flame/blis $HOME/blis
cd $HOME/blis;  ./configure --enable-threading=openmp --enable-cblas --prefix=/usr cortexa57
make -j4;  sudo make install

# Install OpenBLAS
git clone https://github.com/xianyi/OpenBLAS.git $HOME/OpenBLAS
cd $HOME/OpenBLAS
make -j4 BINARY=64 FC=gfortran USE_OPENMP=1 NUM_THREADS=64
sudo make PREFIX=/usr install
```

To build and install NumPy and SciPy with BLIS and OpenBLAS:
```
git clone https://github.com/numpy/numpy/ $HOME/numpy
cd $HOME/numpy;  pip3 install .

git clone https://github.com/scipy/scipy/ $HOME/scipy
cd $HOME/scipy;  pip3 install .
```

When NumPy and SciPy detect the presence of the BLIS library at build time, they
will use BLIS in priority over the same functionality from BLAS and
OpenBLAS. OpenBLAS or LAPACK libraries need to be installed along BLIS to
provide LAPACK functionality.  To change the library dependencies, one can set
environment variables `NPY_BLAS_ORDER` and `NPY_LAPACK_ORDER` before building numpy
and scipy. The default is:
`NPY_BLAS_ORDER=mkl,blis,openblas,atlas,accelerate,blas` and
`NPY_LAPACK_ORDER=mkl,openblas,libflame,atlas,accelerate,lapack`.

### 2.4 Testing NumPy and SciPy installation

To test that the installed NumPy and SciPy are built with BLIS and OpenBLAS, the
following commands will print native library dependencies:
```
python3 -c "import numpy as np; np.__config__.show()"
python3 -c "import scipy as sp; sp.__config__.show()"
```

In the case of Ubuntu and Debian these commands will print `blas` and `lapack`
which are symbolic links managed by `update-alternatives`.

### 2.5 Improving BLIS and OpenBLAS performance with multi-threading

When OpenBLAS is built with `USE_OPENMP=1` it will use OpenMP to parallelize the
computations.  The environment variable `OMP_NUM_THREADS` can be set to specify
the maximum number of threads.  If this variable is not set, the default is to
use a single thread.

To enable parallelism with BLIS, one needs to both configure with
`--enable-threading=openmp` and set the environment variable `BLIS_NUM_THREADS`
to the number of threads to use, the default is to use a single thread.

### 2.6 Graviton support in Conda / Anaconda
Anaconda is a distribution of the Python and R programming languages for scientific computing, that aims to simplify package management and deployment.

Anaconda has announced [support for AWS Graviton on May 14, 2021](https://www.anaconda.com/blog/anaconda-aws-graviton2).

Instructions to install the full Anaconda package installer can be found at https://docs.anaconda.com/anaconda/install/graviton2/ .

Anaconda also offers a lightweight version called [Miniconda](https://docs.conda.io/en/latest/miniconda.html) which is a small, bootstrap version of Anaconda that includes only conda, Python, the packages they depend on, and a small number of other useful packages, including pip, zlib and a few others.

Here is an example on how to use it to install [numpy](https://numpy.org/) and [pandas](https://pandas.pydata.org/) for Python 3.9.

The first step is to install conda:
```
$ wget https://repo.anaconda.com/miniconda/Miniconda3-py39_4.10.3-Linux-aarch64.sh
$ chmod a+x Miniconda3-py39_4.10.3-Linux-aarch64.sh
$ ./Miniconda3-py39_4.10.3-Linux-aarch64.sh
```

Once installed, you can either use the `conda` command directly to install packages, or write an environment definition file and create the corresponding environment.

Here's an example to install [numpy](https://numpy.org/) and [pandas](https://pandas.pydata.org/) (`graviton-example.yml`):
```
name: graviton-example
dependencies:
  - numpy
  - pandas
```

The next step is to instantiate the environment from that definition:
```
$ conda env create -f graviton-example.yml
```

## 3. Machine Learning Python packages


### 3.1 PyTorch

```
pip install numpy
pip install torch torchvision
```
### 3.2 TensorFlow

```
pip install tensorflow-cpu-aws
```
### 3.3 DGL

Make sure Pytorch is installed,  if not, follow [Pytorch installation steps](#41-pytorch)

On **Ubuntu**:

Follow the [install from source](https://github.com/dmlc/dgl/blob/master/docs/source/install/index.rst#install-from-source) instructions.


### 3.4 Sentencepiece

[Sentencepiece>=1.94 now has pre-compiled binary wheels available for Graviton](https://pypi.org/project/sentencepiece/0.1.94/#history).

### 3.5	Morfeusz

On **Ubuntu**:

```
# download the source
wget http://download.sgjp.pl/morfeusz/20200913/morfeusz-src-20200913.tar.gz
tar -xf morfeusz-src-20200913.tar.gz
cd Morfeusz/
sudo apt install cmake zip build-essential autotools-dev \
    python3-stdeb python3-pip python3-all-dev python3-pyparsing devscripts \
    libcppunit-dev acl  default-jdk swig python3-all-dev python3-stdeb
export JAVA_TOOL_OPTIONS=-Dfile.encoding=UTF8
mkdir build
cd build
cmake ..
sudo make install
sudo ldconfig -v
sudo PYTHONPATH=/usr/local/lib/python make install-builder
```

If you run into issue with the last command (_make install-builder_), please try:
```
sudo PYTHONPATH=`which python3` make install-builder
```

## 4. Other Python packages

### confluent_kafka

First, install librdkafka and its development libraries by following the
instructions on [this page](software/librdkafka.md). As part of this process,
you will install `gcc`, `pip` for Python3, and Python development headers.

Once complete, you can then install the `confluent_kafka` module directly from
source:

```
python3 -m pip install --user --no-binary confluent-kafka confluent-kafka
```

### open3d

Open3d required glibc version 2.27 or higher. Amazon Linux 2 includes glibc 2.26, which is not sufficient. In order to
use open3d, please use Amazon Linux 2023 or later, Ubuntu Bionic (18.04) or later, or another supported distribution.
See [open3d documentation](http://www.open3d.org/docs/release/getting_started.html) for more information.

