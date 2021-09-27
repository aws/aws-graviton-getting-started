#!/bin/bash

help_msg() {
  echo "usage: $0 [cpus] [default=threads|cores]"
}

if [[ $# -lt 1 ]]; then
  help_msg
  exit 1
fi

if [[ $(id -u) -ne 0 ]]; then
  echo "Must be run with sudo privileges"
  exit 1
fi

if [[ "$2" == "threads" && $(uname -m) == "aarch64" ]]; then
  echo "Can only specify 'cores' for hotplugging cpus on Graviton"
  exit 1
fi

# Re-enable all CPUs then modify the list
all_vcpus=$(lscpu -a -p=CPU | awk -F',' '$0 ~ /^[[:digit:]]+$/{print $1}')
for i in $all_vcpus; do
  echo 1 > /sys/devices/system/cpu/cpu$i/online
done

# Parse lscpu output to select the subset of cores/threads to hotplug in/out
case $2 in
  threads)
    let physical_cores=$1/2
    vcpus_on=$(lscpu -p=CPU,CORE | awk -F',' 'BEGIN{j='"${physical_cores}"'}$0 ~ /^[[:digit:]]+,[[:digit:]]+$/{if ($2<j) {print $1}; i++}')
    vcpus_off=$(lscpu -p=CPU,CORE | awk -F',' 'BEGIN{j='"${physical_cores}"'}$0 ~ /^[[:digit:]]+,[[:digit:]]+$/{if ($2>=j) {print $1}; i++}')
    ;;
  cores)
    let physical_cores=$1
    vcpus_on=$(lscpu -p=CPU,CORE | awk -F',' 'BEGIN{j='"${physical_cores}"'}$0 ~ /^[[:digit:]]+,[[:digit:]]+$/{if ($1<j) {print $1}; i++}')
    vcpus_off=$(lscpu -p=CPU,CORE | awk -F',' 'BEGIN{j='"${physical_cores}"'}$0 ~ /^[[:digit:]]+,[[:digit:]]+$/{if ($1>=j) {print $1}; i++}')
    ;;
  *)
    echo "Do not recognize option: $2"
    exit 1
esac

for i in $vcpus_on; do
  echo 1 > /sys/devices/system/cpu/cpu$i/online
done

for i in $vcpus_off; do
  echo 0 > /sys/devices/system/cpu/cpu$i/online
done

# Update Docker cpusets to reflect cpus that are hotplugged in/out to allow
# restarted containers so they see the proper number of CPUs
FILE=/sys/fs/cgroup/cpuset/docker/cpuset.cpus
if [ -f "$FILE" ]; then
  cp /sys/fs/cgroup/cpuset/cpuset.cpus /sys/fs/cgroup/cpuset/docker/cpuset.cpus
fi
