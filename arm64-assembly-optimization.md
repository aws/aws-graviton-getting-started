# Assembly Optimization Guide for Graviton Arm64 Processors

## Introduction

This document is a reference for software developers who want to optimize code
for Graviton Arm64 processors at the assembly level. Some of the documented
transforms could be applied to optimize code written in higher level languages
like C or C++, and in that respect this document is not restrictive to assembly
level programming.

The code patterns in this document could also be useful to spot inefficient code
generated for the hot code. Profilers such as Linux perf allow the inspection of
the assembly level code. During the review of the hot code, software developers
could reference this guide to find better ways to optimize inner loops.

## Instruction selection and scheduling

ARM provides several Software Optimization Guides (SWOG) for each CPU:
- [Graviton2 - Neoverse-N1 SWOG](https://developer.arm.com/documentation/swog309707/a/)
- [Graviton3 - Neoverse-V1 SWOG](https://developer.arm.com/documentation/PJDOC-466751330-9685/0101/)

The SWOG documents for each instruction the latency (number of cycles it takes
to finish the execution of an instruction) and the throughput (the number of
similar instructions that can execute in parallel.) The SWOG also documents the
execution units that can execute an instruction. The information provided by the
SWOG is sometimes encoded in compilers (GCC and LLVM) under the form of specific
tuning flags for different CPUs. Tuning flags allow compilers to produce a good
instruction scheduling and a good instruction selection.

LLVM has a tool [llvm-mca](https://www.llvm.org/docs/CommandGuide/llvm-mca.html)
that allows software developers to see on their input assembly code how the
compiler reasons about the execution of instructions by a specific processor.

## Splitting data dependence chains

To increase instruction level parallelism it is possible to duplicate
computations. The redundant computations can execute in parallel as they belong
to different dependence chains.

For example, it is possible to issue several loads to break data dependent
instructions.  The data becomes available earlier and avoids stalls due to data
dependences.  Instead of using a load and an extract instructions:

```
ld1  {v0.16b}, [x1]
// v0 is available after ld1 finishes execution
ext  v1.16b, v0.16b, v0.16b, #1   // x1 + 1
// v1 is available only after ld1 and ext finish execution
```
we can issue two independent loads that can execute in parallel:
```
ld1  {v0.16b}, [x1]
ld1  {v1.16b}, [x1, #1]     // x1 + 1
// v0 and v1 are available after the two independent ld1 instructions finish execution
// Both Graviton2 and Graviton3 will execute the two loads in parallel.
```

## Modulo scheduling

Data loaded for iteration `i` can be used in the next iteration `i + 1` by
keeping it in a register.  The registers used for modulo scheduling are pre-load
before the loop starts, and each iteration saves the data needed in the next
iteration in those registers.

## Optimizing a dot product by a constant vector

When the data is known ahead of execution time, it is possible to specialize the
code based on the data. For example in the x265 encoder a filter is using the
constant coefficients that need to be multiplied by data read from memory and
then summing up all the results. The C code does the following:

```
const int16_t g_lumaFilter[4][NTAPS_LUMA] =
{
    {  0, 0,   0, 64,  0,   0, 0,  0 },
    { -1, 4, -10, 58, 17,  -5, 1,  0 },
    { -1, 4, -11, 40, 40, -11, 4, -1 },
    {  0, 1,  -5, 17, 58, -10, 4, -1 }
};
[...]
    const int16_t* coeff = g_lumaFilter[coeffIdx];
    for (int row = 0; row < blkheight; row++) {
        for (int col = 0; col < width; col++) {
            int sum;
            sum  = src[col + 0] * coeff[0];
            sum += src[col + 1] * coeff[1];
            sum += src[col + 2] * coeff[2];
            sum += src[col + 3] * coeff[3];
            sum += src[col + 4] * coeff[4];
            sum += src[col + 5] * coeff[5];
            sum += src[col + 6] * coeff[6];
            sum += src[col + 7] * coeff[7];
[...]
```

The C code generates 8 multiplies and 7 adds for each row in g_lumaFilter.
For g_lumaFilter[0] the assembly code only uses 1 shift left.
For g_lumaFilter[1], the assembly code only uses 4 multiplies, 1 shift left, and 6 adds:

```
//          a, b,   c,  d,  e,  f, g,  h
// .hword  -1, 4, -10, 58, 17, -5, 1,  0
    movi            v24.16b, #58
    movi            v25.16b, #10
    movi            v26.16b, #17
    movi            v27.16b, #5
[... loop logic ...]
    umull           v19.8h, v2.8b, v25.8b  // c*10
    umull           v17.8h, v3.8b, v24.8b  // d*58
    umull           v21.8h, v4.8b, v26.8b  // e*17
    umull           v23.8h, v5.8b, v27.8b  // f*5
    ushll           v18.8h, v1.8b, #2      // b*4
    sub             v17.8h, v17.8h, v19.8h // d*58 - c*10
    add             v17.8h, v17.8h, v21.8h // d*58 - c*10 + e*17
    usubl           v21.8h, v6.8b, v0.8b   // g - a
    add             v17.8h, v17.8h, v18.8h // d*58 - c*10 + e*17 + b*4
    sub             v21.8h, v21.8h, v23.8h // g - a - f*5
    add             v17.8h, v17.8h, v21.8h // d*58 - c*10 + e*17 + b*4 + g - a - f*5
```

