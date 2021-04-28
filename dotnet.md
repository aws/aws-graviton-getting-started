# .NET Core and .NET 5+ on Graviton

.NET Core is a free, cross-platform, open source developer platform for building many different types of applications originally written by Microsof, and now opensource. .NET Core has supported Linux 64-bit ARM since v2.1.0, but .NET 5 and higher offers hardware specific optimizations in the .NET libraries.

.NET applications are written in the C#, F#, or Visual Basic programming language. Code is compiled into a language-agnostic Common Intermediate Language (CIL). Compiled code is stored in assemblies—files with a .dll or .exe file extension.

When an app runs, the CLR takes the assembly and uses a just-in-time compiler (JIT) to turn it into machine code that can execute on the specific architecture of the computer it is running on. 

Here are some noteworthy performance upgrades:

## .NET 5 \[released 2020/11/10\]
The .NET team has significantly improved performance with .NET 5, both generally and for ARM64. The team focused on ARM64-specific optimizations in the .NET libraries and evaluation of code quality produced by RyuJIT and resulting outcomes.

 * [ARM64 Performance in .NET 5](https://devblogs.microsoft.com/dotnet/arm64-performance-in-net-5/)

## .NET Framework 
.NET Framework is the original implementation of .NET. .NET Framework does not support Linux hosts, and Windows hosts are not yet suported on Graviton.

* [What is .NET](https://dotnet.microsoft.com/learn/dotnet/what-is-dotnet)


## Building & Publishing for Linux Arm64
The .NET SDK supports chosing a [Runtime Identifier (RID)](https://docs.microsoft.com/en-us/dotnet/core/rid-catalog) used to target platforms where the applications run. They're used by .NET packages to represent platform-specific assets in NuGet packages. The following values are examples of RIDs: linux-x64, ubuntu.14.04-x64, win7-x64, or osx.10.12-x64. For the packages with native dependencies, the RID designates on which platforms the package can be restored.

You can build and publish on any host operating system. As an example, you can develop on Windows and build locally to target Arm64, or you can use a CI server like Jenkins on Linux. The commands are the same.

```bash
dotnet build -r linux-arm64
dotnet publish -c Release -r linux-arm64
```

* [Publishing .NET apps with the .NET CLI](https://docs.microsoft.com/en-us/dotnet/core/deploying/deploy-with-cli)



