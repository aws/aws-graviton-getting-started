# Cross-architecture numerical validation harness

A small C++ pricing model and a comparison script for measuring how floating-point results differ when the same code runs on different CPU architectures, for example x86-64 and AWS Graviton (arm64).

The model prices one million European call options with the Black-Scholes closed form. It reports the total book value and a 64-bit fingerprint of every individual price, and can write every price to a file. The comparison script takes two such files and reports how many prices differ, by how much, and whether the differences are within tolerances you set.

This is not a benchmark suite or a pricing library. It is a way to turn the question "do the numbers change on Graviton?" into measured figures for a workload that exercises the same math functions (`log`, `exp`, `sqrt`, `erfc`) that real pricers depend on.

## Contents

| File | Purpose |
|---|---|
| `run-aws.sh` | One command: launches an x86-64 and a Graviton instance in your account, runs everything, prints the comparison, terminates. |
| `pricer.cpp` | Prices the book, prints host info, book value and fingerprint. `--dump` writes every price. |
| `compare.py` | Compares two dumps. Reports differences, optionally enforces tolerances and sets the exit code. |
| `bench.cpp` | Optional throughput benchmark, only run with `run-aws.sh --bench`. Kept separate so speed and correctness are never conflated. |
| `Makefile` | Builds `pricer` (compiler default contraction) and `pricer-strict` (`-ffp-contract=off`). |

## Run it in your AWS account

```
./run-aws.sh
```

This needs the AWS CLI v2 with credentials and `python3` on your machine. It launches a `c8a.xlarge` (AMD) and a `c9g.xlarge` (Graviton5) in `us-east-1` from the latest Amazon Linux 2023 AMI, installs `gcc-c++` on each, builds `pricer` and `pricer-strict`, runs both with price dumps, copies the dumps back through a private S3 bucket, and prints three comparisons:

1. Same x86-64 host, contraction on vs off.
2. Same arm64 host, contraction on vs off.
3. x86-64 vs arm64, both with contraction off.

Then it terminates the instances and deletes the bucket, security group and IAM role it created. Every resource a run creates carries a unique run id: the instances and security group are tagged `Project=graviton-numerical-validation` and `RunId=<id>`, and the bucket (`gnv-results-<account>-<id>`) and IAM role (`graviton-numerical-validation-<id>`) carry the id in their names. Cleanup removes only that run's resources, so concurrent runs do not interfere, and `--cleanup-only --run-id <id>` removes one interrupted run. The run takes about ten minutes and the report and dumps are saved under `results/run-<id>/`.

Instances are reached with SSM Run Command. No SSH key pair is created and the security group has no inbound rules.

Options:

```
--region R                 default us-east-1 (c9g is also in us-east-2, us-west-2, eu-central-1)
--x86 TYPE                 default c8a.xlarge
--arm TYPE                 default c9g.xlarge
--bench                    also run the throughput benchmark (see below)
--instance-profile NAME    use an existing instance profile instead of creating an IAM role
--keep                     leave the instances running (prints the run id and the cleanup command)
--run-id ID                reuse a specific run id, for cleaning up one earlier run
--cleanup-only             remove resources and exit; with --run-id, only that run, otherwise every run in the region/account
```

### Optional: throughput benchmark

```
./run-aws.sh --bench
```

After the correctness comparison, this builds and runs `bench.cpp` on both hosts and adds a table with options priced per second, cores and threads per core, CPU utilisation during the timed region, and, best effort, the current On-Demand and Spot price for each instance type in the region, so you get options per second per dollar. If the caller lacks `pricing:GetProducts` the price columns say `n/a` and the run still completes.

The benchmark prices 16 million options on all hardware threads, best of 8 repeats, with inputs generated outside the timed region. It uses the same Black-Scholes kernel as `pricer.cpp`. Read the result as one data point about this kernel on one instance size. A closed-form formula with no memory pressure, no branching and no library calls beyond libm says little about a real pricing library. The benchmark table is appended to the run's `report.txt` with the date it was taken.

### Permissions

What the script creates in your account, and what each piece can do:

- An IAM role and instance profile for the two instances, with the AWS managed policy `AmazonSSMManagedInstanceCore` and one inline statement allowing `s3:PutObject` to that run's results bucket only. The role has no other S3, EC2 or IAM rights.
- A security group with no inbound rules.
- An S3 bucket with all public access blocked, deleted at the end.
- Two instances with IMDSv2 required and an encrypted root volume.

The identity running the script needs the following. It is broader than the instance role because it creates and deletes the resources above. Scope the IAM statements to the role name used by the script and the S3 statements to the bucket prefix; EC2 launch and describe calls need `*` as their resource.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "sts:GetCallerIdentity", "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "ec2:DescribeInstanceTypeOfferings", "ec2:DescribeImages",
        "ec2:DescribeInstances", "ec2:DescribeSecurityGroups",
        "ec2:RunInstances", "ec2:TerminateInstances", "ec2:CreateTags",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:DescribeInstanceTypes", "ec2:DescribeSpotPriceHistory"
      ], "Resource": "*" },
    { "Effect": "Allow", "Action": "pricing:GetProducts", "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "ssm:DescribeInstanceInformation", "ssm:SendCommand",
        "ssm:GetCommandInvocation"
      ], "Resource": "*" },
    { "Effect": "Allow", "Action": "s3:ListAllMyBuckets", "Resource": "*" },
    { "Effect": "Allow", "Action": [
        "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketPublicAccessBlock",
        "s3:ListBucket", "s3:GetObject", "s3:DeleteObject"
      ], "Resource": [ "arn:aws:s3:::gnv-results-*", "arn:aws:s3:::gnv-results-*/*" ] },
    { "Effect": "Allow", "Action": [
        "iam:GetRole", "iam:CreateRole", "iam:DeleteRole",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy",
        "iam:GetInstanceProfile", "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile", "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile", "iam:PassRole"
      ], "Resource": [
        "arn:aws:iam::*:role/graviton-numerical-validation-role",
        "arn:aws:iam::*:instance-profile/graviton-numerical-validation-role"
      ] }
  ]
}
```

`ec2:DescribeInstanceTypes`, `ec2:DescribeSpotPriceHistory` and `pricing:GetProducts` are only used by `--bench` and can be dropped if you don't run it.

If IAM creation is not allowed for you, have an administrator create an instance profile with `AmazonSSMManagedInstanceCore` and `s3:PutObject` on `arn:aws:s3:::gnv-results-*/*`, pass it with `--instance-profile`, and drop the IAM statement above except `iam:PassRole` on that profile's role.

## Run it on hosts you already have

A C++17 compiler (GCC 11 or later, or Clang 14 or later) and Python 3.8 or later for `compare.py`. No third-party libraries.

Build both variants:

```
make
```

Price the book:

```
./pricer-strict
```

Example output on a Graviton4 instance:

```
arch             : aarch64
sve              : 128-bit (2 doubles per vector)
build flags      : -std=c++17 -O3 -pthread -Wall -ffp-contract=off
options          : 1000000
threads          : 1
book value       : 116982007931.343628
fingerprint      : 2f44f60b7d3f4adb
```

Run the same command on a second host and compare the fingerprints. If they match, every one of the million prices is bit-identical. If they differ, dump the prices on both hosts and compare them:

```
# on each host
./pricer-strict --dump prices.bin

# copy both files to one place, then
python3 compare.py prices_x86.bin prices_graviton.bin
```

To use the comparison as a gate, pass one or more tolerances. The script exits 1 if any is exceeded:

```
python3 compare.py a.bin b.bin --abs-tol 1e-9 --net-tol 1e-6
```

`--threads 0` uses all hardware threads. It does not change the book value or fingerprint: inputs are generated sequentially and the reduction runs in index order, so the result is the same with one thread or sixty-four.

## Reading the output

Book value and fingerprint are the two results. The fingerprint is an FNV-1a hash over the raw bytes of every price, so a one-bit change anywhere changes it. It tells you whether anything moved, not how much.

`compare.py` tells you how much. The figures to look at together:

- Count and percentage of prices that differ.
- Largest absolute difference, and the price it occurred on.
- Largest relative and ULP difference, and the price they occurred on. Relative error is large only where the price itself is near zero (deep out-of-the-money options). This is a property of the formula, not of the hardware: the Black-Scholes call value is a difference of two terms that nearly cancel for those inputs.
- Net difference between the two book totals.

## What the two builds show

`pricer` uses the compiler's default for floating-point contraction. `pricer-strict` adds `-ffp-contract=off`.

Contraction lets the compiler fuse `a * b + c` into a single fused multiply-add (FMA) instruction with one rounding instead of two. GCC defaults to `-ffp-contract=fast` for C++ in every `-std`, including the `-std=c++17` this Makefile uses, and for C only outside a standards-conforming mode (`-std=gnu11` contracts, `-std=c11` does not). Clang has contracted within a statement by default (`-ffp-contract=on`) since Clang 14. On arm64, FMA is part of the base instruction set, so the fused form is always available. Amazon Linux 2023 builds its x86-64 packages and defaults its compiler to the x86-64-v2 level, which has no FMA instruction (FMA arrives in x86-64-v3), so on x86 the same compiler with the same default flags has nothing to fuse with unless you raise the target with `-march`. This is why the two builds produce identical results on x86-64 and different results on arm64. The difference comes from what the compiler is allowed to emit, not from the silicon, and disappears with `-ffp-contract=off` on both.

What remains after contraction is disabled in your own code is the math library. `exp`, `log` and `erfc` are implemented in software, and IEEE 754 recommends but does not require that they be correctly rounded, so implementations may legitimately differ in the last bit. In glibc, the generic implementations of these functions are shared C source across architectures, but the library itself is compiled with contraction decisions you do not control. On aarch64 that code is built with FMA. On x86-64, glibc ships separate FMA-enabled variants of core routines such as `exp`, `log` and `pow`, compiled with `-mfma -mavx2`, and selects one at load time (through an ifunc) based on the CPU it finds. `erfc` has no FMA variant of its own, but glibc's `__erfc` computes its tail through `__ieee754_exp` (`sysdeps/ieee754/dbl-64/s_erf.c`), and on x86-64 that `exp` is the ifunc, so the normal-distribution tail still routes through an FMA-built routine. The last-bit differences you see between architectures after setting `-ffp-contract=off` are therefore mostly the same contraction effect, occurring inside the C library rather than in your code.

Two consequences follow. First, this is not an Arm property: an x86 fleet mixing CPUs with and without FMA would not be bit-identical with itself, because glibc would pick different `exp` implementations on different hosts. Every current-generation EC2 x86 instance supports FMA, which is why Intel and AMD hosts match each other. Second, the picture is changing: glibc has been importing correctly rounded implementations from the CORE-MATH project since 2.41, and 2.43 adds correctly rounded `erf` and `erfc`. A correctly rounded function returns the unique nearest double, so it is identical on every architecture by construction. Amazon Linux 2023 ships glibc 2.34 and does not have these yet.

## Results

Each run of `run-aws.sh` prints the three comparisons and writes a report and the raw price dumps to `results/run-<id>/` on your machine. The dumps are large and regenerable, so they are not committed; run the harness in your own account to produce them. Captured on Amazon Linux 2023 with GCC 11.5 and glibc 2.34, the strict build gives a book value of `116982007931.343628` on every x86 and Graviton instance tested, with 4.6% of individual prices differing in the last bits across architectures.

## What this does not show

The harness demonstrates the size and origin of differences for one closed-form model. It does not measure your pricing library, your compiler flags, or your third-party dependencies. Use it to understand the mechanism and to have a working comparison method, then apply the same method to your own code.

Results within a single architecture and build are reproducible. Results across architectures differ in the last bits of some prices. Whether those differences are acceptable is a question for your model validation process, and the tolerances in `compare.py` are there so you can encode the answer.

The correctness comparison is the point of the harness; `pricer` and `compare.py` say nothing about speed. The optional `--bench` mode (`bench.cpp`) measures throughput separately, and its one-kernel result is not a statement about a real pricing library.

## References

- IEEE Std 754-2019, IEEE Standard for Floating-Point Arithmetic. Basic operations must be correctly rounded; correct rounding of `exp`, `log`, `erf` and other elementary functions is recommended, not required.
- B. Gladman, V. Innocente, J. Mather, K. Ozaki, P. Zimmermann, "Accuracy of Mathematical Functions in Single, Double, Extended Double and Quadruple Precision", 2026. Measured worst-case errors for glibc and other math libraries. https://members.loria.fr/PZimmermann/papers/accuracy.pdf
- The CORE-MATH project, correctly rounded elementary functions being integrated into glibc and other libms. https://core-math.gitlabpages.inria.fr/
- glibc source, x86-64 FMA variants of libm functions selected by ifunc: https://sourceware.org/git/?p=glibc.git;a=blob;f=sysdeps/x86_64/fpu/multiarch/Makefile and https://sourceware.org/git/?p=glibc.git;a=blob;f=sysdeps/x86_64/fpu/multiarch/e_exp.c
- GCC manual, `-ffp-contract`. https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html
- Clang, discussion of the `-ffp-contract` default change to `on` (the LLVM issue tracking the change; the release notes record it landing in Clang 14). https://github.com/llvm/llvm-project/issues/50688
- Amazon Linux 2023, performance and operational optimizations (x86-64-v2 and `armv8.2-a+crypto` build targets). https://docs.aws.amazon.com/linux/al2023/ug/performance-optimizations.html
- AWS Graviton Technical Guide, C/C++ on Graviton (compiler flags per generation). https://github.com/aws/aws-graviton-getting-started/blob/main/c-c++.md
- Financial Services Grid Computing on AWS, Software considerations (IEEE 754 compliance and compiler variation). https://docs.aws.amazon.com/whitepapers/latest/financial-services-grid-computing/software-considerations.html
- Arm, "Enable reproducible math functions across vector extensions with Arm Performance Libraries" (libamath reproducibility mode). https://learn.arm.com/learning-paths/servers-and-cloud-computing/reproducible-libamath/
- nAG, "Bridging the Gap Between Numerical Precision and Cloud Efficiency" (bitwise-identical nAG Library build for a financial institution on Arm cloud instances including AWS Graviton). https://nag.com/insights/bridging-the-gap-numerical-precision-cloud-efficiency/
- AWS Containers Blog, "Migrating from x86 to AWS Graviton on Amazon EKS using Karpenter" (native per-architecture builds recommended over emulation for production). https://aws.amazon.com/blogs/containers/migrating-from-x86-to-aws-graviton-on-amazon-eks-using-karpenter/
