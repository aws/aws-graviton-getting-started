# Java on Graviton

Java is a general-purpose programming language. Compiled Java code can run on all platforms that support Java, without the need for recompilation. Java applications are typically compiled to bytecode that can run on any Java virtual machine (JVM) regardless of the underlying computer architecture. _[Wikipedia](https://en.wikipedia.org/wiki/Java_(programming_language))_

Java is well supported and generally performant out-of-the-box on arm64. [Amazon Corretto](https://aws.amazon.com/corretto/), a no-cost, multiplatform, production-ready distribution of the Open Java Development Kit (OpenJDK) supports Graviton-powered instances.
While Java 8 is fully supported on Arm
processors, some customers haven't been able to obtain Graviton's full
performance benefit until they switched to Java 11.

This page includes specific details about building and tuning Java application on Graviton.

### Java versions
JDK binaries for arm64 are available from a number of
different sources.  [Amazon Corretto](https://aws.amazon.com/corretto/) is
continuing to improve performance of Java workloads running on Graviton processors and
if you have the choice of a JDK to use we recommend using Corretto as it
provides the fastest way to get access to the performance improvements AWS is making.
Versions of Corretto released since October 2020 are built to use the
most optimal atomic operations within the JVM: Corretto11 (all
variants); Correto8 (on Amazon Linux 2 only). This has shown to reduce
GC time in some workloads.

### Java JVM Options
There are numerous options that control the JVM and may lead to better performance. Three that
have shown large (1.5x) improvements in some Java workloads are eliminating tiered compilation
and restricting the size of the code cache which allows the Graviton2 cores to better predict
branches. These are helpful on some workloads but can hurt on others so testing with and without
them is essential: `-XX:-TieredCompilation -XX:ReservedCodeCacheSize=64M -XX:InitialCodeCacheSize=64M`.

### Looking for x86 shared-objects in JARs
Java JARs can include shared-objects that are architecture specific. Some Java libraries check
if these shared objects are found and if they are they use a JNI to call to the native library
instead of relying on a generic Java implementation of the function. While the code might work,
without the JNI the performance can suffer.

A quick way to check if a JAR contains such shared objects is to simply unzip it and check if
any of the resulting files are shared-objects and if an aarch64 (arm64) shared-object is missing:
```
$ unzip foo.jar
$ find . -name "*.so" | xargs file
```
For each x86-64 ELF file, check there is a corresponding aarch64 ELF file
in the binaries. With some common packages (e.g. commons-crypto) we've seen that
even though a JAR can be built supporting Arm manually, artifact repositories such as
Maven don't have updated versions. To see if a certain artifact version may have Arm support,
consult our [Common JARs with native code Table](CommonNativeJarsTable.md).
Feel free to open an issue in this GitHub repo or contact us at ec2-arm-dev-feedback@amazon.com
for advice on getting Arm support for a required Jar. 

### Building multi-arch JARs
Java is meant to be a write once, and run anywhere language.  When building Java artifacts that
contain native code, it is important to build those libraries for each major architecture to provide
a seamless and optimally performing experience for all consumers.  Code that runs well on both Graviton and x86
based instances increases the package's utility.

There is nominally a multi-step process to build the native shared objects for each supported
architecture before doing the final packaging with Maven, SBT, Gradle etc. Below is an example
of how to create your JAR using Maven that contains shared libraries for multiple distributions
and architectures for running your Java application interchangeably on AWS EC2 instances
based on x86 and Graviton processors:

```
# Create two build instances, one x86 and one Graviton instance.
# Pick on instance to be the primary instance.
# Log into the secondary instance
$ cd java-lib
$ mvn package
$ find target/ -name "*.so" -type f -print

# Note the directory this so file is in, it will be in a directory
# such as: target/classes/org/your/class/hierarchy/native/OS/ARCH/lib.so

# Log into the primary build instance
$ cd java-lib
$ mvn package

# Repeat the below two steps for each OS and ARCH combination you want to release
$ mkdir target/classes/org/your/class/hierarchy/native/OS/ARCH
$ scp slave:~/your-java-lib/target/classes/org/your/class/hierarchy/native/OS/ARCH/lib.so target/classes/org/your/class/hierarchy/native/OS/ARCH/

# Create the jar packaging with maven.  It will include the additional
# native libraries even though they were not built directly by this maven process.
$ mvn package

# When creating a single Jar for all platform native libraries, 
# the release plugin's configuration must be modified to specify 
# the plugin's `preparationGoals` to not include the clean goal.
# See http://maven.apache.org/maven-release/maven-release-plugin/prepare-mojo.html#preparationGoals
# For more details.

# To do a release to Maven Central and/or Sonatype Nexus:
$ mvn release:prepare
$ mvn release:perform

```

This is one way to do the JAR packaging with all the libraries in a single JAR.  To build all the JARs, we recommend to build on native
machines, but it can also be done via Docker using the buildx plug-in, or by cross-compiling inside your build-environment.

Additional options for releasing jars with native code is to: use a manager plugin such as the [nar maven plugin](https://maven-nar.github.io/)
to manage each platform specific Jar.  Release individual architecture specific jars, and then use the primary
instance to download these released jars and package them into a combined Jar with a final `mvn release:perform`.
An example of this methd can be found in the [Leveldbjni-native](https://github.com/fusesource/leveldbjni) `pom.xml` files. 


### Profiling Java applications
For languages that rely on a JIT (such an Java), the symbol information that is
captured is lacking, making it difficult to understand where runtime is being consumed.
Similar to the code profiling example above, `libperf-jvmti.so` can be used to dump symbols for
JITed code as the JVM runs.

```bash
# Compile your Java application with -g

# find where libperf-jvmti.so is on your distribution

# Run your java app with -agentpath:/path/to/libperf-jvmti.so added to the command line
# Launch perf record on the system
$ perf record -g -k 1 -a -o perf.data sleep 5

# Inject the generated methods information into the perf.data file
$ perf inject -j -i perf.data -o perf.data.jit

# Process the new file, for instance via Brendan Gregg's Flamegraph tools
$ perf script -i perf.data.jit | ./FlameGraph/stackcollapse-perf.pl | ./FlameGraph/flamegraph.pl > ./flamegraph.svg
```
