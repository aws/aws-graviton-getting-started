# Spark on Graviton

Apache Spark is a data processing framework widely used to extract information from large pools of data.
One main problem that affects performance is the straggler, where a long-running task slows down the entire cluster. Stragglers in Spark are usually caused by non-uniform distribution of work or data being skewed non uniformly across nodes, resulting in a single task taking up more work. Our goal should be to keep all the CPUs busy and not have a small set of cores executing long running tasks. Setting up a correct configuration depends on the dataset size, number of instances, core count/instance, and computational complexity.

Below are some general guidelines that can be referenced by users trying to improve over all Application performance across Spark clusters. Since there is no one standard config set that works well in all cases, we advise users to benchmark real applications after following the below guidelines. 

1. Shuffle Partitions: This configuration option is important to mitigate performance issues due to stragglers. Recommendations are
    * To have a partition size to be less than 200 MB to gain optimized performance
    * The number of partitions should be multiples of the number of cores available (1xcores, 2xcores .. etc)

Below are the benchmark results showing the total execution time by varying shuffle partitions value in Spark. Benchmarking is performed on Spark cluster with 128 vCPUs spread across 8 Graviton3 instances, executing queries on 1 TB TPC-DS dataset.
We have seen 80% improvement in performance when using optimized value vs non-optimized value. 


|shuffle_partitions	|Execution time (mins)	|%Diff	|
|---	|---	|---	|
|10	|175	|Baseline	|
|16	|117	|-33%	|
|30	|72	|-59%	|
|64	|50	|-71%	|
|128	|48	|-73%	|
|256	|39	|-78%	|
|512	|37	|-79%	|
|1024	|35	|-80%	|
|2000	|35	|-80%	|

*Lower numbers are better, and negative % diff means faster. Benchmarked on Spark 3.3.0 with Java 17 using spark-sql-perf framework from Databricks*



2. When using Amazon EMR to setup Spark cluster, it is recommended to use EMR defaults for configuration options. For any other specific cases that need specific tuning, the general optimization guide can be referenced from https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-spark-performance.html.
3. Adaptive Query Execution(AQE) is an optimization technique in Spark SQL that makes use of runtime statistics to choose the most efficient query execution plan, which is enabled by default since Apache Spark 3.2.0. For users, using older Spark versions, we recommend checking the performance by turning it on (https://spark.apache.org/docs/latest/sql-performance-tuning.html#adaptive-query-execution)
4. We have seen 40% improvement in performance when using Spark 3 with Java 17 when compared to Spark 2 with Java 8. So we recommend to use latest Spark 3 with Java 17. 
