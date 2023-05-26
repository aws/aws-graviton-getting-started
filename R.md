# R on Graviton
**Introduction**

R is a free software environment for statistical computing and graphics. It compiles and runs on a wide variety of platforms (including arm64).  _[Read more on the R Project page]([(https://www.r-project.org)])(https://www.r-project.org)_.
This page is meant to discuss differences between running R on Graviton versus other platforms, not to give instructions for R in general.

## 1. Installing R
Because of its use cases, performance is a consideration for R.  For that reason, using Amazon Linux is recommended because it is regularly updated to include Graviton related optimizations.  

All instructions here are tested using the Amazon Linux distribution (specifically the 2023 version). Other than the package manager (yum/apt), they should work on other distributions as well.

As on most platforms, the easiest way to install R is using the built in package manager.

```sudo yum install R```

This will install R.  However, as is also the case on most platforms, the package manager doesn't always have the latest version.  If you need a more current version, you would need to install manually from the source.   

## 2. Installing R packages
CRAN (the default R package repository) hosts most packages as source code.  This means that installing a package using the built in package manager (install.packages) will automatically download the source and compile it for your platform. This works well on the Graviton platform because it creates the binaries you need and also lets you take advantage of processor optimizations that may be compiled in.

Packages may not install because of missing libraries.  In most cases, install.packages will show you the missing packages that provide those libraries.  If too many things scrolled by on the screen, run

```>warnings()``` 

from the R command prompt to review.

There are some packages that need to be installed a little differently on Graviton because their installation includes binary distribution.

**For example:** 

```>install.packages(c("devtools"), dependencies=TRUE) ```

will tell you that you need to first install libcurl and openssl.  For Amazon Linux, use the package names listed on the ```\* rpm:``` line.

In this case:

```
sudo yum install openssl-devel
sudo yum install libcurl-devel
```
However, one of the required packages, gert, will tell you it needs ```libgit2-devel```.  You don't see this in the installation on x86 because the gert install package includes a script that downloads a static linked binary if it doesn't find the needed library.

```libgit2-devel``` is not currently available through yum, so you need to install manually.

In order to do that, you may need two additional packages, ```cmake``` and ```git```.  **You also need to use the install prefix of /usr instead of /usr/local**

From the linux command line:
```
sudo yum install cmake
sudo yum install git
git clone https://github.com/libgit2/libgit2
cd libgit2
mkdir build && cd build
sudo cmake .. -DCMAKE_INSTALL_PREFIX=/usr
sudo cmake --build . --target install
cd ..
rm -rf libgit2
```

After that, you can return to R and run 

```>install.packages(c("devtools"), dependencies=TRUE) ```

and it should complete.

## 3. Compiled code use

Any R package or program that uses compiled code will probably need to have that code recompiled.  Refer to _[Using compiled code]([(https://cran.r-project.org/web/packages/box/vignettes/compiled-code.html)])(https://cran.r-project.org/web/packages/box/vignettes/compiled-code.html)_ on the R Project site to see examples of what compiled code use may look like.
