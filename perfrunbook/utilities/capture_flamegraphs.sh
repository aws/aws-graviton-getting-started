#!/bin/bash

set -e

let capture_freq=99

# search replace filter that will combine thread names like 
# GC-Thread-1 to GC-Thread- in perf-script sample header lines.
sr_filter='s/^([a-zA-Z\-]+)[0-9]*-?([a-zA-z]*) (.*?)$/\1\2 \3/g'

help_msg() {
 echo "Requires perf to be installed and in your PATH"
 echo "usage: $0 oncpu|offcpu|<custom_event> [time seconds|default 300] --f|--frequency 99 -r|--regexfilter 's/hi/bye/g'"
 echo "custom_event is any event listed in perf-list"
}

process_perf_data () {
  perf inject -j -i perf.data -o perf.data.jit
  perf script -f -i perf.data.jit > script.out
  
  if [[ ! -z "${sr_filter}" ]]; then
    perl -pi -e "${sr_filter}" script.out
  fi
  ./FlameGraph/stackcollapse-perf.pl --kernel --jit script.out > folded.out
  ./FlameGraph/flamegraph.pl --colors java folded.out > flamegraph_$1_$4_$3_$2.svg
  rm perf.data perf.data.jit script.out folded.out
}

capture_on_cpu () {
  perf record -a -g -k 1 -F${capture_freq} -e cpu-clock:pppH -- sleep $1
  process_perf_data "oncpu" $2 $3 $4
}

capture_off_cpu () {
  perf record -a -g -k 1 -F${capture_freq} -e sched:sched_switch -- sleep $1
  process_perf_data "offcpu" $2 $3 $4
}

capture_custom_event () {
  perf record -a -g -k 1 -F${capture_freq} -e $1 -- sleep $2
  process_perf_data $1 $3 $4 $5
}

if [[ $(id -u) -ne 0 ]]; then
  echo "Must be run with sudo privileges"
  exit 1
fi

# Test perf exists
test_perf=$(perf list &> /dev/null)
if [[ $? -ne 0 ]]; then
  help_msg
  exit 1
fi

date=$(date "+%Y-%m-%d_%H:%M:%S")
# Get meta-data using IMDSv2
token=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
instance_type=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-type)
instance_id=$(curl -s -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-id)

POSITIONAL=()
while [[ $# -gt 0 ]]
do
  key="$1"
  case $key in
    -f|--frequency)
      let capture_freq="$2"
      shift; shift
      ;;
    -r|--regexfilter)
      sr_filter="$2"
      shift; shift
      ;;
    -h|--help)
      help_msg
      exit 1
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done
set -- "${POSITIONAL[@]}"

if [[ $# -lt 1 ]]; then
  help_msg
  exit 1
fi

capture_time=300
if [[ $# -gt 1 ]]; then
  capture_time=$2
fi

if [[ "$1" == "oncpu" ]]; then
  capture_on_cpu $capture_time $date $instance_type $instance_id
elif [[ "$1" == "offcpu" ]]; then
  capture_off_cpu $capture_time $date $instance_type $instance_id
else
  capture_custom_event $1 $capture_time $date $instance_type $instance_id
fi
