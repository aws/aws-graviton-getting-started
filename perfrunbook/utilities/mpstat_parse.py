#! /usr/bin/env python3

import numpy as np
import pandas as pd


# Pass in a dict s:
# { date: string in YYYY-MM-DD
#   time: string in hh:mm:ss
# }
# Pass in a last_date as an np.datetime64 obj or None
# Returns a np.datetime64 object
def parse_time(time, last_date):
    # Get ourselves a date in ISO format from last_date
    date = f"{last_date.tolist().year}-{last_date.tolist().month:02d}-{last_date.tolist().day:02d}"
    d = np.datetime64(f"{date} {time}")
    if last_date:
        while (d - last_date) < np.timedelta64(0, 's'):
            d = d + np.timedelta64(1, 'D')

    return d


def parse_mpstat_json_all_irqs(data):
    """
    Parses IRQs for entire system
    """
    irq_data = data["sysstat"]["hosts"][0]["statistics"]
    date = data["sysstat"]["hosts"][0]["date"]

    data = {"time": [],
            "irq_s": []}

    last_date = None
    for stats in irq_data:
        timestamp = stats["timestamp"]
        all_irqs = float(stats["sum-interrupts"][0]["intr"])

        if last_date:
            date = parse_time(timestamp, last_date)
        else:
            date = np.datetime64(f"{date} {timestamp}")
        last_date = date

        data["time"].append(date)
        data["irq_s"].append(all_irqs)

    df = pd.DataFrame(data)
    df = df.set_index('time')
    return df


def parse_mpstat_json_single_irq(data, irq):
    """
    Does the generic parsing and combining
    """
    irq_data = data["sysstat"]["hosts"][0]["statistics"]
    date = data["sysstat"]["hosts"][0]["date"]

    data = {"time": []}
    data[irq] = []

    last_date = None
    for stats in irq_data:
        timestamp = stats["timestamp"]

        single_irq = 0
        for cpus in stats["individual-interrupts"]:
            for irqs in cpus["intr"]:
                if irqs["name"] == irq:
                    single_irq += int(irqs["value"])
        if last_date:
            date = parse_time(timestamp, last_date)
        else:
            date = np.datetime64(f"{date} {timestamp}")
        last_date = date
        data["time"].append(date)
        data[irq].append(single_irq)
    df = pd.DataFrame(data)
    df = df.set_index('time')
    return df
