# Go on Graviton

Go is a statically typed, compiled programming language designed at Google. Since it is compiled
existing binaries will need to be recompiled to run on Graviton, but in general, this should just
work. Go supports arm64 out of the box and recent changes will improve performance, so make sure
to use the latest version of the Go compiler and toolchain.

## Go 1.16
The main implementation of the Go compiler, [golang/go](https://github.com/golang/go), has improved
performance on Arm. It is expected to be released in January 2021. Building your project with Go 1.16
will give you these improvements:

 * [ARMv8.1-A Atmoics instructions](https://go-review.googlesource.com/c/go/+/234217), which dramatically improve mutex fairness and speed on Graviton 2.
 * [copy performance improvements](https://go-review.googlesource.com/c/go/+/243357), especially when the addresses are unaligned

## Recently updated packages
Changes to commonly used pacakges that improve performance on Arm can make a big difference in
some cases. Here is a partial list of packages to be aware of.

Package   | Version   | Improvements
----------|-----------|-------------
[Snappy](https://github.com/golang/snappy) | as of commit [196ae77](https://github.com/golang/snappy/commit/196ae77b8a26000fa30caa8b2b541e09674dbc43) | assembly implementations of the hot path functions were ported from amd64 to arm64

