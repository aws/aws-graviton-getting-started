# .NET on Graviton

.NET is a free, cross-platform, open source developer platform for building many different types of applications. .NET applications are written in the C#, F#, or Visual Basic programming language. Code is compiled into a language-agnostic Common Intermediate Language (CIL). Compiled code is stored in assemblies—files with a .dll or .exe file extension. For more information, please see [what is .NET](https://dotnet.microsoft.com/learn/dotnet/what-is-dotnet).

When an app runs, the Common Language Runtime (CLR) takes the assembly and uses a just-in-time compiler (JIT) to turn it into machine code that can execute on the specific architecture of the computer it is running on. 

## .NET Versions

Version            | Linux Arm32   | Linux Arm64   | Notes
------------------|-----------|-----------|-------------
[.NET 6](https://dotnet.microsoft.com/download/dotnet/6.0) | Yes | Yes |  Preview releases provide early access to features that are currently under development. These releases are generally not supported for production use.
[.NET 5](https://dotnet.microsoft.com/download/dotnet/5.0) | Yes | Yes | Arm64-specific optimizations in the .NET libraries and the code produced by RyuJIT. [Arm64 Performance in .NET 5](https://devblogs.microsoft.com/dotnet/arm64-performance-in-net-5/) 
[.NET Framework 4.x](https://dotnet.microsoft.com/learn/dotnet/what-is-dotnet-framework) | No | No | The original implementation of the .NET Framework does not support Linux hosts, and Windows hosts are not suported on Graviton. 
[.NET Core 3.1](https://dotnet.microsoft.com/download/dotnet/3.1) | Yes | Yes | .NET Core 3.0 added support for [Arm64 for Linux](https://docs.microsoft.com/en-us/dotnet/core/whats-new/dotnet-core-3-0#linux-improvements). 
[.NET Core 2.1](https://dotnet.microsoft.com/download/dotnet/2.1) | Yes* | No | Initial support was for [Arm32 was added to .NET Core 2.1](https://github.com/dotnet/announcements/issues/82). *Operating system support is limited, please see the [official documentation](https://github.com/dotnet/core/blob/main/release-notes/2.1/2.1-supported-os.md).


## .NET 5
The .NET team has significantly improved performance with .NET 5, both generally and for Arm64. The team focused on Arm64-specific optimizations in the .NET libraries and evaluation of code quality produced by RyuJIT and resulting outcomes.

 * AWS Compute Blog [Powering .NET 5 with AWS Graviton2: Benchmarks](https://aws.amazon.com/blogs/compute/powering-net-5-with-aws-graviton2-benchmark-results/) 
 * Microsoft .NET Blog [ARM64 Performance in .NET 5](https://devblogs.microsoft.com/dotnet/arm64-performance-in-net-5/)


## Building & Publishing for Linux Arm64
The .NET SDK supports choosing a [Runtime Identifier (RID)](https://docs.microsoft.com/en-us/dotnet/core/rid-catalog) used to target platforms where the applications run. They're used by .NET packages to represent platform-specific assets in NuGet packages. The following values are examples of RIDs: linux-x64, ubuntu.14.04-x64, win7-x64, or osx.10.12-x64. For the packages with native dependencies, the RID designates on which platforms the package can be restored.

You can build and publish on any host operating system. As an example, you can develop on Windows and build locally to target Arm64, or you can use a CI server like Jenkins on Linux. The commands are the same.

```bash
dotnet build -r linux-arm64
dotnet publish -c Release -r linux-arm64
```

For more information about [publishing .NET apps with the .NET CLI](https://docs.microsoft.com/en-us/dotnet/core/deploying/deploy-with-cli) please see the offical documents.



