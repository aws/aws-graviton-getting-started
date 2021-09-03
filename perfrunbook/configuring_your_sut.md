# Configuring your system-under-test environment

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

This section documents multiple checklists to use to verify your Graviton System-under-test (SUT) is up-to-date and as code-equivalent as possible to the systems and instances you are comparing against.   Please perform these tests on each SUT to vet your experimental setup and eliminate as many potential unknown variables as possible.

## Initial system-under-test checks

If you have more than one SUT, first verify there are no major differences in setup:

1. Check all instances are running the same OS distribution:
  ```bash
  ## AL2
  %> sudo cat /etc/system-release
  Amazon Linux release 2 (Karoo)
    
  ## Ubuntu
  %> sudo lsb_release -a
  Distributor ID: Ubuntu
  Description:    Ubuntu 20.04.2 LTS
  Release:        20.04
  Codename:       focal
  ```
2. Update your system packages to the latest for your AMI to pull in the most recent security and bug fixes. 
  ```bash
  ## AL2
  %> sudo yum update
    
  ## Ubuntu
  %> sudo apt-get upgrade
  ```
3. Check all instances are running the same major and minor kernel versions.  It is recommended to upgrade to the newest kernel available to bring in the latest security and bug fixes.
  ```bash
  # Example output on x86 SUT
  %> uname -r
  4.14.219-161.340.amzn2.x86_64
    
  # Example output on Graviton2 SUT
  %> uname -r
  5.10.50-45.132.amzn2.aarch64
    
  # To upgrade on AL2 for example to Linux 5.10:
  %> sudo amazon-linux-extras enable kernel-5.10
  %> sudo yum install kernel
    
  # To update on Ubuntu
  %> sudo apt-cache search "linux-image"
  # Find the newest kernel available
  %> sudo apt-get install linux-image-<version>-generic
    
  # Restart your instance
  %> sudo reboot now
  ```
4. Check for suspicious error, exception or warning messages in system and service logs that are different between instances.
  ```bash
  # Grep in all log locations, on most systems this is /var/log, but there
  # may be additional log locations.
  %> egrep -Rni "ERROR|WARN|EXCEPTION" /var/log/*
  # Example output
  exampleservice.log:1000:`LoadError: Unsupported platform: unknown-linux
  ...
  ``` 
5.  Check per process limitations on all systems under test are identical by running:
  ```bash
  %> ulimit -a
  # Pay special attention to stacksize and open files limits
  # If they are different, they can be changed temporarily.
  # For example to change number of files allowed open:
  %> ulimit -n 65535
    
  # Permanently changing the values requires editing /etc/security/limits.conf
  ```
6.  Check ping latencies to load generators and downstream services that will be accessed from each system-under-test and verify latencies are similar.   A different of +/-50us is acceptable, differences of >+/-100us can adversely affect testing results.  We recommend putting all testing environment instances inside a [cluster placement group](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster), or at a minimum confirm that all instances are in the same subnet (i.e. us-east-1a).
7.  Check the instance types used and verify IO devices are setup equivalently between the SUTs. I.e. m5d\.metal and m6gd\.metal have different disk configurations that may lead to differing performance measurements if your service is sensitive to disk performance. 
8. We recommend using instances set to [**dedicated tenancy**](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/dedicated-instance.html) first to establish a baseline for performance variance for your test application.  Knowing this baseline will help interpret results when testing on instances that are set to **default** tenancy.

## Check for missing binary dependencies

Libraries for Python or Java can link in binary shared objects to provide enhanced performance.  The absence of these shared object dependencies does not prevent the application from running on Graviton2, but the CPU will be forced to use a slow code-path instead of the optimized paths.  Use the checklist below to verify the same shared objects are available on all platforms.

1. JVM based languages — Check for the presence of binary shared objects in the installed JARs and compare between Graviton2 and x86.
  ```bash
  %> cd ~/aws-getting-started-guide/perfrunbook/utilities
  %> sudo ./find_and_list_jar_with_so.sh
  # Example output ...
  # jars may place the shared object in different folders for the arch support
  ./com/sun/jna/linux-x86/libjnidispatch.so
  ./com/sun/jna/linux-x86-64/libjnidispatch.so
  ./com/sun/jna/linux-arm/libjnidispatch.so
  ./com/sun/jna/linux-armel/libjnidispatch.so
  ./com/sun/jna/linux-aarch64/libjnidispatch.so
  ./com/sun/jna/linux-ppc/libjnidispatch.so
  ./com/sun/jna/linux-ppc64le/libjnidispatch.so
  # ... or append a suffix declaring the arch support
  ./META-INF/native/libnetty_tcnative_linux_x86_64.so
  ./META-INF/native/libnetty_tcnative_linux_aarch64.so
  ./META-INF/native/libnetty_transport_native_epoll_x86_64.so
  ./META-INF/native/libnetty_transport_native_epoll_aarch_64.so
  # ... or very old jars will be x86 only if linux64/32 is specified
  ./META-INF/native/linux64/libjansi.so
  ./META-INF/native/linux32/libjansi.so
  ``` 
2. Python — Check for the presence of binary shared objects in your python version’s `site-packages` locations and compare between Graviton2 and x86: 
  ```bash
  %> cd ~/aws-getting-started-guide/perfrunbook/utilites
  %> sudo ./find_and_list_pylib_with_so.sh 3.7 # takes python version as arg
  # Example output ...
  # ... Graviton2
  ./numpy/core/_multiarray_tests.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_struct_ufunc_tests.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_rational_tests.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_simd.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_multiarray_umath.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_umath_tests.cpython-37m-aarch64-linux-gnu.so
  ./numpy/core/_operand_flag_tests.cpython-37m-aarch64-linux-gnu.so
  # ... x86
  ./numpy/core/_operand_flag_tests.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_simd.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_rational_tests.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_umath_tests.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_multiarray_tests.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_multiarray_umath.cpython-37m-x86_64-linux-gnu.so
  ./numpy/core/_struct_ufunc_tests.cpython-37m-x86_64-linux-gnu.so
  ```  
3. If you find any missing libraries, check for newer versions at:
    1. [https://mvnrepository.com](https://mvnrepository.com/)
    2. [https://pypi.org](https://pypi.org/)
    3. Check the [AWS Graviton getting started guide](https://github.com/aws/aws-graviton-getting-started) for additional guidance on known good versions of common libraries.
4. Upgrade your dependencies to newer versions if able to get added support, but also security and bug fixes.

## Check native application build system and code

For native compiled components of your application, proper compile flags are essential to make sure Graviton2’s hardware features are being fully taken advantage of.  Follow the below checklist:

1. Verify equivalent code optimizations are being made for Graviton as well as x86.  For example with C/C++ code built with GCC, make sure if builds use `-O3` for x86, that Graviton builds also use that optimization and not some basic debug setting like just `-g`.
2. Confirm when building for Graviton that **one of the following flags** are added to the compile line for GCC/LLVM12+ to ensure using Large System Extension instructions when able to speed up atomic operations.
    1. Use `-moutline-atomics` for code that must run on Graviton1 and Graviton2
    2. Use `-march=armv8.2a -mcpu=neoverse-n1` for code that will run on Graviton2 and other modern Arm platforms
3. When building natively for Rust, ensure that `RUSTFLAGS` is set to **one of the following flags**
    1. `export RUSTFLAGS="-Ctarget-features=+lse"` for code that will run on Graviton2 and earlier platforms that support LSE (Large System Extension) instructions.
    2. `export RUSTFLAGS="-Ctarget-cpu=neoverse-n1"` for code that will only run on Graviton2 and later platforms.
4. Check for the existence of assembly optimized on x86 with no optimization on Graviton.  For help with porting optimized assembly routines, see [Section 6](./optimization_recommendation.md).
  ```bash
  # Check for any .S/.s files in a C/C++ application
  find . -regex '.*\.[sS]' -type f -print
    
  # Check for any inline assembly in files
  egrep -Rn "__asm__|asm" *
    
  # Search for intrinsics usage in the code base
  egrep -Rn "arm_neon.h|mmintrin.h" *
  ```

## Check application configuration settings

Finally as part of checking the systems-under-test verify the application is configured properly on startup.

1. Check that any startup scripts that attempt to do thread-pinning via `taskset` or `CGroups` are not making assumptions about the presence of SMT that is common on x86 servers.  There are no threads on Graviton servers and no assumptions about threads needs to be made.  This may be present as code taking the number of CPUs in the system and dividing by two, i.e. for shell run scripts you might see: `let physical_cores=$(nproc) / 2`
2. Check daemon start scripts provide enough resources to the service as it starts on Graviton, such as specifying `LimitNOFILE`, `LimitSTACK`, or `LimitNPROC` in a systemd start script.
3. Check for debug flags in application start-up scripts that are enabled but should be disabled. Such as: `-XX:-OmitStackTraceInFastThrow` for Java which logs and generates stack traces for all exceptions, even if they are not considered fatal exceptions.
4. If using the Java Virtual Machine to execute your service, ensure it is a recent version based off at least JDK11. We recommend using [Corretto11](https://docs.aws.amazon.com/corretto/latest/corretto-11-ug/downloads-list.html) or [Corretto15](https://docs.aws.amazon.com/corretto/latest/corretto-15-ug/downloads-list.html).  Corretto is a free and actively maintained OpenJDK distribution that contains optimizations for AWS Graviton based instances.


