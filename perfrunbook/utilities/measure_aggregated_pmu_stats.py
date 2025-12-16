#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import copy
import glob
import json
import math
import os
import re
import signal
import subprocess
from collections import defaultdict, namedtuple

import numpy as np
import pandas as pd
from scipy import stats


# When calculating aggregate stats, if some are zero, may
# get a benign divide-by-zero warning from numpy, make it silent.
np.seterr(divide="ignore")

# Constants
SAMPLE_INTERVAL = 5
RESULTS_CSV = "/tmp/stats.csv"
RESULTS_JSON = "/tmp/stats.json"


# Classes
class SignalWatcher:
    """
    Watch for SIGTERM, SIGINT and SIGALRM to stop collection
    """

    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_and_cleanup)
        signal.signal(signal.SIGTERM, self.exit_and_cleanup)
        signal.signal(signal.SIGALRM, self.exit_and_cleanup)

    def exit_and_cleanup(self, *args):
        self.kill_now = True

    def __del__(self):
        # When object goes out of scope, reset our signal handlers to default handlers
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)


#Counter = namedtuple("Counter", "ctr1 ctr2")
class PMUEventCounter:
    def __init__(self, name, program_str, per_cpu=True, agg_func=None):
        self.name = name
        self.program_str = program_str
        self.per_cpu = per_cpu
        self.pmu = None
        self.agg_func = agg_func or "sum"

    def __eq__(self, other):
        return self.name == other.get_canonical_name()

    def __hash__(self):
        return hash(self.name)

    def get_canonical_name(self):
        return self.name

    def set_pmu(self, pmu):
        self.pmu = self.pmu or pmu

    def get_event_to_program(self, group):
        """
        Returns an event to program, which may be different than the
        canonical name.  This is useful for naming
        """
        return f"{self.pmu}/{self.program_str},name={group}-{self.get_canonical_name()}/"

    def is_per_cpu(self):
        return self.per_cpu


class PMUCompositeEventCounter(PMUEventCounter):
    def get_event_to_program(self, group):
        """
        Specific to some events like Gv4 mesh events where we need to measure multiple
        events for perf to multiplex on our behalf and then combine later.
        """
        program_strings = []
        for events in self.program_str:
            ps = f"{self.pmu}/{events},name={group}-{self.get_canonical_name()}/"
            program_strings.append(ps)

        return f"{','.join(program_strings)}"
    

class ArmCMN700EventCounter(PMUEventCounter):
    """
    This counter sets up an event or pair of events to monitor
    on a CMN700 mesh that may support multi-socket.
    """

    pmus = []

    @staticmethod
    def detect_pmus():
        paths = glob.glob("/sys/devices/arm_cmn_*")
        return [os.path.basename(path) for path in paths]

    def __init__(self, name, program_str, per_cpu=False, agg_func=None):
        super().__init__(name, program_str, per_cpu, agg_func)

        if not ArmCMN700EventCounter.pmus:
            ArmCMN700EventCounter.pmus = ArmCMN700EventCounter.detect_pmus()

    def get_event_to_program(self, group):
        """
        This is specific to the CMN700 on Grv4
        """

        program_strings = []
        for pmu in ArmCMN700EventCounter.pmus:
            ps = f"{pmu}/{self.program_str},name={group}-{self.get_canonical_name()}/"
            program_strings.append(ps)

        return f"{','.join(program_strings)}"


class CounterConfig:
    """
    Defines a PMU counter ratio of 1 or 2 counters and a scale factor.
    """
    def __init__(self, pmu, name, numerator, denominator, scale):
        self.pmu = pmu
        self.name = name
        if isinstance(numerator, str):
            self.numerator = PMUEventCounter(numerator, numerator)
        elif isinstance(numerator, PMUEventCounter):
            self.numerator = numerator
        else:
            raise TypeError("Unknown type passed in for numerator")
        self.numerator.set_pmu(pmu)

        if isinstance(denominator, str):
            self.denominator = PMUEventCounter(denominator, denominator)
        elif isinstance(numerator, PMUEventCounter):
            self.denominator = denominator
        if self.denominator is not None:
            self.denominator.set_pmu(pmu)

        self.scale = scale

    def get_name(self):
        return self.name

    def get_pmu(self):
        return self.pmu

    def get_numerator(self):
        return self.numerator

    def get_denominator(self):
        return self.denominator

    def _compute_stat(self, ctr1_df, ctr2_df, idx):
        # Divide ctr1 by ctr2 matched up by indices over a preset value.
        try:
            s = (ctr1_df.loc[idx]["count"] / ctr2_df.loc[idx]["count"]) * self.scale  # noqa
            s = s.dropna()
            return s
        except Exception:
            return None

    def create_stat(self, df):
        """
        Returns series of the counter ratios from the individual counter measurements for
        plotting or statistical manipulation
        """
        # Group the same counters together that may form a composite event, or come from different PMUs, and aggregate their counts
        dfs = []
        dfn = (
            df[df["counter"] == self.numerator.get_canonical_name()][["count", "event", "group", "counter"]]
            .reset_index()
            .groupby(by=["normalized_time", "CPU", "event", "group", "counter"], as_index=False)
            .aggregate(self.numerator.agg_func)
            .set_index(["normalized_time", "CPU"])
        )
        dfs.append(dfn)
        if self.denominator:
            dfd = (
                df[df["counter"] == self.denominator.get_canonical_name()][["count", "event", "group", "counter"]]
                .reset_index()
                .groupby(by=["normalized_time", "CPU", "event", "group", "counter"], as_index=False)
                .aggregate(self.denominator.agg_func)
                .set_index(["normalized_time", "CPU"])
            )
            dfs.append(dfd)
        df = pd.concat(dfs, sort=False).sort_index()


        if self.numerator and not self.denominator:
            return (df[df["counter"] == self.numerator.get_canonical_name()]["count"].reset_index(drop=True)) * self.scale

        # Find the groups our counters belong to, the intersection of the groups are the measurements we
        # can use to calculate the ratio accurately.
        series = []
        group_id = (
            set(df[df["counter"] == self.numerator.get_canonical_name()]["group"].unique())
            & set(df[df["counter"] == self.denominator.get_canonical_name()]["group"].unique())
        )

        for group in group_id:
            ctr1_df = df[(df["counter"] == self.numerator.get_canonical_name()) & (df["group"] == group)]
            ctr2_df = df[(df["counter"] == self.denominator.get_canonical_name()) & (df["group"] == group)]

            idx = df[(df["group"] == group)].index

            s = self._compute_stat(ctr1_df, ctr2_df, idx)
            if s is not None and s.size:
                series.append(s)

        if len(series):
            return pd.concat(series)
        else:
            return None


# Specializations of the CounterConfig class
class ArmCounterConfig(CounterConfig):
    def __init__(self, name, counter1, counter2, scale):
        super().__init__("armv8_pmuv3_0", name, counter1, counter2, scale)

class ArmCounterPKC(ArmCounterConfig):
    def __init__(self, name, event_name, event, scale=1):
        super().__init__(name, PMUEventCounter(event_name, event),
                         PMUEventCounter("cycles", "event=0x11"), scale*1000)

class ArmCounterPKI(ArmCounterConfig):
    def __init__(self, name, event_name, event, scale=1):
        super().__init__(name, PMUEventCounter(event_name, event),
                         PMUEventCounter("instructions", "event=0x8"), scale*1000)

class ArmCMNCounterConfig(CounterConfig):
    def __init__(self, name, counter1, counter2, scale):
        super().__init__("arm_cmn_0", name, counter1, counter2, scale)

class ArmCMN700CounterConfig(CounterConfig):
    def __init__(self, name, counter1, counter2, scale):
        super().__init__("arm_cmn_*", name, counter1, counter2, scale)

class x86CounterConfig(CounterConfig):
    def __init__(self, name, counter1, counter2, scale):
        super().__init__("cpu", name, counter1, counter2, scale)

class x86CounterPKI(x86CounterConfig):
    def __init__(self, name, event_name, event, scale=1):
        super().__init__(name, PMUEventCounter(event_name, event),
                         PMUEventCounter("instructions", "event=0xc0,umask=0x0"), scale*1000)

class IntelCounterPKC(x86CounterConfig):
    def __init__(self, name, event_name, event, scale=1):
        super().__init__(name, PMUEventCounter(event_name, event),
                         PMUEventCounter("cycles", "event=0x3c,umask=0x0"), scale*1000)

class AMDCounterPKC(x86CounterConfig):
    def __init__(self, name, event_name, event):
        super().__init__(name, PMUEventCounter(event_name, event),
                         PMUEventCounter("cycles", "event=0x76,umask=0x0"), 1000)


# function to mask signals for a child process, and catch them only in the parent.
def mask_signals():
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGALRM})


# Measurement and processing functions
def perfstat(counter_groups, timeout=None, cpus=None):
    """
    Measure performance counters using perf-stat in a subprocess.
    Stores results into a CSV file.  Uses our own multiplexing loop
    which is cheaper than letting perf in the kernel do multiplexing.
    """
    try:
        if not cpus:
            res = subprocess.run(["lscpu", "-p=CPU"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            cpus = []
            for line in res.stdout.decode("utf-8").splitlines():
                match = re.search(r"""^(\d+)$""", line)
                if match is not None:
                    cpus.append(match.group(1))

        sig = SignalWatcher()
        if timeout:
            signal.alarm(timeout)
        out = open(RESULTS_CSV, "a")

        while not sig.kill_now:  # waits until a full measurement cycle is done.
            i = 0
            for pmu in counter_groups.keys():
                for ctrset in counter_groups[pmu]:
                    group = f"group{i}"
                    # Forms the perf counter format with a unique group and hash to form the name
                    #XXX: For arm_cmn, getting a None type for a counter to program, so that's odd....
                    counters = [ctr.get_event_to_program(group)for ctr in ctrset]
                    # Collect everything un-aggregated.  So we can see lightly loaded CPUs

                    perf_cmd = [
                        "perf",
                        "stat",
                        f"-I{2 * SAMPLE_INTERVAL * 1000}",
                        "-A",
                        "-x|",
                        "-a",
                        "-e",
                        f"{','.join(counters)}",
                    ]

                    # Assumes we don't mix counter types (we shouldn't as its per pmu)
                    for ctr in ctrset:
                        if ctr.is_per_cpu():
                            perf_cmd.append(f"-C{','.join(cpus)}")
                            break
                        else:
                            perf_cmd.append(f"-C0")
                            break

                    perf_cmd.extend([
                        "--",
                        "sleep",
                        f"{SAMPLE_INTERVAL}",
                    ])

                    # TODO: How to work with CMN and tell perf how to program the PMU
                    proc = subprocess.Popen(
                        perf_cmd,
                        preexec_fn=mask_signals,
                        stdout=subprocess.PIPE,
                        stderr=out,
                    )
                    proc.wait()
                    i += 1
        out.close()
        if timeout:
            # Cancel the timeout if any before leaving the loop
            signal.alarm(0)
    except subprocess.CalledProcessError:
        print("Failed to measure performance counters.")


def calculate_counter_stat(platforms):
    """
    Process out csv file from perf out to a set of aggregate statistics
    """
    df = pd.read_csv(
        RESULTS_CSV,
        sep="|",
        header=None,
        names=["time", "CPU", "count", "rsrvd1", "event", "rsrvd2", "frac", "rsrvd3", "rsrvd4"],
        dtype={
            "time": np.float64,
            "CPU": str,
            "count": np.float64,
            "rsrvd1": str,
            "event": str,
            "rsrvd2": str,
            "frac": np.float64,
            "rsrvd3": str,
            "rsrvd4": str,
        },
        na_values=["<not counted>", "<not supported>"],
    )

    # Filter counter event names into a group id and back
    # into the human readable counter definition.
    def split_counter_group(row):
        group, counter = row.event.split("-")
        row["group"] = group
        row["counter"] = counter
        return row

    # Normalize our time value to serve as an index along with CPU
    # for easier processing.
    time_offset = 0
    cur_time = 0
    cur_group_id = ""

    def normalize_time(row):
        # Each time the group changes, update our time offset as we have started
        # a new set of measurements, but time resets.
        nonlocal time_offset
        nonlocal cur_time
        nonlocal cur_group_id
        # Initial group_id assignment
        if not cur_group_id:
            cur_group_id = row["group"]
        if cur_group_id != row["group"]:
            time_offset = int(math.ceil(time_offset + row["time"]))
            cur_group_id = row["group"]
        cur_time = int(math.ceil(row["time"] + time_offset))  # round up to whole seconds
        row["normalized_time"] = cur_time
        return row

    df = df.apply(split_counter_group, axis=1)
    df = df.apply(normalize_time, axis=1)
    df = df.set_index(["normalized_time", "CPU"])
    data = {}

    for platform in platforms:
        counter_list = platform.get_counters()
        for counter in counter_list:
            stat_name = counter.get_name()
            series_res = counter.create_stat(df)

            try:
                series_res.replace([np.inf, -np.inf], np.nan, inplace=True)
                series_res.dropna(inplace=True)

                # Calculate some meaningful aggregate stats for comparisons
                geomean = stats.gmean(series_res)
                p10 = stats.scoreatpercentile(series_res, 10)
                p50 = stats.scoreatpercentile(series_res, 50)
                p90 = stats.scoreatpercentile(series_res, 90)
                p95 = stats.scoreatpercentile(series_res, 95)
                p99 = stats.scoreatpercentile(series_res, 99)
                p999 = stats.scoreatpercentile(series_res, 99.9)
                p100 = stats.scoreatpercentile(series_res, 100)

                data[stat_name] = {
                    "geomean": geomean,
                    "p10": p10,
                    "p50": p50,
                    "p90": p90,
                    "p95": p95,
                    "p99": p99,
                    "p99.9": p999,
                    "p100": p100,
                }
            except:  # noqa
                data[stat_name] = {
                    "geomean": 0,
                    "p10": 0,
                    "p50": 0,
                    "p90": 0,
                    "p95": 0,
                    "p99": 0,
                    "p99.9": 0,
                    "p100": 0,
                }
    with open(RESULTS_JSON, "w") as f:
        json.dump(data, f)
    return data


def pretty_print_table(counter_table):
    """
    Takes a table of calculated counter ratios and percentiles and
    prints them in a formatted table for viewing.
    """
    ratios = [key for key in counter_table.keys()]
    stats = [key for key in counter_table[ratios[0]].keys()]

    hdr_string = f"|{'Ratio':<20}|"
    for stat in stats:
        hdr_string += f"{stat:>10}|"

    print(hdr_string)
    for ratio in ratios:
        line = f"|{ratio:<20}|"
        for stat in stats:
            line += f"{counter_table[ratio][stat]:>10.2f}|"
        print(line)


def build_groups(platforms):
    """
    Takes a list of counter ratios and divides them into a minimal set of groups that we
    can multiplex onto the CPU PMU.  Numerators and denominators are scheduled together
    to avoid artifacts with the ratios.
    """
    # Counter groupings by denominator
    pmu_sets = {}
    for platform in platforms:
        groups = defaultdict(list)
        MAX_COUNTERS_IN_GROUP = platform.get_max_ctrs()

        counters = platform.get_counters()
        pmu = None
        for ctr in counters:
            denom = ctr.get_denominator()
            numer = ctr.get_numerator()
            pmu = ctr.get_pmu()

            groups[denom].append(numer)

        counter_sets = []
        current_set = set()

        for denom in groups.keys():
            # Make a copy of the list because we're going to mutate it
            numerators = groups[denom].copy()
            while len(numerators):
                # Make sure to add the denominator to the set, if and only if
                # it is not there and we have space for another numerator.
                # One exception is for counter ratios with no denominator.
                if (denom) and (denom not in current_set):
                    if len(current_set) < (MAX_COUNTERS_IN_GROUP - 1):
                        current_set.add(denom)
                    else:
                        # Counter set cannot fit a new denominator and
                        # at least 1 numerator in group
                        counter_sets.append(current_set)
                        current_set = set()
                        continue

                if len(current_set) < MAX_COUNTERS_IN_GROUP:
                    current_set.add(numerators.pop(0))
                else:
                    # Out of space for a numerator
                    counter_sets.append(current_set)
                    current_set = set()

        # Add final counter set.
        if len(current_set):
            counter_sets.append(current_set)
        if pmu not in pmu_sets:
            pmu_sets[pmu] = counter_sets
        else:
            pmu_sets[pmu].extend(counter_sets)

    return pmu_sets


def get_cpu_type():
    GRAVITON_MAPPING = {
        "0xd0c": "Graviton2",
        "0xd40": "Graviton3",
        "0xd4f": "Graviton4",
        "0xd84": "Graviton5"
    }
    AMD_MAPPING = {
        "7R13": "Milan",
        "9R14": "Genoa",
        "9R45": "Turin"
    }

    with open("/proc/cpuinfo", "r") as f:
        for line in f.readlines():
            if "model name" in line:
                ln = line.split(":")[-1].strip()
                if "AMD EPYC" in ln:
                    # Return the model number of the AMD CPU, its the 3rd entry in format
                    # AMD EPYC <model>
                    return AMD_MAPPING[ln.split(" ")[2]]
                else:
                    return ln
            elif "CPU part" in line:
                cpu = line.split(":")[-1].strip()
                return GRAVITON_MAPPING[cpu]


class PlatformDetails:
    def __init__(self, counter_list, max_ctrs):
        self.counter_list = copy.deepcopy(counter_list)
        self.max_ctrs = max_ctrs

    def get_max_ctrs(self) -> int:
        return self.max_ctrs

    def get_counters(self) -> list:
        return self.counter_list


def _agg_gv5_l3_misses(x):
    x = x.to_list()
    sz = len(x)
    if sz < 3:
        return float("nan")
    l3_demand_miss, l3_demand_access, l2_refill = x
    return (l3_demand_miss / l3_demand_access) * l2_refill


counter_mapping = {
    "Graviton": [
        ArmCounterConfig(
            "ipc",
            PMUEventCounter("instructions", "event=0x8"), 
            PMUEventCounter("cycles", "event=0x11"),
            1),
        ArmCounterPKI("branch-mpki", "branch_miss_predicts", "event=0x10"),
        ArmCounterPKI("code_sparsity", "code_sparsity", "event=0x11c"),
        ArmCounterPKI("data-l1-mpki", "data_l1_refills", "event=0x3"),
        ArmCounterPKI("inst-l1-mpki", "inst_l1_refills", "event=0x1"),
        ArmCounterPKI("l2-ifetch-mpki", "l2_refills_ifetch", "event=0x108"),
        ArmCounterPKI("l2-mpki", "l2_refills", "event=0x17"),
        ArmCounterPKC("stall_frontend_pkc", "stall_frontend_cycles", "event=0x23"),
        ArmCounterPKC("stall_backend_pkc", "stall_backend_cycles", "event=0x24"),
        ArmCounterPKI("inst-tlb-mpki", "inst_tlb_refill", "event=0x2"),
        ArmCounterPKI("inst-tlb-tw-pki", "inst_tlb_walk", "event=0x35"),
        ArmCounterPKI("data-tlb-mpki", "data_tlb_refill", "event=0x5"),
        ArmCounterPKI("data-tlb-tw-pki", "data_tlb_walk", "event=0x34"),
        ArmCounterPKC("inst-neon-pkc", "ASE_SPEC", "event=0x74"),
        ArmCounterPKC("inst-scalar-fp-pkc", "VFP_SPEC", "event=0x75"),

    ],
    "Graviton2": [
        ArmCounterPKI("l3-mpki", "llc_cache_miss_rd", "event=0x37"),
    ],
    "Graviton3": [
        ArmCounterPKI("l3-mpki", "llc_cache_miss_rd", "event=0x37"),
        ArmCounterPKC("stall_backend_mem_pkc", "stall_backend_mem_cycles", "event=0x4005"),
        ArmCounterPKC("inst-sve-pkc", "SVE_INST_SPEC", "event=0x8006"),
        ArmCounterPKC("inst-sve-empty-pkc", "SVE_PRED_EMPTY_SPEC", "event=0x8075"),
        ArmCounterPKC("inst-sve-full-pkc", "SVE_PRED_FULL_SPEC", "event=0x8076"),
        ArmCounterPKC("inst-sve-partial-pkc", "SVE_PRED_PARTIAL_SPEC", "event=0x8077"),
        # SCALE OPS: number of SVE ops, counting size of vector
        # See The A-profile achitecture reference manual (DDI 0487J.a) in Sec D12.11.1 tells us these are in ALU operations per 128-bits,
        ArmCounterPKC("flop-sve-pkc", "FP_SCALE_OPS_SPEC", "event=0x80C0", scale=256/128),
        # FP FIXED OPS: number of NEON and Scalar ops, counting NEON vector width (128-bit)
        ArmCounterPKC("flop-nonsve-pkc", "FP_FIXED_OPS_SPEC", "event=0x80C1"),
    ],
    "Graviton4": [
        ArmCounterPKI("l3-mpki", "llc_cache_miss_rd", "event=0x37"),
        ArmCounterPKC("stall_backend_mem_pkc", "stall_backend_mem_cycles", "event=0x4005"),
        ArmCounterPKC("inst-sve-pkc", "SVE_INST_SPEC", "event=0x8006"),
        ArmCounterPKC("inst-sve-empty-pkc", "SVE_PRED_EMPTY_SPEC", "event=0x8075"),
        ArmCounterPKC("inst-sve-full-pkc", "SVE_PRED_FULL_SPEC", "event=0x8076"),
        ArmCounterPKC("inst-sve-partial-pkc", "SVE_PRED_PARTIAL_SPEC", "event=0x8077"),
        # SCALE OPS: number of SVE ops, counting size of vector
        # See The A-profile achitecture reference manual (DDI 0487J.a) in Sec D12.11.1 tells us these are in ALU operations per 128-bits,
        ArmCounterPKC("flop-sve-pkc", "FP_SCALE_OPS_SPEC", "event=0x80C0", scale=256/128),
        # FP FIXED OPS: number of NEON and Scalar ops, counting NEON vector width (128-bit)
        ArmCounterPKC("flop-nonsve-pkc", "FP_FIXED_OPS_SPEC", "event=0x80C1"),
    ],
    "Graviton5": [
        ArmCounterConfig(
            "l3-mpki", 
            PMUCompositeEventCounter(
                "llc_cache_miss_rd", 
                ["event=0x37", "event=0x36", "event=0x17"],
                per_cpu=True,
                agg_func=_agg_gv5_l3_misses
            ),
            PMUEventCounter("instructions", "event=0x8"),
            1000,
        ),
    ],
    "CMN": [
        # DDR-BW-MBps over-counts when close to saturation, need to remove the retry percentage from the BW reading. 
        ArmCMNCounterConfig("DDR-BW-MBps", PMUEventCounter("hnf_mc_reqs", "type=0x5,eventid=0xd", per_cpu=False), None, (64.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DDR-retry-rate", PMUEventCounter("hnf_mc_retries", "type=0x5,eventid=0xc", per_cpu=False), PMUEventCounter("hnf_mc_reqs", "type=0x5,eventid=0xd", per_cpu=False), 100),
        ArmCMNCounterConfig("LLC-miss-rate", PMUEventCounter("hnf_cache_miss", "type=0x5,eventid=0x1", per_cpu=False), PMUEventCounter("hnf_slc_sf_cache_access", "type=0x5,eventid=0x2", per_cpu=False), 100),
        ArmCMNCounterConfig("SF-back-inval-pka", PMUEventCounter("hnf_snf_eviction", "type=0x5,eventid=0x7", per_cpu=False), PMUEventCounter("hnf_slc_sf_cache_access", "type=0x5,eventid=0x2", per_cpu=False), 1000),
        ArmCMNCounterConfig("SF-snoops-pka", PMUEventCounter("hnf_sf_snps", "type=0x5,eventid=0x18", per_cpu=False), PMUEventCounter("hnf_slc_sf_cache_access", "type=0x5,eventid=0x2", per_cpu=False), 1000),
        ArmCMNCounterConfig("PCIe-Read-MBps", PMUEventCounter("rni_rx_flits", "type=0xa,eventid=0x4", per_cpu=False), None, (32.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("PCIe-Write-MBps", PMUEventCounter("rni_tx_flits", "type=0xa,eventid=0x5", per_cpu=False), None, (32.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
    ],
    "CMN600": [
        ArmCMNCounterConfig("DVM-BW-Ops/s", PMUEventCounter("dn_dvmops", "type=0x1,eventid=0x1", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DVMSync-BW-Ops/s", PMUEventCounter("dn_dvmsyncops", "type=0x1,eventid=0x2", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
    ],
    "CMN650": [
        ArmCMNCounterConfig("DVM-TLBI-BW-Ops/s", PMUEventCounter("dn_dvmops", "type=0x1,eventid=0x1", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DVM-BPI-BW-Ops/s", PMUEventCounter("dn_bpi_dvmops", "type=0x1,eventid=0x2", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DVM-PICI-BW-Ops/s", PMUEventCounter("dn_pici_dvmops", "type=0x1,eventid=0x3", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DVM-VICI-BW-Ops/s", PMUEventCounter("dn_vici_dvmops", "type=0x1,eventid=0x4", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMNCounterConfig("DVMSync-BW-Ops/s", PMUEventCounter("dn_dvmsyncops", "type=0x1,eventid=0x5", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
    ],
    "CMN700": [
        # DDR-BW-MBps on Gv4 in its current form over-counts when at saturation and if using 48xl with cross-socket communication.  Need to remove retry fraction and Remote BW reading.
        ArmCMN700CounterConfig("DDR-BW-MBps", ArmCMN700EventCounter("hnf_mc_reqs", "type=0x200,eventid=0xd", per_cpu=False), None, (64.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("Remote-DDR-BW-MBps", ArmCMN700EventCounter("hnf_mc_remote_reqs", "type=0x103,eventid=0x56", per_cpu=False), None, (32.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DDR-retry-rate", ArmCMN700EventCounter("hnf_mc_retries", "type=0x200,eventid=0xc", per_cpu=False), ArmCMN700EventCounter("hnf_mc_reqs", "type=0x200,eventid=0xd", per_cpu=False), 100),
        ArmCMN700CounterConfig("LLC-miss-rate", ArmCMN700EventCounter("hnf_cache_miss", "type=0x200,eventid=0x1", per_cpu=False), ArmCMN700EventCounter("hnf_slc_sf_cache_access", "type=0x200,eventid=0x2", per_cpu=False), 100),
        ArmCMN700CounterConfig("SF-back-inval-pka", ArmCMN700EventCounter("hnf_snf_eviction", "type=0x200,eventid=0x7", per_cpu=False), ArmCMN700EventCounter("hnf_slc_sf_cache_access", "type=0x200,eventid=0x2", per_cpu=False), 1000),
        ArmCMN700CounterConfig("SF-snoops-pka", ArmCMN700EventCounter("hnf_sf_snps", "type=0x200,eventid=0x18", per_cpu=False), ArmCMN700EventCounter("hnf_slc_sf_cache_access", "type=0x200,eventid=0x2", per_cpu=False), 1000),
        ArmCMN700CounterConfig("PCIe-Read-MBps", ArmCMN700EventCounter("rni_rx_flits", "type=0xa,eventid=0x4", per_cpu=False), None, (32.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("PCIe-Write-MBps", ArmCMN700EventCounter("rni_tx_flits", "type=0xa,eventid=0x5", per_cpu=False), None, (32.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DVM-TLBI-BW-Ops/s", ArmCMN700EventCounter("dn_dvmops", "type=0x1,eventid=0x1", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DVM-BPI-BW-Ops/s", ArmCMN700EventCounter("dn_bpi_dvmops", "type=0x1,eventid=0x2", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DVM-PICI-BW-Ops/s", ArmCMN700EventCounter("dn_pici_dvmops", "type=0x1,eventid=0x3", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DVM-VICI-BW-Ops/s", ArmCMN700EventCounter("dn_vici_dvmops", "type=0x1,eventid=0x4", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
        ArmCMN700CounterConfig("DVMSync-BW-Ops/s", ArmCMN700EventCounter("dn_dvmsyncops", "type=0x1,eventid=0x5", per_cpu=False), None, (1.0 / SAMPLE_INTERVAL)),
    ],
    "Intel_SKX_CXL_ICX": [
        x86CounterConfig("ipc", PMUEventCounter("insts", "event=0xc0,umask=0x0"), PMUEventCounter("cycles", "event=0x3c,umask=0x0"), 1),
        x86CounterPKI("branch-mpki", "br_mispred", "event=0xC5,umask=0x0"),
        x86CounterPKI("data-l1-mpki", "l1_data_fill", "event=0x51,umask=0x1"),
        x86CounterPKI("inst-l1-mpki", "l2_inst_ifetch", "event=0x24,umask=0xe4"),
        x86CounterPKI("l3-mpki", "longest_lat_cache_miss", "event=0x2e,umask=0x41"),
        x86CounterConfig("core-rdBw-MBs", PMUEventCounter("longest_lat_cache_miss", "event=0x2e,umask=0x41"), None, (64.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL)),  
        IntelCounterPKC("flop-scalar-sp-pkc", "FP_ARITH_INST_RETIRED.SCALAR_SINGLE", "event=0xc7,umask=0x2"),
        IntelCounterPKC("flop-scalar-dp-pkc", "FP_ARITH_INST_RETIRED.SCALAR_DOUBLE", "event=0xc7,umask=0x1"),
        # we'll scale these so they count total flops, rather than packed flops:
        IntelCounterPKC("flop-128b-sp-pkc", "FP_ARITH_INST_RETIRED.128B_PACKED_SINGLE", "event=0xc7,umask=0x8", scale=128/32),
        IntelCounterPKC("flop-256b-sp-pkc", "FP_ARITH_INST_RETIRED.256B_PACKED_SINGLE", "event=0xc7,umask=0x20", scale=256/32),
        IntelCounterPKC("flop-512b-sp-pkc", "FP_ARITH_INST_RETIRED.512B_PACKED_SINGLE", "event=0xc7,umask=0x80", scale=512/32),
        IntelCounterPKC("flop-128b-dp-pkc", "FP_ARITH_INST_RETIRED.128B_PACKED_DOUBLE", "event=0xc7,umask=0x4", scale=128/64),
        IntelCounterPKC("flop-256b-dp-pkc", "FP_ARITH_INST_RETIRED.256B_PACKED_DOUBLE", "event=0xc7,umask=0x10", scale=256/64),
        IntelCounterPKC("flop-512b-dp-pkc", "FP_ARITH_INST_RETIRED.512B_PACKED_DOUBLE", "event=0xc7,umask=0x40", scale=512/64),
    ],
    "Intel_SKX_CXL" : [
        x86CounterPKI("l2-mpki", "l2_fills", "event=0xf1,umask=0x1f"), 
        IntelCounterPKC("stall_frontend_pkc", "idq_uops_not_delivered_cycles", "event=0x9c,umask=0x1,cmask=0x4"),
        IntelCounterPKC("stall_backend_pkc", "resource_stalls_any", "event=0xa2,umask=0x1"),
        x86CounterPKI("inst-tlb-mpki", "inst_tlb_miss", "event=0x85,umask=0x20"),
        x86CounterPKI("inst-tlb-tw-pki", "inst_tlb_miss_tw", "event=0x85,umask=0x1"),
        x86CounterPKI("data-rd-tlb-mpki", "data_tlb_miss_rd", "event=0x08,umask=0x20"),
        x86CounterPKI("data-st-tlb-mpki", "data_tlb_miss_st", "event=0x49,umask=0x20"),
        x86CounterPKI("data-rd-tlb-tw-pki", "data_tlb_miss_rd_tw", "event=0x08,umask=0x01"),
        x86CounterPKI("data-st-tlb-tw-pki", "data_tlb_miss_st_tw", "event=0x49,umask=0x01"),
    ],
    "Intel_ICX": [
        x86CounterPKI("l2-mpki", "l2_fills", "event=0xf1,umask=0x1f"),
        x86CounterConfig("stall_frontend_pkc", PMUEventCounter("idq_uops_not_delivered_cycles", "event=0x9c,umask=0x1,cmask=0x5"), PMUEventCounter("cycles", "event=0x3c,umask=0x0"), 1000),
        # This is actually the fraction of execution slots that are backend stalled according to the TMA method, but it can be interpreted the same as stall_backend_pkc.
        x86CounterConfig("stall_backend_pkc", PMUEventCounter("slots_be_stall", "event=0xa4,umask=0x2"), PMUEventCounter("slots", "event=0xa4,umask=0x01"), 1000),
        x86CounterPKI("inst-tlb-mpki", "inst_tlb_miss", "event=0x85,umask=0x20"),
        x86CounterPKI("inst-tlb-tw-pki", "inst_tlb_miss_tw", "event=0x85,umask=0x0e"),
        x86CounterPKI("data-rd-tlb-mpki", "data_tlb_miss_rd", "event=0x08,umask=0x20"),
        x86CounterPKI("data-st-tlb-mpki", "data_tlb_miss_st", "event=0x49,umask=0x20"),
        x86CounterPKI("data-rd-tlb-tw-pki", "data_tlb_miss_rd_tw", "event=0x08,umask=0x0e"),
        x86CounterPKI("data-st-tlb-tw-pki", "data_tlb_miss_st_tw", "event=0x49,umask=0x0e"),
    ],
    "Intel_SPR": [
        x86CounterPKI("l2-mpki", "l2_fills", "event=0x25,umask=0x1f"),
        x86CounterPKI("inst-tlb-mpki", "inst_tlb_miss", "event=0x11,umask=0x20"),
        x86CounterPKI("inst-tlb-tw-pki", "inst_tlb_miss_tw", "event=0x11,umask=0x0e"),
        x86CounterPKI("data-rd-tlb-mpki", "data_tlb_miss_rd", "event=0x12,umask=0x20"),
        x86CounterPKI("data-st-tlb-mpki", "data_tlb_miss_st", "event=0x13,umask=0x20"),
        x86CounterPKI("data-rd-tlb-tw-pki", "data_tlb_miss_rd_tw", "event=0x12,umask=0x0e"),
        x86CounterPKI("data-st-tlb-tw-pki", "data_tlb_miss_st_tw", "event=0x13,umask=0x0e"),
        IntelCounterPKC("stall_frontend_pkc", "idq_uops_not_delivered_cycles", "event=0x9c,umask=0x1,cmask=0x6"),
        # This is actually the fraction of execution slots that are backend stalled according to the TMA method,
        # but it can be interpreted the same as stall_backend_pkc as slots count per cycle.
        x86CounterConfig(
            "stall_backend_pkc",
            PMUEventCounter("slots_be_stall", "event=0xa4,umask=0x2"),
            PMUEventCounter("slots", "event=0xa4,umask=0x01"),
            1000,
        ),
    ],
    "Milan_Genoa": [
        x86CounterConfig(
            "ipc",
            PMUEventCounter("insts", "event=0xc0,umask=0x0"),
            PMUEventCounter("cycles", "event=0x76,umask=0x0"),
            1,
        ),
        x86CounterPKI("branch-mpki", "br_mispred", "event=0xc3,umask=0x0"),
        x86CounterPKI("data-l1-mpki", "l1_data_fill", "event=0x44,umask=0xff"),
        x86CounterPKI("inst-l1-mpki", "l2_inst_request", "event=0x60,umask=0x10"),
        x86CounterPKI("l2-ifetch-mpki", "l2_inst_miss", "event=0x64,umask=0x1"),
        x86CounterPKI("l2-mpki", "l2_demand_miss", "event=0x64,umask=0x9"),
        x86CounterPKI(
            # This is sorta l3 mpki, but ellides Prefetch misses from L2
            "l3-mpki", "l1_any_fills_dram", "event=0x44,umask=0x8"),
        x86CounterConfig(
            # This sort estimates core BW demand (plus prefetches), but need
            # to also get L2 Prefetch BW, but need a new event def to do this
            "core-rdBw-MBs",
            PMUEventCounter("l1_any_fills_dram", "event=0x44,umask=0x8"),
            None,
            (64.0 / 1024.0 / 1024.0 / SAMPLE_INTERVAL),
        ),
        AMDCounterPKC("stall_frontend_pkc", "de_opq_empty", "event=0xa9,umask=0x0"),
        x86CounterPKI(
            # Technically misses in L1-iTLB that hit L2 STLB,
            # need another counter to get the true number. But this is good enough for now
            "inst-tlb-mpki", "inst_tlb_miss", "event=0x84,umask=0x0"),
        x86CounterPKI("inst-tlb-tw-pki", "inst_tlb_miss", "event=0x85,umask=0x0f"),
        x86CounterPKI("data-tlb-mpki", "data_tlb_miss", "event=0x45,umask=0xff"),
        x86CounterPKI("data-tlb-tw-pki", "inst_tlb_miss", "event=0x45,umask=0xf0"),
    ],
    "Milan": [
        AMDCounterPKC("stall_backend_pkc1", "dispatch_stall_token_1", "event=0xae,umask=0xf7"),
        AMDCounterPKC("stall_backend_pkc2", "dispatch_stall_token_2", "event=0xaf,umask=0x27"),
    ],
    "Genoa": [
        x86CounterConfig(
            "stall_backend_pkc",
            PMUEventCounter("dispatch_stall_backend_slots", "event=0x1a0,umask=0x1e"),
            PMUEventCounter("cycles", "event=0x76,umask=0x0"),
            1000 * (1.0 / 6.0),
        ),
    ]
}


def create_graviton_counter_mapping(cpu_type):
    """
    Depending on the PMUs available on the current node,
    return the proper PMU counter set.
    """
    have_cmn = os.path.isdir("/sys/devices/arm_cmn_0")
    have_pmu = os.path.isdir("/sys/devices/armv8_pmuv3_0")

    mesh_mapping = {
        "Graviton2": "CMN600",
        "Graviton3": "CMN650",
        "Graviton4": "CMN700",
        "Graviton5": "CMN650"
    }

    pmu_groups = []
    if have_pmu:
        pmu_groups.append(PlatformDetails(counter_mapping["Graviton"], 6))
        if cpu_type in counter_mapping:
            pmu_groups.append(PlatformDetails(counter_mapping[cpu_type], 6))
    if have_cmn:
        if cpu_type != "Graviton4":
            pmu_groups.append(PlatformDetails(counter_mapping["CMN"], 2))
        if cpu_type in mesh_mapping:
            pmu_groups.append(PlatformDetails(counter_mapping[mesh_mapping[cpu_type]], 2))

    return pmu_groups


# CPU and PMU mappings and # counter mappings, need to make this extensible to more CPUs
filter_proc = {
    "Graviton2": create_graviton_counter_mapping("Graviton2"),
    "Graviton3": create_graviton_counter_mapping("Graviton3"),
    # Neoverse-V2 cores have a superset of events that overlap with Gv3
    "Graviton4": create_graviton_counter_mapping("Graviton4"),
    "Graviton5": create_graviton_counter_mapping("Graviton5"),
    "Intel(R) Xeon(R) Platinum 8124M CPU @ 3.00GHz": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 4),
        PlatformDetails(counter_mapping["Intel_SKX_CXL"], 4)],
    "Intel(R) Xeon(R) Platinum 8175M CPU @ 2.50GHz": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 4),
        PlatformDetails(counter_mapping["Intel_SKX_CXL"], 4)],
    "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 4),
        PlatformDetails(counter_mapping["Intel_SKX_CXL"], 4)],
    "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 4),
        PlatformDetails(counter_mapping["Intel_SKX_CXL"], 4)],
    "Intel(R) Xeon(R) Platinum 8375C CPU @ 2.90GHz": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 6),
        PlatformDetails(counter_mapping["Intel_ICX"], 6)],
    "Intel(R) Xeon(R) Platinum 8488C": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 6),
        PlatformDetails(counter_mapping["Intel_SPR"], 6)],
    "Intel(R) Xeon(R) 6975P-C": [
        PlatformDetails(counter_mapping["Intel_SKX_CXL_ICX"], 6),
        PlatformDetails(counter_mapping["Intel_SPR"], 6)],
    "Milan": [
        PlatformDetails(counter_mapping["Milan_Genoa"], 6),
        PlatformDetails(counter_mapping["Milan"], 6)],
    "Genoa": [
        PlatformDetails(counter_mapping["Milan_Genoa"], 5),
        PlatformDetails(counter_mapping["Genoa"], 5)],
    "Turin": [
        PlatformDetails(counter_mapping["Milan_Genoa"], 5),
        PlatformDetails(counter_mapping["Genoa"], 5)], 
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-root", action="store_true", help="Allow running without root privileges")
    parser.add_argument("--cpu-list", action="store", type=str)
    parser.add_argument("--timeout", action="store", type=int, default=300)
    args = parser.parse_args()

    if not args.no_root:
        res = subprocess.run(["id", "-u"], check=True, stdout=subprocess.PIPE)
        if int(res.stdout) > 0:
            print("Must be run with root privileges (or with --no-root)")
            exit(1)

    # Remove temporary files
    try:
        os.remove(RESULTS_CSV)
    except:
        pass
    try:
        os.remove(RESULTS_JSON)
    except:
        pass

    cpus = None
    if args.cpu_list and args.cpu_list != "all":
        cpus = args.cpu_list.split(",")

    processor_version = get_cpu_type()

    try:
        counters = filter_proc[processor_version]
    except KeyError:
        print(f"Error: {processor_version} not supported")
        exit(1)

    # For Graviton single-slot, max counters - 1 is what avoids odd aliasing with the Brimstone cycle counter.
    counter_groups = build_groups(counters)

    perfstat(counter_groups, timeout=args.timeout, cpus=cpus)
    counter_table = calculate_counter_stat(counters)

    pretty_print_table(counter_table)
