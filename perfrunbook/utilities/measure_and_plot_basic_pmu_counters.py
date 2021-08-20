#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import pandas as pd
import numpy as np
import re
import scipy as sp
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
    Plot data to the terminal using gnuplotlib
    """
    import gnuplotlib as gp
    x = data.index.to_numpy()
    y = data[title].to_numpy()
    gp.plot(x, y, _with = 'lines', terminal = 'dumb 160,40', unset = 'grid', title = title, xlabel = xtitle)


def plot_matplotlib(data, title, xtitle):
    """
    Plot the data using matplotlib via pandas to either a jupyter notebook frame or GUI window
    """
    import seaborn as sb
    import matplotlib

    sb.set(style="whitegrid")
    matplotlib.rc('xtick', labelsize=12)
    matplotlib.rc('ytick', labelsize=12)
    matplotlib.rc('axes', titlesize=16)
    matplotlib.rc('axes', labelsize=12)
    matplotlib.rc('figure', titlesize=18)
    matplotlib.rc('legend', fontsize=14)

    data.plot(y=title, figsize=(16, 8), xlabel=xtitle, title=title)


def plot_counter_stat(csv, plot_format, stat_name, counter_numerator,
                      counter_denominator, scale):
    """
    Process the returned csv file into a time-series statistic to plot and
    also calculate some useful aggregate stats.
    """
    df = pd.read_csv(csv, sep='|', header=0,
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

    if plot_format == "terminal":
        plot_terminal(df_processed, stat_name, xtitle)
    elif plot_format == "matplotlib":
        plot_matplotlib(df_processed, stat_name, xtitle)
    else:
        print(f"Do not know how to plot {plot_format}")


counter_mapping = {
                      "Graviton2":
                      {
                        "ipc": ["armv8_pmuv3_0/event=0x8/", "armv8_pmuv3_0/event=0x11/", 1],
                        "branch-mpki": ["armv8_pmuv3_0/event=0x10/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "data-l1-mpki": ["armv8_pmuv3_0/event=0x4/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "inst-l1-mpki": ["armv8_pmuv3_0/event=0x1/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "l2-mpki": ["armv8_pmuv3_0/event=0x17/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "l3-mpki": ["armv8_pmuv3_0/event=0x37/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "stall_frontend_pkc": ["armv8_pmuv3_0/event=0x23/", "armv8_pmuv3_0/event=0x11/", 1000],
                        "stall_backend_pkc": ["armv8_pmuv3_0/event=0x24/", "armv8_pmuv3_0/event=0x11/", 1000],
                        "inst-tlb-mpki": ["armv8_pmuv3_0/event=0x2/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "inst-tlb-tw-pki": ["armv8_pmuv3_0/event=0x35/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "data-tlb-mpki": ["armv8_pmuv3_0/event=0x5/", "armv8_pmuv3_0/event=0x8/", 1000],
                        "data-tlb-tw-pki": ["armv8_pmuv3_0/event=0x34/", "armv8_pmuv3_0/event=0x8/", 1000],
                        },
                      "CXL":
                      {
                        "ipc": ["cpu/event=0xc0,umask=0x0/", "cpu/event=0x3c,umask=0x0/", 1],
                        "branch-mpki": ["cpu/event=0xC5,umask=0x0/", "cpu/event=0xc0,umask=0x0/", 1000],
                        "data-l1-mpki": ["cpu/event=0x51,umask=0x1/", "cpu/event=0xc0,umask=0x0/", 1000],
                        "inst-l1-mpki": ["cpu/event=0x83,umask=0x2/", "cpu/event=0xc0,umask=0x0/", 1000],
                        "l2-mpki": ["cpu/event=0x24,umask=0x27/", "cpu/event=0xc0,umask=0x0/", 1000],
                        "l3-mpki": ["cpu/event=0xB0,umask=0x10/", "cpu/event=0xc0,umask=0x0/", 1000],
                        "stall_frontend_pkc": ["cpu/event=0x9C,umask=0x1,cmask=0x4/", "cpu/event=0x3c,umask=0x0/", 1000],
                        "stall_backend_pkc": ["cpu/event=0xA2,umask=0x1/", "cpu/event=0x3c,umask=0x0/", 1000],
                        "inst-tlb-mpki": ["cpu/event=0x85,umask=0x20/", "cpu/event=0x3c,umask=0x0/", 1000],
                        "inst-tlb-tw-pki": ["cpu/event=0x85,umask=0x01/", "cpu/event=0x3c,umask=0x0/", 1000],
                        # This counter just counts misses from loads, need to add stores here too...
                        "data-tlb-mpki": ["cpu/event=0x08,umask=0x20/", "cpu/event=0x3c,umask=0x0/", 1000],
                        "data-tlb-tw-pki": ["cpu/event=0x08,umask=0x01/", "cpu/event=0x3c,umask=0x0/", 1000],
                        # L2 TLB misses need to be calculated from multiple counters, this helper script does not support that.
                      }
                  }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stat", default="ipc", type=str, choices=["ipc", "branch-mpki", "data-l1-mpki", "inst-l1-mpki", "l2-mpki", "l3-mpki",
                                                                    "stall_frontend_pkc", "stall_backend_pkc", "inst-tlb-mpki", "inst-tlb-tw-pki",
                                                                    "data-tlb-mpki", "data-tlb-tw-pki", "l2-tlb-mpki"])
    parser.add_argument("--plot", default="terminal", type=str, choices=["terminal", "matplotlib"],
                        help="What display type to use, terminal (ascii art!) or matplotlib (for Jupyter notebooks)")
    parser.add_argument("--uarch", default="Graviton2", type=str, choices=["Graviton2", "CXL"],
                        help="What micro-architecture to use to define our events")
    parser.add_argument("--time", default=60, type=int, help="How long to measure for in seconds")

    res = subprocess.run(["id", "-u"], check=True, stdout=subprocess.PIPE)
    if int(res.stdout) > 0:
        print("Must be run under sudo privileges")
        exit(1)

    args = parser.parse_args()

    counter_info = counter_mapping[args.uarch][args.stat]

    csv = perfstat(args.time, *counter_info)
    plot_counter_stat(csv, args.plot, args.stat, *counter_info)

