#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import pandas as pd
import numpy as np
import re
from scipy import stats
import subprocess
import io

# When calculating aggregate stats, if some are zero, may
# get a benign divide-by-zero warning from numpy, make it silent.
np.seterr(divide='ignore')


def perfstat(time, counter_numerator, counter_denominator, __unused__):
    """
    Measure performance counters using perf-stat in a subprocess.  Return a CSV buffer of the values measured.
    """
    try:
        res = subprocess.run(["lscpu", "-p=CPU"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = io.StringIO(res.stdout.decode('utf-8'))
        cpus = []
        for line in output.readlines():
            match = re.search(r'''^(\d+)$''', line)
            if match is not None:
                cpus.append(match.group(1))

        res = subprocess.run(["perf", "stat", f"-C{','.join(cpus)}", "-I1000", "-x|", "-a", "-e", f"{counter_numerator}", "-e", f"{counter_denominator}", "--", "sleep", f"{time}"],
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return io.StringIO(res.stdout.decode('utf-8'))
    except subprocess.CalledProcessError:
        print("Failed to measure performance counters.")
        print("Please check that perf is installed using install_perfrunbook_dependencies.sh and in your PATH")
        return None


def plot_terminal(data, title, xtitle):
    """
    Plot data to the terminal using plotext
    """
    import plotext as plt
    x = data.index.tolist()
    y = data[title].tolist()

    plt.scatter(x, y)
    plt.title(title)
    plt.xlabel(xtitle)
    plt.plot_size(100, 30)
    plt.show()


def plot_counter_stat(csv, stat_name, counter_numerator,
                      counter_denominator, scale):
    """
    Process the returned csv file into a time-series statistic to plot and
    also calculate some useful aggregate stats.
    """
    df = pd.read_csv(csv, sep='|',
                     names=['time', 'count', 'rsrvd1', 'event',
                            'rsrvd2', 'frac', 'rsrvd3', 'rsrvd4'],
                     dtype={'time': np.float64, 'count': np.float64,
                            'rsrvd1': str, 'event': str, 'rsrvd2': str,
                            'frac': np.float64, 'rsrvd3': str, 'rsrvd4': str})
    df_processed = pd.DataFrame()

    df_processed[stat_name] = (df[df['event'] == counter_numerator]['count'].reset_index(drop=True)) / (df[df['event'] == counter_denominator]['count'].reset_index(drop=True)) * scale
    df_processed.dropna(inplace=True)

    # Calculate some meaningful aggregate stats for comparing time-series plots
    geomean = stats.gmean(df_processed[stat_name])
    p50 = stats.scoreatpercentile(df_processed[stat_name], 50)
    p90 = stats.scoreatpercentile(df_processed[stat_name], 90)
    p99 = stats.scoreatpercentile(df_processed[stat_name], 99)
    xtitle = f"gmean:{geomean:>6.2f} p50:{p50:>6.2f} p90:{p90:>6.2f} p99:{p99:>6.2f}"

    plot_terminal(df_processed, stat_name, xtitle)


def get_cpu_type():
    GRAVITON_MAPPING = {"0xd0c": "Graviton2", "0xd40": "Graviton3"}
    with open("/proc/cpuinfo", "r") as f:
        for line in f.readlines():
            if "model name" in line:
                return line.split(":")[-1].strip()
            elif "CPU part" in line:
                cpu = line.split(":")[-1].strip()
                return GRAVITON_MAPPING[cpu]


UNIVERSAL_GRAVITON_CTRS = {
    "ipc": ["armv8_pmuv3_0/event=0x8/", "armv8_pmuv3_0/event=0x11/", 1],
    "branch-mpki": ["armv8_pmuv3_0/event=0x10/", "armv8_pmuv3_0/event=0x8/", 1000],
    "data-l1-mpki": ["armv8_pmuv3_0/event=0x3/", "armv8_pmuv3_0/event=0x8/", 1000],
    "inst-l1-mpki": ["armv8_pmuv3_0/event=0x1/", "armv8_pmuv3_0/event=0x8/", 1000],
    "l2-mpki": ["armv8_pmuv3_0/event=0x17/", "armv8_pmuv3_0/event=0x8/", 1000],
    "l3-mpki": ["armv8_pmuv3_0/event=0x37/", "armv8_pmuv3_0/event=0x8/", 1000],
    "stall_frontend_pkc": ["armv8_pmuv3_0/event=0x23/", "armv8_pmuv3_0/event=0x11/", 1000],
    "stall_backend_pkc": ["armv8_pmuv3_0/event=0x24/", "armv8_pmuv3_0/event=0x11/", 1000],
    "inst-tlb-mpki": ["armv8_pmuv3_0/event=0x2/", "armv8_pmuv3_0/event=0x8/", 1000],
    "inst-tlb-tw-pki": ["armv8_pmuv3_0/event=0x35/", "armv8_pmuv3_0/event=0x8/", 1000],
    "data-tlb-mpki": ["armv8_pmuv3_0/event=0x5/", "armv8_pmuv3_0/event=0x8/", 1000],
    "data-tlb-tw-pki": ["armv8_pmuv3_0/event=0x34/", "armv8_pmuv3_0/event=0x8/", 1000],
    "code-sparsity": ["armv8_pmuv3_0/event=0x11c/", "armv8_pmuv3_0/event=0x8/", 1000],
}
GRAVITON3_CTRS = {
    "stall_backend_mem_pkc": ["armv8_pmuv3_0/event=0x4005/", "armv8_pmuv3_0/event=0x11/", 1000],
}
UNIVERSAL_INTEL_CTRS = {
    "ipc": ["cpu/event=0xc0,umask=0x0/", "cpu/event=0x3c,umask=0x0/", 1],
    "branch-mpki": ["cpu/event=0xC5,umask=0x0/", "cpu/event=0xc0,umask=0x0/", 1000],
    "data-l1-mpki": ["cpu/event=0x51,umask=0x1/", "cpu/event=0xc0,umask=0x0/", 1000],
    "inst-l1-mpki": ["cpu/event=0x24,umask=0xe4/", "cpu/event=0xc0,umask=0x0/", 1000],
    "l2-mpki": ["cpu/event=0xf1,umask=0x1f/", "cpu/event=0xc0,umask=0x0/", 1000],
    "l3-mpki": ["cpu/event=0x2e,umask=0x41/", "cpu/event=0xc0,umask=0x0/", 1000],
    "stall_frontend_pkc": ["cpu/event=0x9C,umask=0x1,cmask=0x4/", "cpu/event=0x3c,umask=0x0/", 1000],
    "stall_backend_pkc": ["cpu/event=0xA2,umask=0x1/", "cpu/event=0x3c,umask=0x0/", 1000],
    "inst-tlb-mpki": ["cpu/event=0x85,umask=0x20/", "cpu/event=0x3c,umask=0x0/", 1000],
    "inst-tlb-tw-pki": ["cpu/event=0x85,umask=0x01/", "cpu/event=0x3c,umask=0x0/", 1000],
    "data-tlb-mpki": ["cpu/event=0x08,umask=0x20/", "cpu/event=0xc0,umask=0x0/", 1000],
    "data-st-tlb-mpki": ["cpu/event=0x49,umask=0x20/", "cpu/event=0xc0,umask=0x0/", 1000],
    "data-tlb-tw-pki": ["cpu/event=0x08,umask=0x01/", "cpu/event=0xc0,umask=0x0/", 1000],
    "data-st-tlb-tw-pki": ["cpu/event=0x49,umask=0x01/", "cpu/event=0xc0,umask=0x0/", 1000],
}
ICX_CTRS = {
    "stall_frontend_pkc": ["cpu/event=0x9C,umask=0x1,cmask=0x5/", "cpu/event=0x3c,umask=0x0/", 1000],
    "stall_backend_pkc": ["cpu/event=0xa4,umask=0x2/", "cpu/event=0xa4,umask=0x01/", 1000], 
}

filter_proc = {
    "Graviton2": UNIVERSAL_GRAVITON_CTRS,
    "Graviton3": {**UNIVERSAL_GRAVITON_CTRS, **GRAVITON3_CTRS},
    "Intel(R) Xeon(R) Platinum 8124M CPU @ 3.00GHz": UNIVERSAL_INTEL_CTRS,
    "Intel(R) Xeon(R) Platinum 8175M CPU @ 2.50GHz": UNIVERSAL_INTEL_CTRS,
    "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz": UNIVERSAL_INTEL_CTRS,
    "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz": UNIVERSAL_INTEL_CTRS,
    "Intel(R) Xeon(R) Platinum 8375C CPU @ 2.90GHz": {**UNIVERSAL_INTEL_CTRS, **ICX_CTRS}
}

if __name__ == "__main__":
    processor_version = get_cpu_type()
    try:
        stat_choices = list(filter_proc[processor_version].keys())
    except:
        print(f"{processor_version} is not supported")
        exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--stat", default="ipc", type=str, choices=stat_choices)
    parser.add_argument("--time", default=60, type=int, help="How long to measure for in seconds")
    parser.add_argument("--custom_ctr", type=str,
                        help="Specify a custom counter ratio and scaling factor as 'ctr1|ctr2|scale'"
                             ", calculated as ctr1/ctr2 * scale")

    res = subprocess.run(["id", "-u"], check=True, stdout=subprocess.PIPE)
    if int(res.stdout) > 0:
        print("Must be run under sudo privileges")
        exit(1)

    args = parser.parse_args()

    if args.custom_ctr:
        ctrs = args.custom_ctr.split("|")
        counter_info = [ctrs[0], ctrs[1], int(ctrs[2])]
    else:
        counter_info = filter_proc[processor_version][args.stat]

    csv = perfstat(args.time, *counter_info)
    plot_counter_stat(csv, args.stat, *counter_info)
