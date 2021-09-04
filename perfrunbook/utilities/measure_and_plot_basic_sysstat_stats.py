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

def sar(time):
    """
    Measure sar into a buffer for parsing
    """
    try:
        res = subprocess.run(["sar", "-o", "out.dat", "-A", "1", f"{time}"], timeout = time+5,
                             check = True, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        res = subprocess.run(["sar", "-f", "out.dat", "-A", "1"], check = True, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        os.remove("out.dat")
        return io.StringIO(res.stdout.decode('utf-8'))
    except subprocess.CalledProcessError:
        print("Failed to measure statistics with sar.")
        print("Please check that sar is installed using install_perfrunbook_dependencies.sh and is in your PATH")
        return None


def plot_terminal(data, title, xlabel, yrange):
    """
    Plot data to the terminal using gnuplot
    """
    import gnuplotlib as gp
    x = data.index.to_numpy()
    y = data[title].to_numpy()
    gp.plot(x, y, _with = 'lines', terminal = 'dumb 160,40', unset = 'grid', set = f"yrange [{yrange[0]}:{yrange[1]}]", title = title, xlabel = xlabel)


def plot_matplotlib(data, title, xlabel, yrange):
    import seaborn as sb
    import matplotlib

    sb.set(style="whitegrid")
    matplotlib.rc('xtick', labelsize=12)
    matplotlib.rc('ytick', labelsize=12)
    matplotlib.rc('axes', titlesize=16)
    matplotlib.rc('axes', labelsize=12)
    matplotlib.rc('figure', titlesize=18)
    matplotlib.rc('legend', fontsize=14)

    data.plot(figsize=(24,8), xlabel=xlabel, ylim=(yrange[0], yrange[1]), title=title)


def plot_cpu(buf, stat, plot_format):
    """
    Plot cpu usage data from sar
    """
    YAXIS_RANGE = (0,100)
    from sar_parse import ParseCpuTime, parse_start_date
    line = buf.readline()
    start_date = parse_start_date(line)
    if not start_date:
        print("ERR: header not first line of Sar file, exiting")
        exit(1)

    parseCPU = ParseCpuTime(start_date)
    line = buf.readline()
    df = None
    while (line):
        df = parseCPU.parse_for_header(line, buf, save_parquet=False)
        if (df is not None):
            break
        line = buf.readline()

    df['time_delta'] = (df.index - df.index[0]).seconds
    df = df.set_index('time_delta')

    group = df.groupby('cpu')
    data = group.get_group('all')

    # Calculate some meaningful aggregate stats for comparing time-series plots
    geomean = stats.gmean(data[stat])
    p50 = stats.scoreatpercentile(data[stat], 50)
    p90 = stats.scoreatpercentile(data[stat], 90)
    p99 = stats.scoreatpercentile(data[stat], 99)
    xtitle = f"gmean:{geomean:>6.2f} p50:{p50:>6.2f} p90:{p90:>6.2f} p99:{p99:>6.2f}"

    if plot_format == "terminal":
        plot_terminal(data, stat, xtitle, YAXIS_RANGE)
    elif plot_format == "matplotlib":
        plot_matplotlib(data, stat, xtitle, YAXIS_RANGE)
    else:
        print(f"Do not know how to plot {plot_format}")


def plot_tcp(buf, stat, plot_format):
    """
    Plot the numer of new connections being recieved over time
    """
    from sar_parse import ParseTcpTime, parse_start_date
    line = buf.readline()
    start_date = parse_start_date(line)
    if not start_date:
        print("ERR: header not first line of Sar file, exiting")
        exit(1)

    parseTcp = ParseTcpTime(start_date)
    line = buf.readline()
    df = None
    while (line):
        df = parseTcp.parse_for_header(line, buf, save_parquet=False)
        if (df is not None):
            break
        line = buf.readline()

    df['time_delta'] = (df.index - df.index[0]).seconds
    df = df.set_index('time_delta')

    limit = df[stat].max() + 1

    # Calculate some meaningful aggregate stats for comparing time-series plots
    geomean = stats.gmean(df[stat])
    p50 = stats.scoreatpercentile(df[stat], 50)
    p90 = stats.scoreatpercentile(df[stat], 90)
    p99 = stats.scoreatpercentile(df[stat], 99)
    xtitle = f"gmean:{geomean:>6.2f} p50:{p50:>6.2f} p90:{p90:>6.2f} p99:{p99:>6.2f}"

    if plot_format == "terminal":
        plot_terminal(df, stat, xtitle, (0, limit))
    elif plot_format == "matplotlib":
        plot_matplotlib(df, stat, xtitle, (0, limit))
    else:
        print(f"Do not know how to plot {plot_format}")



stat_mapping = {
  "cpu-user": (plot_cpu, "usr"),
  "cpu-kernel": (plot_cpu, "sys"),
  "cpu-iowait": (plot_cpu, "iowait"),
  "new-connections": (plot_tcp, "passive"),
  "tcp-in-segments": (plot_tcp, "iseg"),
  "tcp-out-segments": (plot_tcp, "oseg")
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stat", default="cpu-user", type=str, choices=["cpu-user", "cpu-kernel", "cpu-iowait", 
                                                                         "new-connections", "tcp-in-segments", "tcp-out-segments"])
    parser.add_argument("--plot", default="terminal", type=str, choices=["terminal", "matplotlib"],
                        help="What display type to use, terminal (ascii art!) or matplotlib (for Jupyter notebooks)")
    parser.add_argument("--time", default=60, type=int, help="How long to measure for in seconds")

    args = parser.parse_args()

    text = sar(args.time)
    func = stat_mapping[args.stat][0]
    stat = stat_mapping[args.stat][1]

    func(text, stat, args.plot)
