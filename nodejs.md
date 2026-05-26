# Node.js on Graviton

Graviton is an excellent choice for running web applications with Node.js. There
are a few considerations to be aware of to get the best performance.

## Use Multiprocessing

Node.JS is fundamentally single threaded and so on an instance with more than
one vCPU (which is most of them!), the node process will leave the CPU
underutilized. There a few ways to improve this. 

1. Use a load balancer, such as Nginx, to balance incoming HTTP requests across
multiple processes. 
1. Use a built in module, `cluster` to balance the load across several forks of
the node process.

The details of how to do this is beyond the scope of this document, but can be
easily found with a few quick searches of the web.

## Use Statically Linked Builds

If you download compiled binaries of the Node from Nodejs.org, you will have
statically linked binaries. Some package managers distribute Node as a thin
`node` binary which is dynamically linked to `libnode.so` where most of the code
lives. This is fine and allows other applications to link with `libnode.so`, but
it adds a small amount of extra overhead in each function call since each one
must use an extra step of indirection to load the destination function address.
This hardly matters at all until your application reaches a threshold volume of
incoming requests and it can no longer service all requests coming in. In a
dynamically linked `node`, this threshold will be lower. This is true on on all
EC2 instance types; it is not unique to Graviton.

## Applications Using Many and Complex Regular Expressions

Older versions of V8 (prior to V8 9.4, which first shipped with Node.js
[v16.11.0](https://nodejs.org/en/blog/release/v16.11.0) in October 2021) had
a shortcoming in the JIT compiler for aarch64 that created long veneer chains
when evaluating complex regular expressions. Veneering was further optimized
for long link chains in V8 12.5 (April 2024, see [V8 commit
07ee5d4](https://github.com/v8/v8/commit/07ee5d44bfe7cc46d4e632616e7cc2d5c8c84c51)
and [Chromium bug 40261789](https://issues.chromium.org/issues/40261789)).
This has been fixed in all currently supported Node.js versions (18+). If
you are running an unsupported older version and find that regexp performance
is lower on Graviton, add `--regexp-interpret-all` to the node arguments as
a workaround, but note this flag carries a significant performance penalty
(up to 10x slower on some patterns) so upgrading to a supported Node.js LTS
release is strongly preferred.
