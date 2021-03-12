# Rust on Graviton

Rust is supported on Linux/arm64 systems as a tier1 platform along side x86.

### Large-System Extensions (LSE)

The Graviton2 processor in C6g, M6g, and R6g instances has support for the
Armv8.2 instruction set.  Armv8.2 specification includes the large-system
extensions (LSE) introduced in Armv8.1. LSE provides low-cost atomic operations.
LSE improves system throughput for CPU-to-CPU communication, locks, and mutexes.
The improvement can be up to an order of magnitude when using LSE instead of
load/store exclusives. LSE can be enabled in Rust and we've seen cases on 
larger machines where performance is improved by over 3x by setting the `RUSTFLAGS`
environment variable and rebuilding your project.

```
export RUSTFLAGS="-Ctarget-feature=+lse"
cargo build --release
```

If you're running only on Graviton2 or newer hardware you can also enable other
instructions by setting the cpu target as well:

```
export RUSTFLAGS="-Ctarget-cpu=neoverse-n1"
cargo build --release
```


