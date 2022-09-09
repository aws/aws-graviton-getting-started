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
