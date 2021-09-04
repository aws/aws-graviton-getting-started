#!/bin/bash

set -e

help_msg() {
 echo "Requires perf to be installed and in your PATH"
 echo "usage: $0 oncpu|offcpu [time seconds|default 300]"
}

capture_on_cpu () {
  perf record -a -g -k 1 -F99 -e cpu-clock:pppH -- sleep $1
  perf inject -j -i perf.data -o perf.data.jit
  perf script -f -i perf.data.jit > script.out
  ./FlameGraph/stackcollapse-perf.pl --kernel --jit script.out > folded.out
  ./FlameGraph/flamegraph.pl --colors java folded.out > flamegraph_oncpu_$4_$3_$2.svg
  rm perf.data perf.data.jit script.out folded.out
}

capture_off_cpu () {
  perf record -a -g -k 1 -F99 -e sched:sched_switch -- sleep $1
  perf inject -j -i perf.data -o perf.data.jit
  perf script -f -i perf.data.jit > script.out
  ./FlameGraph/stackcollapse-perf.pl --kernel --jit script.out > folded.out
  ./FlameGraph/flamegraph.pl --colors java folded.out > flamegraph_offcpu_$4_$3_$2.svg
  rm perf.data perf.data.jit script.out folded.out
}

if [[ $(id -u) -ne 0 ]]; then
  echo "Must be run with sudo privileges"
  exit 1
fi

if [[ $# -lt 1 ]]; then
  help_msg
  exit 1
fi

capture_time=300
if [[ $# -gt 1 ]]; then
  capture_time=$2
fi

date=$(date "+%Y-%m-%d_%H:%M:%S")
# Get meta-data using IMDSv2
token=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
instance_type=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-type)
instance_id=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-id)

# Test perf exists
test_perf=$(perf list &> /dev/null)
if [[ $? -ne 0 ]]; then
  help_msg
  exit 1
fi

if [[ "$1" == "oncpu" ]]; then
  capture_on_cpu $capture_time $date $instance_type $instance_id
elif [[ "$1" == "offcpu" ]]; then
  capture_off_cpu $capture_time $date $instance_type $instance_id
else
  help_msg
  exit 1
fi
