# Spark on Graviton
Below are some general guidelines that can be referenced by users trying to improve over all Application performance across Spark clusters. Note that, there is no magic/standard values that works in all use cases and each case can be different. Most of the times, it depends on dataset sizes, cores available, workload type etc. 

1. Shuffle Partitions: This config option is important to achieve optimal performance. Recommendations in regards to this are
    * It's recommended to have the partition size less than 200 MB to gain optimized performance
    * Usually number of partitions should be multiples of number of cores available (1xcores, 2xcores .. etc)
2. AWS EMR team recommends using EMR defaults. For any other specific cases that needs specific tunings, the general optimization guide is https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-spark-performance.html.
3. Spark official tuning guide - https://spark.apache.org/docs/latest/sql-performance-tuning.html. Also worth looking at Adaptive query execution (AQE) which was not enabled by default before Spark 3.2 (https://spark.apache.org/docs/latest/sql-performance-tuning.html#adaptive-query-execution). 
4. Our current results show Graviton3 instances to be more performant than Graviton2 instances. For users dealing with issues across performance on Graviton 2 instances, first recommendation is to try above tuning options and check the performance. In case of no improvement, we recommend to migrate to Graviton3 instances if possible. 
5. Spark 3 is faster than Spark 2 in general. We recommend to use latest version of Spark along with latest Java version.

