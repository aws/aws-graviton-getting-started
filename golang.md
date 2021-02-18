# Go on Graviton

Go is a statically typed, compiled programming language originally designed at Google. Go supports arm64 out of the box, and available in all common distributions, with recent changes that improve performance, so make sure to use the latest version of the Go compiler and toolchain.

Here are some noteworthy performance upgrades:

## Go 1.16 \[released 2021/02/16\]
The main implementation of the Go compiler, [golang/go](https://github.com/golang/go), has improved
performance on Arm with couple of changes listed below. Building your project with Go 1.16 will give you these improvements:

 * [ARMv8.1-A Atomics instructions](https://go-review.googlesource.com/c/go/+/234217), which dramatically improve mutex fairness and speed on Graviton 2, and modern Arm core with v8.1 and newer instruction set.
 * [copy performance improvements](https://go-review.googlesource.com/c/go/+/243357), especially when the addresses are unaligned.

## Recently updated packages
Changes to commonly used packages that improve performance on Arm can make a noticeable difference in
some cases. Here is a partial list of packages to be aware of.

Package   | Version   | Improvements
----------|-----------|-------------
[Snappy](https://github.com/golang/snappy) | as of commit [196ae77](https://github.com/golang/snappy/commit/196ae77b8a26000fa30caa8b2b541e09674dbc43) | assembly implementations of the hot path functions were ported from amd64 to arm64

