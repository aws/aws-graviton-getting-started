# Configuring your load generator

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

The load generator setup is important to understand and verify: it generates the load that is expected.  An unknown load-generation setup can lead to not measuring the expected experiment and getting results that are hard to interpret. Below is a checklist to step through and verify the load generator is working as expected.

1. Ensure the load generator instance is large enough for driving traffic to the Systems-under-test (SUTs), we recommend using 12xl instances or larger.  
2. When generating load, verify the load-generator instance is not using 100% CPU for load-generators that use blocking IO.  For load-generators that busy poll, verify that it is spending ~50% of its time in the busy poll loop by utilizing `perf`  to verify where the load generator code is spending time. See [Section 5.b](./debug_code_perf.md) on how to generate CPU time profiles to verify this.  
3. If the load-generator is close to its limit, measurements taken may be measuring the load-generator's ability to generate load and not the SUT's ability to process that load.  A load-generator that is spending less than 50% of its time generating load is a good target to ensure you are measuring the SUT.
4. When generating load, verify the load-generator is receiving valid responses and not a large number of errors from the SUT.  For example, the example below shows the [Wrk2](https://github.com/giltene/wrk2) load generator receiving many errors, meaning the test point is invalid:
  ```bash 
  Running 30s test @ http://127.0.0.1:80/index.html
  2 threads and 100 connections
  Thread calibration: mean lat.: 9747 usec, rate sampling interval: 21 msec
    Thread calibration: mean lat.: 9631 usec, rate sampling interval: 21 msec
    Thread Stats   Avg      Stdev     Max   +/- Stdev
      Latency     6.46ms    1.93ms  12.34ms   67.66%
      Req/Sec     1.05k     1.12k    2.50k    64.84%
    60017 requests in 30.01s, 19.81MB read
    Non-2xx or 3xx responses: 30131 
  Requests/sec:   2000.15
  Transfer/sec:    676.14KB
  ```
5. Check `dmesg` and logs in `/var/log` on the SUT and load generator for indications of errors occurring when under load
6. Verify load generators and SUTs are physically close to remove sensitivities to RTT (Round-Trip-Times) of messages. Differences in RTT from a load-generator to SUTs can show up as lower throughput, higher latency percentiles and/or increase in error rates, so it is important to control this aspect for testing. Check the following aspects in the order provided to verify your network setup follows best practices and reduces the influence of network factors on test results:
    1. Verify on EC2 console *Placement Group* is filled in with the same placement for the SUTs and load generators and that placement group is set to `cluster`.
    2. Check in the EC2 console that all load generators are in the same subnet (i.e. us-east-1a)
    3. Run `ping` from your SUTs to the load generators and any back-end services your SUT will communicate with. Verify the average latencies are similar (10s of micro-seconds).  You can also use `traceroute` to see the number of hops between your instances as well, ideally it should be 3 or less.
7. Check for ephemeral port exhaustion that may prevent load-generator from driving the desired traffic load:
  ```bash
  # Check on both the load generator/SUT machines
  %> netstat -nt | awk '/ESTABLISHED|TIME_WAIT|FIN_WAIT2|FIN_WAIT1|CLOSE_WAIT/ {print $6}' | sort | uniq -c | sort -n
  30000 TIME_WAIT
    128 ESTABLISHED

  # If large numbers of connections are in TIME_WAIT, and number of ESTABLISHED is decreasing,
  # port exhaustion is happening and can lead to decrease in driven load.  Use the below tips to
  # fix the issue.

  # Increase ephemeral port range on load generator/SUT
  %> sudo sysctl -w net.ipv4.ip_local_port_range 1024 65535
  # If you application uses IPv6
  %> sudo sysctl -w net.ipv6.ip_local_port_range 1024 65535

  # Allow kernel to re-use connections in load generator/SUT
  %> sysctl -w net.ipv4.tcp_tw_reuse=1
  ```
8. Check connection rates on SUT.  Do you see constant rate of new connections or bursty behavior? Does it match the expectations for the workload? 
  ```bash
  # Terminal on load-generator instance
  %> <start test>

  # Terminal on SUT
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities
  %> python3 ./measure_and_plot_basic_sysstat_stats.py --stat new-connections --time 60
  ```
9. If higher than expected connections/s are being observed, the cause of these new connections can be determined by looking at a packet trace and determining which end is initiating and closing the connections. 
  ```bash
  # On load-generator
  %> <start test>
        
  # On load-generator
  # Grab tcpdump from network device that will recieve traffic, likely 
  # eth0, but check your configuration.
  %> tcpdump -i eth<N> -s 128 -w dump.pcap
  %> <stop tcpdump using Ctrl-C>
  ```
10. Open the trace using a tool like [Wireshark](https://www.wireshark.org/#download). 
11. Look for which side is closing connections unexpectedly by looking for `Connection: Close` in the HTTP headers, or `FIN` in the TCP headers.  Identify which system is doing this more than expected.
12. Verify setup of the SUT and/or load generator for connection establishment behavior.
13.  Check packet rate, is it behaving as expected? i.e. constant rate of traffic, or bursty.
  ```bash
  # Load generator terminal #1
  %> <start load generator or benchmark>
    
  # Terminal #2 on load generator
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities
  %> python3 ./measure_and_plot_basic_sysstat_stats.py --stat tcp-out-segments --time 60
  %> python3 ./measure_and_plot_basic_sysstat_stats.py --stat tcp-in-segments --time 60
  ```
14. Check for hot connections (i.e. connections that are more heavily used that others) by running: `watch netstat -t`. The below example shows the use of `netstat -t` to watch multiple TCP connections. One connection is active and has a non-zero `Send-Q` value while all other connections have a `Send-Q` value of 0. 
  ```bash
  %> watch netstat -t
  Every 2.0s: netstat -t
  ip-172-31-9-146: Tue Jan 12 23:01:35 2021
      
  Active Internet connections (w/o servers)
  Proto Recv-Q Send-Q Local Address           Foreign Address         State
  tcp        0      0 ip-172-31-9-146.ec2:ssh 72-21-196-67.amaz:62519 ESTABLISHED
  tcp        0 345958 ip-172-31-9-146.ec2:ssh 72-21-196-67.amaz:25884 ESTABLISHED
  tcp        0      0 ip-172-31-9-146.ec2:ssh 72-21-196-67.amaz:18144 ESTABLISHED
  ```
15. Is the behavior expected?  If not, re-visit load-generator configuration.
