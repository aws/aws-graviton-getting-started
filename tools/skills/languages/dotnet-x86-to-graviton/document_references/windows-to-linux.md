# Windows and .NET Framework to Linux

> Graviton runs Linux, so an application that runs on Windows today, on the .NET Framework or on modern .NET, moves to modern .NET on Linux before any arm64 check matters. This file says how to detect what blocks that move, what replaces each Windows-only piece on Linux, and which choices belong to the user. Read it when Phase 1.1 finds a .NET Framework or Windows starting point. Every replacement below was executed on a Linux x64 host and in a linux/arm64 container (emulated), unless the row says otherwise.

## 1. The Decision and the Tools

- **One decision for the whole solution.** The move to modern .NET on Linux is a MUST UPGRADE, approved once (`dotnet.framework_bump` in `skill-config.md`, default `ask`). Present the target framework options with their support dates and glibc needs (phase1-static-analysis.md §1.5), then apply the approved one to every project that moves.
- **Only what modern .NET supports on Linux.** A component with no Linux path (Windows Forms, WPF, ASP.NET Web Forms) is a **BLOCKER** with documented options. It is never ported to another Windows-only target, and the server parts it calls can still move.
- **Each replacement that changes behavior or data is a user decision:** secrets, imaging libraries, authentication, persisted serialized data, time zone handling, hosting.
- **Optional accelerators for large solutions.** Microsoft recommends GitHub Copilot app modernization and says ".NET Upgrade Assistant is officially deprecated" ([Microsoft Learn: porting](https://learn.microsoft.com/en-us/dotnet/core/porting/), [Upgrade Assistant](https://learn.microsoft.com/en-us/dotnet/core/porting/upgrade-assistant-overview)). AWS Transform for .NET ports .NET Framework applications to cross-platform .NET for Linux ([AWS blog](https://aws.amazon.com/blogs/modernizing-with-aws/port-your-net-framework-applications-to-linux-with-aws-transform-for-net/)). Whatever produced the ported code, the checks in this skill (per-RID native assets, code scan, output scan, arm64 tests) apply to the result.

## 2. Technology Map

| Technology (how Phase 1 finds it) | On Linux | Replacement | Executed result |
|---|---|---|---|
| Windows Forms (`-windows` target framework, `UseWindowsForms`) | not available: "a UI framework for building Windows desktop apps" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/overview/)) | none: **BLOCKER**. Keep the tool on Windows clients, or replace the UI (user decision) | `dotnet build` on Linux: `NETSDK1100`; `publish -r linux-arm64` with `EnableWindowsTargeting=true` exited 0, but the runtimeconfig needs `Microsoft.WindowsDesktop.App` |
| WPF (`UseWPF`) | not available: "WPF only runs on Windows" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)) | none: **BLOCKER**, as above | same build and publish behavior as Windows Forms |
| ASP.NET Web Forms (`.aspx`, `.ascx`, `System.Web.UI`) | "ASP.NET Web Forms are only available in .NET Framework" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/standard/choosing-core-framework-server)) | none: **BLOCKER**, rewrite or retire (user decision) | the page was kept out of the build of the port (`<Compile Remove>`, `<Content Remove>`) |
| ASP.NET Web API 2 and MVC 5 (`System.Web.Http`, `System.Web.Mvc`, `Global.asax`) | not available | ASP.NET Core controllers (`[ApiController]`, `ControllerBase`, attribute routes) | `GET /api/orders/7` answered `{"id":7,"status":"open"}` on x64 and arm64 |
| WCF service (`System.ServiceModel`, `.svc`) | server through CoreWCF: "WCF server can be used in .NET 6+ by using the CoreWCF NuGet packages" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable)) | CoreWCF (`CoreWCF.Http`, `CoreWCF.Primitives`) with `UseServiceModel`, or gRPC or REST (user decision) | CoreWCF 1.9.1 with `BasicHttpBinding`: the SOAP call `Status(5)` returned `<StatusResult>open</StatusResult>` on x64 and arm64. Other bindings were not tested |
| Windows service (`ServiceBase`, `AddWindowsService`, `UseWindowsService`) | no Windows service manager | `BackgroundService` plus `AddSystemd()` (Microsoft.Extensions.Hosting.Systemd) and a systemd unit with `Type=notify`, or a container | the worker ran under the generic host; `systemd-analyze verify` passed for the unit |
| IIS hosting (`web.config`, `UseIIS()`, `AspNetCoreHostingModel`) | IIS does not exist; the app runs on Kestrel | no code change; the reverse proxy or load balancer is a deployment decision | with `UseIIS()` left in place, the API started on Kestrel and answered `/health`; `web.config` is unused on Linux |
| Registry (`Microsoft.Win32.Registry`) | `PlatformNotSupportedException: Registry is not supported on this platform.` | configuration: `appsettings.json`, environment variables, or a parameter store | settings read from environment variables |
| DPAPI (`ProtectedData`) | `PlatformNotSupportedException: Operation is not supported on this platform.` | secrets from a secret store, injected as environment variables; or ASP.NET Core Data Protection with a persisted key ring (user decision, including where the key ring lives) | Data Protection (Microsoft.AspNetCore.DataProtection.Extensions 8.0.31) protected and unprotected a value with a key ring on disk, on x64 and arm64 |
| P/Invoke into Windows DLLs (`kernel32.dll`, `user32.dll`, ...) | `DllNotFoundException: Unable to load shared library 'kernel32.dll' or one of its dependencies` | the .NET API that does the same (`Environment.TickCount64` for `GetTickCount64`) | uptime read through `Environment.TickCount64` |
| Windows paths (`C:\...`, `\` separators, case that differs from the disk) | no exception for an absolute Windows path: a directory literally named `C:\ProgramData\Orders` was created in the working directory. A `\` separator: `FileNotFoundException: Could not find file '.../Config\Settings.json'.` | paths from configuration, with Linux defaults; `Path.Combine` with each segment spelled as on disk | data directory from `ORDERS_DATA_DIR`; settings read through `Path.Combine("config", "settings.json")` |
| Windows time zone IDs (`"Pacific Standard Time"`) | work when the image has ICU and time zone data (§5) | keep the ID on an image with ICU and tzdata, or use IANA IDs (decided together with the image) | `04:00` on Debian, Azure Linux, Lambda and chiseled-extra images; `TimeZoneNotFoundException` on Alpine and chiseled images |
| `System.Drawing.Common` | Windows only since .NET 6: "a TypeInitializationException exception is thrown with PlatformNotSupportedException as the inner exception" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/core/compatibility/core-libraries/6.0/system-drawing-common-windows-only)) | another imaging library (user decision), checked with the per-RID check like any native package | SkiaSharp with SkiaSharp.NativeAssets.Linux 2.80.0 resized a bitmap on x64 and arm64. Restore flags 2.80.0 to 2.88.5 with NU1903, so offer 2.88.6, the lowest release without it ([nuget-native-assets.md §5](nuget-native-assets.md#5-finding-the-lowest-version-that-works)) |
| Event Log (`AddEventLog`, `EventLog`) | the host crashed at startup: `System.PlatformNotSupportedException: EventLog access is not supported on this platform.` (exit 134) | remove; the host's console logging (or JSON console) goes to the journal or the container log | the host logged to the console |
| `AppDomain.CreateDomain` | `PlatformNotSupportedException: Secondary AppDomains are not supported on this platform.` | a collectible `AssemblyLoadContext`: "To dynamically load assemblies, use the AssemblyLoadContext class" ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable)) | a plugin assembly loaded and ran on x64 and arm64 |
| `BinaryFormatter` | `SYSLIB0011` is a build error on .NET 8 and 10; with the warning suppressed, .NET 8 threw `NotSupportedException` and .NET 10 `PlatformNotSupportedException` | another serializer; whether existing files must stay readable is a user decision | `System.Text.Json` wrote and read the cache on x64 and arm64 |
| .NET Remoting, code access security, Workflow Foundation, COM+ (`System.EnterpriseServices`) | not supported in modern .NET ([Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/core/porting/net-framework-tech-unavailable)); CoreWF is the alternative Microsoft names for Workflow Foundation | redesign: **BLOCKER** with options | not tested |
| Windows authentication (`<authentication mode="Windows" />`, Negotiate) | the Negotiate handler "can be used with Kestrel to enable Windows Authentication using Negotiate and Kerberos on Windows, Linux, and macOS", and "Kerberos authentication on Linux or macOS doesn't provide any role information" without an LDAP lookup ([Microsoft Learn](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/windowsauth)) | Microsoft.AspNetCore.Authentication.Negotiate with Kerberos, or another identity provider (user decision) | not tested: it needs a Kerberos domain |
| Windows container images (`nanoserver`, `servercore`) | do not run on Linux | the Linux image of the same .NET version (Phase 2.4) | `docker build --platform linux/arm64` of the rewritten Dockerfile (SDK stage on `$BUILDPLATFORM`, `-a $TARGETARCH`) took 14 seconds; the arm64 container answered `/health`, and a scan of its `/app` found only aarch64 and arm64 files |
| Install scripts (`New-Service`, `sc.exe`, `.ps1`) | do not run on Linux | a systemd unit, or the container | unit file verified with `systemd-analyze verify` |
| CI on Windows runners, `-r win-x64` | the pipeline still builds Windows output | a Linux runner and `-r linux-arm64` (or a multi-architecture image build) | CI changes are the user's: recorded as a recommendation (SKILL.md "User Responsibility") |

## 3. Porting a .NET Framework Project

Executed on the .NET Framework test solution (a Web API 2 application with a WCF service, a Windows service class, an application-domain plugin host, a `BinaryFormatter` cache and a Web Forms page, plus a .NET Standard library that needed no change):

1. **Project file.** Replace the old project file with an SDK-style one: `<Project Sdk="Microsoft.NET.Sdk.Web">` for a web application, the approved `<TargetFramework>`, and no `<PlatformTarget>x64</PlatformTarget>` (AnyCPU is the default).
2. **Packages.** Move `packages.config` entries to `<PackageReference>` items ([package-management-mapping.md §2.4](package-management-mapping.md#24-packagesconfig)). Drop packages whose function modern .NET has built in (Microsoft.AspNet.WebApi and its parts become ASP.NET Core). Keep managed libraries at their versions (Newtonsoft.Json 13.0.1 stayed). Replace packages with no linux-arm64 native (System.Data.SQLite.Core: Microsoft.Data.Sqlite).
3. **Configuration.** Move settings from `Web.config` to `appsettings.json`, with Linux paths: `Data Source=C:\ProgramData\Orders\orders.db` became `Data Source=/var/lib/orders/orders.db`. Binding redirects are not needed.
4. **Code.** Apply the replacements in §2. `Global.asax` becomes `Program.cs` with `WebApplication.CreateBuilder`, `AddControllers` and `MapControllers`; the WCF service gets `AddServiceModelServices` and `UseServiceModel`; the Windows service becomes a hosted `BackgroundService` with `AddSystemd()`.
5. **Blockers.** Keep blocked components out of the build until the user decides, and record them in `04-code-scan-findings.md`.
6. **Check and run.** Build on Linux, run the per-RID check (`assets`), publish for linux-arm64, scan the output, and run on Linux (Phase 3).

Results: the build passed; `assets` reported 81 packages, all managed, and no findings; the linux-arm64 publish scan reported no findings; on x64 and arm64 the REST call, the SOAP call, the plugin load and the cache all worked.

## 4. Moving a Windows-Hosted Modern .NET Application

Executed on the Windows test solution (a worker service, an IIS-hosted API and a Windows Forms tool, all on .NET 8):
- The replacements changed three files of the service (registry, DPAPI, `kernel32.dll`, paths, `System.Drawing`, Event Log, Windows service hosting, the `win-x64` RID), rewrote the Dockerfile for a Linux image and added a systemd unit. The API needed no code change.
- After the changes, the service and the API built on Linux without `EnableWindowsTargeting`, and CA1416 reported no call sites. Every self-check passed on x64 and arm64, the host ran with `AddSystemd()` in place, and the API answered on Kestrel.
- Building the whole solution still failed with `NETSDK1100`, because the Windows Forms project stays in it. Build and test the projects that move to Linux one by one (or through a solution filter the team adds); never set `EnableWindowsTargeting` to make the Linux build pass.

## 5. Images: Globalization and Time Zones

The image, not the CPU, decides globalization behavior. Executed with a framework-dependent probe (a Windows time zone ID, an IANA ID, the `de-DE` culture) on native containers:

| Image | `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT` in the image | `/usr/share/zoneinfo` | `Pacific Standard Time` | `America/Los_Angeles` | `de-DE` |
|---|---|---|---|---|---|
| `mcr.microsoft.com/dotnet/runtime:8.0` (Debian) | not set | yes | works | works | works |
| `mcr.microsoft.com/dotnet/runtime:8.0-alpine` | `true` | no | `TimeZoneNotFoundException` | `TimeZoneNotFoundException` | `CultureNotFoundException` |
| `mcr.microsoft.com/dotnet/runtime:8.0-noble-chiseled` | `true` | no | `TimeZoneNotFoundException` | `TimeZoneNotFoundException` | `CultureNotFoundException` |
| `mcr.microsoft.com/dotnet/runtime:8.0-noble-chiseled-extra` | not set | yes | works | works | works |
| `mcr.microsoft.com/dotnet/runtime:8.0-azurelinux3.0` | not set | yes | works | works | works |
| `public.ecr.aws/lambda/dotnet:8` | not set | yes | works | works | works |
| `mcr.microsoft.com/dotnet/runtime:8.0` run with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` | set | yes | `TimeZoneNotFoundException` | works | `CultureNotFoundException` |

The chiseled image gave the same results as linux/arm64 (emulated). So:
- Windows time zone IDs need ICU, and every time zone ID needs time zone data in the image.
- A move to Alpine or a chiseled image changes these results as well as the C library ([agent-scope-boundaries.md](agent-scope-boundaries.md): base image changes are a user decision).
- `<InvariantGlobalization>true</InvariantGlobalization>` in a project file (phase1 §1.1 lists it) writes `"System.Globalization.Invariant": true` to the runtimeconfig and gave the same results as the environment variable on the Debian image.

## 6. Traps

| Trap | Instead |
|---|---|
| A Windows Forms or WPF project publishes for linux-arm64 with exit 0 | the target framework, `UseWindowsForms`/`UseWPF`, and the runtimeconfig frameworks decide; Phase 3 scans the runtimeconfig |
| CA1416 reports nothing for P/Invoke into Windows DLLs, for `-windows` projects, or for .NET Framework projects | also search the text (phase1 §1.4) |
| An absolute Windows path raises no exception on Linux | search for drive letters and backslashes, and check where files land in Phase 3 |
| `AddWindowsService` is harmless on Linux, so the service looks fine until `AddEventLog` crashes the host | replace both together |
| The time zone code works on the Debian image and fails on the chiseled image | test on the image that ships (§5) |
| A replacement package is added at a version with an audit warning | read the restore output for NU1901 to NU1904 and offer the lowest version without one |
| `EnableWindowsTargeting=true` makes a Linux build pass | build only the projects that move to Linux; Windows-only projects are blockers, not build settings |
