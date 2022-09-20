#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import io
import os
import subprocess

import numpy as np
import pandas as pd
from scipy import stats

# When calculating aggregate stats, if some are zero, may
# get a benign divide-by-zero warning from numpy, make it silent.
np.seterr(divide='ignore')
pd.options.mode.chained_assignment = None


def sar(time):
    """
    Measure sar into a buffer for parsing
    """
    try:
        env = dict(os.environ, S_TIME_FORMAT="ISO", LC_TIME="ISO")
        res = subprocess.run(["sar", "-o", "out.dat", "-A", "1", f"{time}"], timeout=time+5, env=env,
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        res = subprocess.run(["sar", "-f", "out.dat", "-A", "1"], env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        os.remove("out.dat")
        return io.StringIO(res.stdout.decode('utf-8'))
    except subprocess.CalledProcessError:
        print("Failed to measure statistics with sar.")
        print("Please check that sar is installed using install_perfrunbook_dependencies.sh and is in your PATH")
        return None


def mpstat(time):
    """
    Measure mpstat into a buffer for parsing
    """
    try:
        env = dict(os.environ, S_TIME_FORMAT="ISO", LC_TIME="ISO")
        res = subprocess.run(["mpstat", "-I", "ALL", "-o", "JSON", "1", f"{time}"], timeout=time+5, env=env,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return io.StringIO(res.stdout.decode('utf-8'))
    except subprocess.CalledProcessError:
        print("Failed to measure statistics with mpstat")
        print("Please check that sar is installed using install_perfrunbook_dependencies.sh and is in your PATH")


def plot_terminal(data, title, xlabel, yrange):
    """
    Plot data to the terminal using plotext
    """
    import plotext as plt
    x = data.index.tolist()
    y = data[title].tolist()

    plt.scatter(x, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylim(*yrange)
    plt.plot_size(100, 30)
    plt.show()


def calc_stats_and_plot(df, stat, yaxis_range=None):
    """
    Function that calculates the common stats and 
    plots the data.
    """
    df['time_delta'] = (df.index - df.index[0]).seconds
    df = df.set_index('time_delta')

    if yaxis_range:
        limit = yaxis_range
    else:
        limit = (0, df[stat].max() + 1)

    # Calculate some meaningful aggregate stats for comparing time-series plots
    geomean = stats.gmean(df[stat])
    p50 = stats.scoreatpercentile(df[stat], 50)
    p90 = stats.scoreatpercentile(df[stat], 90)
    p99 = stats.scoreatpercentile(df[stat], 99)
    xtitle = f"gmean:{geomean:>6.2f} p50:{p50:>6.2f} p90:{p90:>6.2f} p99:{p99:>6.2f}"

    plot_terminal(df, stat, xtitle, limit)


def parse_sar(sar_parse_class, buf):
    """
    Parse SAR output to a pandas dataframe
    """
    from sar_parse import parse_start_date
    line = buf.readline()
    start_date = parse_start_date(line)
    if not start_date:
        print("ERR: header not first line of Sar file, exiting")
        exit(1)

    parse = sar_parse_class(start_date)
    line = buf.readline()
    df = None
    while(line):
        df = parse.parse_for_header(line, buf, save_parquet=False)
        if (df is not None):
            break
        line = buf.readline()
    
    return df


def plot_cpu(buf, stat):
    """
    Plot cpu usage data from sar
    """
    from sar_parse import ParseCpuTime
    df = parse_sar(ParseCpuTime, buf)

    YAXIS_RANGE = (0, 100)

    group = df.groupby('cpu')
    data = group.get_group('all')

    calc_stats_and_plot(data, stat, yaxis_range=YAXIS_RANGE)


def plot_tcp(buf, stat):
    """
    Plot the numer of new connections being recieved over time
    """
    from sar_parse import ParseTcpTime
    df = parse_sar(ParseTcpTime, buf)

    calc_stats_and_plot(df, stat)


def plot_cswitch(buf, stat):
    """
    Plot cpu usage data from sar
    """
    from sar_parse import ParseCSwitchTime
    df = parse_sar(ParseCSwitchTime, buf)

    calc_stats_and_plot(df, stat)


def plot_irq(buf, stat):
    """
    Plot irq per second data from mpstat
    """
    from mpstat_parse import parse_mpstat_json_all_irqs
    import json
    irqs = json.load(buf)

    df = parse_mpstat_json_all_irqs(irqs)

    calc_stats_and_plot(df, stat)


def plot_specific_irq(buf, stat):
    """
    Plot a specific IRQ source
    """
    import json
    irqs = json.load(buf)

    # IPI0 - rescheduling interrupt
    # IPI1 - Function call interrupt
    # RES - rescheduling interrupt x86
    # CAL - function call interrupt x86
    from mpstat_parse import parse_mpstat_json_single_irq
    df = parse_mpstat_json_single_irq(irqs, stat)

    calc_stats_and_plot(df, stat)


stat_mapping = {
  "cpu-user": (sar, plot_cpu, "usr"),
  "cpu-kernel": (sar, plot_cpu, "sys"),
  "cpu-iowait": (sar, plot_cpu, "iowait"),
  "new-connections": (sar, plot_tcp, "passive"),
  "tcp-in-segments": (sar, plot_tcp, "iseg"),
  "tcp-out-segments": (sar, plot_tcp, "oseg"),
  "cswitch": (sar, plot_cswitch, "cswch_s"),
  "all-irqs": (mpstat, plot_irq, "irq_s"),
  "single-irq": (mpstat, plot_specific_irq, ""),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stat", default="cpu-user", type=str, choices=["cpu-user", "cpu-kernel", "cpu-iowait", 
                                                                         "new-connections", "tcp-in-segments", "tcp-out-segments",
                                                                         "cswitch","all-irqs","single-irq"])
    parser.add_argument("--irq", type=str, help="Specific IRQ to measure if single-irq chosen for stat")
    parser.add_argument("--time", default=60, type=int, help="How long to measure for in seconds")

    args = parser.parse_args()

    gather, plot, stat = stat_mapping[args.stat]

    if args.stat == "single-irq" and args.irq:
        stat = args.irq
    elif args.stat == "single-irq" and not args.irq:
        print("single-irq selected, need to specify --irq option")
        exit(1)

    text = gather(args.time)
    plot(text, stat)
