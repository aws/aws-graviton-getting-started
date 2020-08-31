# DPDK, SPDK, ISA-L supports Graviton2

Graviton2 is optimized for data path functions like networking and storage.  Users of [DPDK](https://github.com/dpdk/dpdk) and [SPDK](https://github.com/spdk/spdk) can download and compile natively on Graviton2 following the normal installation guidelines from the respective repositories linked above. 

**NOTE**: *Though DPDK precompiled packages are available from Ubuntu but we recommend building them from source.*

SPDK relies often on [ISA-L](https://github.com/intel/isa-l) which is already optimized for Arm64 and the CPU cores in Graviton2.



## Compile DPDK from source

[DPDK official guidelines](https://doc.dpdk.org/guides/linux_gsg/build_dpdk.html) requires using *meson* and *ninja* to build from source code.

A native compilation of DPDK on top of Graviton2 will generate optimized code that take advantage of the CRC and Crypto instructions in Graviton2 cpu cores.

However, as of August 2020, some of the default RTE parameters are not optimal.

**NOTE**: Some of the installations steps call "python" which may not be valid command in modern linux distribution,  you may need to install *python-is-python3* to resolve this.

