# Assembly Optimization Guide for Graviton Arm64 Processors

## Introduction

This document is a reference for software developers who want to optimize code
for Graviton Arm64 processors at the assembly level. Some of the documented
transforms could be applied to optimize code written in higher level languages
like C or C++, and in that respect this document is not restrictive to assembly
level programming. This guide isn’t intended cover every aspect of writing in
assembly, such as assembler syntax or ABI details.

The code patterns in this document could also be useful to spot inefficient code
generated for the hot code. Profilers such as Linux perf allow the inspection of
the assembly level code. During the review of the hot code, software developers
can reference this guide to find better ways to optimize inner loops.

Some techniques for writing optimized assembly:
1. Be aware of instruction level parallelism

We will be adding more sections to this document soon, so check back!

## Instruction Level Parallelism
When writing in C, or any higher level language, the programmer writes a sequence
of statements which are presumed to execute in strict sequence. In the following
example, each statement logically occurs after the previous one.

```c
int foo (int a, int b, int c)
{
    if (c < 0) {
        int d = a + b;
        return d;
    } else {
        int e = a * b;
        return e;
    }
}
```

However when we compile this code with gcc version 7.3 with `-O1`, this is the output:
```
foo(int, int, int):
    add     w3, w0, w1
    mul     w0, w0, w1
    cmp     w2, 0
    csel    w0, w0, w3, ge
    ret
```

Here we can see the add and the multiply instruction are executed independently
of the result of `c < 0`. The compiler knows that the CPU can execute these
instructions in parallel. If we use the machine code analyzer from the LLVM
project, we can can see what is happening. We will use Graviton2 as our target
platform, which uses the Neoverse-N1 core.

`llvm-mca -mcpu=neoverse-n1 -timeline -iterations 1 foo.s`
```
...
Timeline view:
Index     012345

[0,0]     DeER .   add  w3, w0, w1
[0,1]     DeeER.   mul  w0, w0, w1
[0,2]     DeE-R.   cmp  w2, #0
[0,3]     D==eER   csel w0, w0, w3, ge
[0,4]     DeE--R   ret
...
```

In this output we can see that all five instructions from this function are decoded
in parallel in the first cycle. Then in the second cycle the instructions for which
all dependencies are already resolved begin executing. There is only one instruction
which has dependencies: the conditional select, `csel`. The four remaining
instructions all begin executing, including the `ret` instruction at the end. In
effect, nearly the entire C function is executing in parallel. The
`csel` has to wait for the result of the comparison instruction to check
`c < 0` and the result of the multiplication. Even the return has
completed by this point and the CPU front end has already decoded
instructions in the return path and some of them will already be
executing as well.

It is important to understand this when writing assembly. Instructions
do not execute in the order they appear. Their effects will be logically
sequential, but execution order will not be.

When writing assembly for arm64 or any platform, be aware that the CPU has more
than one pipeline of different types. The types and quantities are outlined in
the Software Optimization Guide, often abbreviated as SWOG. The guide
for each Graviton processor is linked from the [main page of this
technical guide](README.md). Using this knowledge, the programmer can arrange instructions of
different types next to each other to take advantage of instruction level
parallelism, ILP. For example, interleaving load instructions with vector or
floating point instructions can keep both pipelines busy.

Next we will discuss breaking data dependencies as a technique for improving performance. Check back
again soon!