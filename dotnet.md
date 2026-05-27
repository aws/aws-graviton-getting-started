# .NET on Graviton
.NET is an open-source platform for writing different types of applications. Software engineers can write .NET based applications in multiple languages such as C#, F#, and Visual Basic. .NET applications are compiled into Common Intermediate Language (CIL). When an application is executed, the Common Language Runtime (CLR) loads that application binary and uses a just-in-time (JIT) compiler to generate machine code for the architecture being executed on. For more information, please see [what is .NET](https://dotnet.microsoft.com/learn/dotnet/what-is-dotnet).


## .NET Versions

Version            | Linux Arm32   | Linux Arm64   | Notes
------------------|-----------|-----------|-------------
.NET 10 | Yes | Yes | v10.0.0 released November 2025 with Arm64 Linux builds (LTS, supported until 2028-11-14). Recommended for new projects on Graviton.
.NET 9 | Yes | Yes | v9.0.0 released November 12, 2024 with Arm64 Linux builds. Maintenance support until 2026-11-10. See also [Arm64 vectorization in .NET libraries](https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-9/runtime#arm64-vectorization-in-net-libraries).
.NET 8 | Yes | Yes | v8.0.0 released November 14, 2023 with Arm64 Linux builds. Maintenance support until 2026-11-10. See also [Arm64 Performance Improvements in .NET 8](https://devblogs.microsoft.com/dotnet/this-arm64-performance-in-dotnet-8/). For details on .NET 8 and Graviton, check out this blog: [Powering .NET 8 with AWS Graviton3: Benchmarks](https://aws.amazon.com/blogs/dotnet/powering-net-8-with-aws-graviton3-benchmarks/)
~~.NET 7~~ | ~~Yes~~ | ~~Yes~~ | Out of support since 2024-05-14.
~~.NET 6~~ | ~~Yes~~ | ~~Yes~~ | Out of support since 2024-11-12.
~~.NET 5~~ | ~~Yes~~ | ~~Yes~~ | Out of support since 2022-05-10.
[.NET Framework 4.x](https://dotnet.microsoft.com/learn/dotnet/what-is-dotnet-framework) | No | No | The original implementation of the .NET Framework does not support Linux hosts, and Windows hosts are not supported on Graviton. 
~~.NET Core 3.1~~ | ~~Yes~~ | ~~Yes~~ | Out of support since 2022-12-13.
~~.NET Core 2.1~~ | ~~Yes~~ | ~~No~~ | Out of support since 2021-08-21.


<a id="net-5"></a>
## Recommended versions

Since version 5, .NET has added specific Arm64 optimizations in both the .NET libraries and the machine code emitted by RyuJIT, and each subsequent release has built on top of that work. We recommend .NET 10 (LTS) for new Graviton workloads, or .NET 8/9 if you need an earlier supported release.

 * AWS DevOps Blog: [Build and Deploy .NET web applications to ARM-powered AWS Graviton 2 Amazon ECS Clusters using AWS CDK](https://aws.amazon.com/blogs/devops/build-and-deploy-net-web-applications-to-arm-powered-aws-graviton-2-amazon-ecs-clusters-using-aws-cdk/)
 * AWS Compute Blog: [Powering .NET 5 with AWS Graviton2: Benchmarks](https://aws.amazon.com/blogs/compute/powering-net-5-with-aws-graviton2-benchmark-results/)
 * Microsoft .NET Blog: [ARM64 Performance in .NET 5](https://devblogs.microsoft.com/dotnet/arm64-performance-in-net-5/)
 * AWS .NET Blog: [Powering .NET 8 with AWS Graviton3: Benchmarks](https://aws.amazon.com/blogs/dotnet/powering-net-8-with-aws-graviton3-benchmarks/)
 * Microsoft .NET Blog: [Arm64 Performance Improvements in .NET 8](https://devblogs.microsoft.com/dotnet/this-arm64-performance-in-dotnet-8/)
 * Microsoft Learn: [Arm64 vectorization in .NET 9](https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-9/runtime#arm64-vectorization-in-net-libraries)


## Building & Publishing for Linux Arm64
The .NET SDK supports choosing a [Runtime Identifier (RID)](https://docs.microsoft.com/en-us/dotnet/core/rid-catalog) used to target platforms where the applications run. These RIDs are used by .NET dependencies (NuGet packages) to represent platform-specific resources in NuGet packages. The following values are examples of RIDs: linux-arm64, linux-x64, ubuntu.14.04-x64, win7-x64, or osx.10.12-x64. For the NuGet packages with native dependencies, the RID designates on which platforms the package can be restored.

You can build and publish on any host operating system. As an example, you can develop on Windows and build locally to target Arm64, or you can use a CI server like Jenkins on Linux. The commands are the same.

```bash
dotnet build -r linux-arm64
dotnet publish -c Release -r linux-arm64
```

For more information about [publishing .NET apps with the .NET CLI](https://docs.microsoft.com/en-us/dotnet/core/deploying/deploy-with-cli) please see the offical documents.
