# Quick introduction to benchmarking

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

When designing an experiment to benchmark Graviton2 against another instance type, it is key to remember the below 2 guiding principles:

1. Always define a specific question to answer with your benchmark
2. Control your variables and unknowns within the benchmark environment

### Ask the right question

The first bullet point is the most important; without a specific question to answer, any benchmarking data gathered will be hard to interpret and provide limited conclusions.  For example, a poor question is this:

> “How do Graviton instances compare to x86 based instances on Java?”

This type of question is impossible to answer.  The primary problem is that there are too many variables present in that simple question, for instance: What Java version? What application? What load? What is the metric of interest?  What OS distribution? What software dependencies?  Because the scope of the question is so vast, any data gathered and any conclusion made from it will be immediately questioned and discarded as simple outliers from outside reviewers.  Leading to a great deal of wasted effort. 

Instead formulate the question as tightly as possible:

> “How does a Graviton instance’s request throughput compare to current instances on my Java application at a P99 of 10ms for a mix of 60% GETS and 40% PUTS on Ubuntu 20.04LTS?

This question is narrower in scope and defines a specific experiment that can be answered conclusively without a mountain of data.  Always ask specific questions so as to get specific answers and conclusions.  

### Less moving parts

The second bullet follows from the first.  Once a specific question is posed for an experiment, then it is required to account for variables in the experimental environment as much as possible.   

Variables for benchmarking an application can include: 
- OS distribution
- Linux kernel version
- software dependency versions
- instance size used
- network placement group configuration
- application setup
- background daemons
- traffic profiles
- load generator behavior 
- etc.  

The more variables that are controlled for, more specific questions can be answered about the system.  Such as, if an instance is over-provisioned with disk and network bandwidth and it is known that this configuration will not pose a bottleneck, then experiments can be derived to test only the capability of the CPU and DRAM in the system.  

It is recommended before running an experiment to fully understand all the ways the environment can vary and determine how and if they can be controlled for.  The above list can be used as a starting point.  Having a thorough understanding of all the variables present in an experiment will enable better analysis of results and reduce the number of experimental runs needed before settling on the final configurations that will enable performance debugging.  

Now that you have a specific question to answer, and have a basic understanding of the variables to control for, lets get started with defining how to test your application to assist with debugging performance in [Section 2.](./defining_your_benchmark.md)



