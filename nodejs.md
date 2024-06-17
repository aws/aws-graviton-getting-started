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

A shortcoming in the just in time compiler in V8 for aarch64 creates a long link
chain of veeneers when evaluating complex regular expressions. A new version of
V8 addresses this, but it has not yet been merged into NodeJS main. If your
application relies heavily on regular expression performance AND you find that
the performance is lower on Graviton, try adding `--regexp-interpret-all` to
the node arguments to force V8 to interpret rather than compile regular
expressions.
