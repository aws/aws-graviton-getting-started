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
1. [Be aware of instruction level parallelism](#instruction-level-parallelism)
1. [Split Data Dependency Chains](#split-data-dependency-chains)


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


## Split Data Dependency Chains

As we saw in the last section, Graviton has multiple pipelines or execution units which can execute instructions. The instructions may execute in parallel if all of the input dependencies have been met but a series of instructions each of which depend on a result from the previous one will not be able to efficiently utilize the resources of the CPU.

For example, a simple C function which takes 64 signed 8-bit integers and adds them all up into one value could be implemented like this:

```
int16_t add_64(int8_t *d) {
    int16_t sum = 0;
    for (int i = 0; i < 64; i++) {
        sum += d[i];
    }
    return sum;
}
```

We could write this in assembly using NEON SIMD instructions like this:

```
add_64_neon_01:
    ld1     {v0.16b, v1.16b, v2.16b, v3.16b} [x0]   // load all 64 bytes into vector registers v0-v3
    movi    v4.2d, #0                               // zero v4 for use as an accumulator
    saddw   v4.8h, v4.8h, v0.8b                     // add bytes 0-7 of v0 to the accumulator
    saddw2  v4.8h, v4.8h, v0.16b                    // add bytes 8-15 of v0 to the accumulator
    saddw   v4.8h, v4.8h, v1.8b                     // ...
    saddw2  v4.8h, v4.8h, v1.16b
    saddw   v4.8h, v4.8h, v2.8b
    saddw2  v4.8h, v4.8h, v2.16b
    saddw   v4.8h, v4.8h, v3.8b
    saddw2  v4.8h, v4.8h, v3.16b
    addv    h0, v4.8h                               // horizontal add all values in the accumulator to h0
    fmov    w0, h0                                  // copy vector registor h0 to general purpose register w0
    ret                                             // return with the result in w0
```

In this example, we use a signed add-wide instruction which adds the top and bottom of each register to v4 which is used to accumulate the sum. This is the worst case for data dependency chains because every instruction depends on the result of the previous one which will make it impossible for the CPU to achieve any instruction level parallelism. If we use `llvm-mca` to evaluate it we can see this clearly.

```
Timeline view:
                    0123456789
Index     0123456789          0123456

[0,0]     DeeER.    .    .    .    ..   movi    v4.2d, #0000000000000000
[0,1]     D==eeER   .    .    .    ..   saddw   v4.8h, v4.8h, v0.8b
[0,2]     D====eeER .    .    .    ..   saddw2  v4.8h, v4.8h, v0.16b
[0,3]     D======eeER    .    .    ..   saddw   v4.8h, v4.8h, v1.8b
[0,4]     D========eeER  .    .    ..   saddw2  v4.8h, v4.8h, v1.16b
[0,5]     D==========eeER.    .    ..   saddw   v4.8h, v4.8h, v2.8b
[0,6]     D============eeER   .    ..   saddw2  v4.8h, v4.8h, v2.16b
[0,7]     D==============eeER .    ..   saddw   v4.8h, v4.8h, v3.8b
[0,8]     D================eeER    ..   saddw2  v4.8h, v4.8h, v3.16b
[0,9]     D==================eeeeER..   addv    h0, v4.8h
[0,10]    D======================eeER   fmov    w0, h0
[0,11]    DeE-----------------------R   ret
```


One way to break data dependency chains is to use commutative property of addition and change the order which the adds are completed. Consider the following alternative implementation which makes use of pairwise add instructions.

```
add_64_neon_02:
    ld1     {v0.16b, v1.16b, v2.16b, v3.16b} [x0]

    saddlp  v0.8h, v0.16b                   // signed add pairwise long
    saddlp  v1.8h, v1.16b
    saddlp  v2.8h, v2.16b
    saddlp  v3.8h, v3.16b                   // after this instruction we have 32 16-bit values

    addp    v0.8h, v0.8h, v1.8h             // add pairwise again v0 and v1
    addp    v2.8h, v2.8h, v3.8h             // now we are down to 16 16-bit values

    addp    v0.8h, v0.8h, v2.8h             // 8 16-bit values
    addv    h0, v4.8h                       // add 8 remaining values across vector
    fmov    w0, h0

    ret
```

In this example the first 4 instructions after the load can execute independently and then the next 2 are also independent of each other.  However, the last 3 instructions do have data dependencies on each other. If we take a look with `llvm-mca` again, we can see that this implementation takes 17 cycles (excluding the initial load instruction common to both implementations) and the original takes 27 cycles.

```
Timeline view:
                    0123456
Index     0123456789

[0,0]     DeeER.    .    ..   saddlp    v0.8h, v0.16b
[0,1]     DeeER.    .    ..   saddlp    v1.8h, v1.16b
[0,2]     D=eeER    .    ..   saddlp    v2.8h, v2.16b
[0,3]     D=eeER    .    ..   saddlp    v3.8h, v3.16b
[0,4]     D==eeER   .    ..   addp      v0.8h, v0.8h, v1.8h
[0,5]     D===eeER  .    ..   addp      v2.8h, v2.8h, v3.8h
[0,6]     D=====eeER.    ..   addp      v0.8h, v0.8h, v2.8h
[0,7]     .D======eeeeeER..   addv      h0, v0.8h
[0,8]     .D===========eeER   fmov      w0, h0
[0,9]     .DeE------------R   ret
```


Next we will discuss modulo scheduling. Check back again soon!
