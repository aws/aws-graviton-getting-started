# Rust on Graviton

Rust is supported on Linux/arm64 systems as a tier1 platform along side x86.

### Large-System Extensions (LSE)

The Graviton2 processor in C6g[d], C6gn, M6g[d], R6g[d], T4g, X2gd, Im4gn, Is4gen, 
and G5g instances has support for the Armv8.2 instruction set.  Armv8.2 
specification includes the large-system extensions (LSE) introduced in Armv8.1. LSE
provides low-cost atomic operations:

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

When Rust is configured to use LLVM 12 or newer, target feature
`+outline-atomics` is available.  Outline-atomics produces a binary containing
two versions of the atomic operation following the hardware capabilities.  When
the code executes on a newer hardware such as Graviton2, the processor will
execute LSE instructions; when the code executes on older hardware without LSE
instructions, the processor will execute Armv8.0 atomics instructions.

Rust 1.57 (release on December 2, 2021) enables by default outline-atomics
target feature when compiling for arm64-linux with LLVM 12 or newer.  When using
older Rust releases, outline-atomics target feature can be enabled with
```
export RUSTFLAGS="-Ctarget-feature=+outline-atomics"
```
