#! /usr/bin/env python3

import re
import sys
import numpy as np
import pandas as pd


def parse_start_date(line):
    # Get start date from line in ISO 8601 format
    hdr = re.compile(r'''.*?\)\s+(?P<start>\d+\-\d+\-\d+).*''')
    match_hdr = hdr.match(line)
    start_date = None
    if match_hdr:
        start_date = match_hdr['start']

    return start_date


class ParseInterface(object):

    def __init__(self, start_date):
        self.regex_hdr = None
        self.regex_data = None
        self.regex_footer = re.compile(r'''Average:.*''')
        self.start = start_date
        self.last_date = None
        self.parquet_name = "sar.parquet"
        self.fields = []

    # Pass in a dict s:
    # { date: string in YYYY-MM-DD
    #   time: string in hh:mm:ss
    # }
    # Pass in a last_date as an np.datetime64 obj or None
    # Returns a np.datetime64 object
    def parse_time(self, s, last_date):

        d = np.datetime64("{} {}".format(s['date'], s['time']))

        if last_date:
            while (d - last_date) < np.timedelta64(0, 's'):
                d = d + np.timedelta64(1, 'D')

        return d

    def parse_data(self, f, save_parquet=True):
        line = f.readline()
        data = {}
        for key in self.fields:
            data[key[0]] = []

        while(line):
            match_data = self.regex_data.match(line)
            if match_data:
                s = {'date': self.start,
                     'time': match_data['time']}
                d = self.parse_time(s, self.last_date)
                data['time'].append(d)
                self.last_date = d

                # Every other field is not special
                for key in self.fields[1:]:
                    data[key[0]].append(key[1](match_data[key[0]]))

                line = f.readline()
                continue
            match_footer = self.regex_footer.match(line)
            if match_footer:
                break
            line = f.readline()

        df = pd.DataFrame(data)
        df = df.set_index('time')
        if (save_parquet):
            df.to_parquet(self.parquet_name, compression='gzip')
        return df


    # Look for the header, if we find it, read until we hit the end of the section
    # Return the data frame if we get one.
    def parse_for_header(self, line, f, save_parquet=True):
        match = self.regex_hdr.match(line)
        if match:
            return self.parse_data(f, save_parquet)
        return None


class ParseIfaceUtil(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)

        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+IFACE\s+'''
                                    r'''rxpck/s\s+txpck/s\s+rxkB/s\s+txkB/s\s+rxcmp/s\s+txcmp/s\s+'''
                                    r'''rxmcst/s''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<iface>[\d\w]+)\s+'''
                                     r'''(?P<rxpcks>\d+\.\d+)\s+(?P<txpcks>\d+\.\d+)\s+(?P<rxkBs>\d+\.\d+)\s+'''
                                     r'''(?P<txkBs>\d+\.\d+)\s+(?P<rxcmps>\d+\.\d+)\s+(?P<txcmps>\d+\.\d+)\s+'''
                                     r'''(?P<rxmcsts>\d+\.\d+)''')
        self.fields = [('time', None), ('iface', str), ('rxpcks', float), ('txpcks', float), ('rxkBs', float),
                       ('txkBs', float), ('rxcmps', float), ('txcmps', float), ('rxmcsts', float)]

        self.start = start_date
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_iface_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_iface.parquet"


# class that embodies the state machine for parsing SAR log for device utilization
class ParseDevUtil(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)
        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+DEV\s+tps\s+'''
                                    r'''rd_sec/s\s+wr_sec/s\s+avgrq\-sz\s+avgqu\-sz\s+'''
                                    r'''await\s+svctm\s+%util''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<dev>[\w\d\-]+)\s+(?P<tps>\d+\.\d+)\s+'''
                                     r'''(?P<rdsecs>\d+\.\d+)\s+(?P<wrsecs>\d+\.\d+)\s+(?P<avgrqsz>\d+\.\d+)\s+'''
                                     r'''(?P<avgqusz>\d+\.\d+)\s+(?P<await>\d+\.\d+)\s+(?P<svctm>\d+\.\d+)\s+(?P<util>\d+\.\d+)''')
        self.fields = [('time', None), ('dev', str), ('tps', float), ('rdsecs', float),
                       ('wrsecs', float), ('avgrqsz', float), ('avgqusz', float), ('await', float),
                       ('svctm', float), ('util', float)]
        self.start = start_date
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_dev_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_dev.parquet"


# class that embodies the state machine for parsing SAR log for disk reads/writes
class ParseDiskUtil(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)
        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+tps\s+rtps\s+'''
                                    r'''wtps\s+bread/s\s+bwrtn/s''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<tps>\d+\.\d+)\s+'''
                                     r'''(?P<rtps>\d+\.\d+)\s+(?P<wtps>\d+\.\d+)\s+'''
                                     r'''(?P<breads>\d+\.\d+)\s+(?P<bwrtns>\d+\.\d+)''')

        self.fields = [('time', None), ('tps', float), ('rtps', float),
                       ('wtps', float), ('breads', float), ('bwrtns', float)]
        self.start = start_date
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_disk_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_disk.parquet"


# class that embodies the state machine for parsing SAR logs for cpu utilization
class ParseTcpTime(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)
        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+active/s\s+'''
                                       r'''passive/s\s+iseg/s\s+oseg/s''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<active>\d+\.\d+)\s+'''
                                       r'''(?P<passive>\d+\.\d+)\s+(?P<iseg>\d+\.\d+)\s+'''
                                       r'''(?P<oseg>\d+\.\d+)''')

        self.fields = [('time', None), ('active', str), ('passive', float),
                       ('iseg', float), ('oseg', float)]
        self.start = start_date
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_tcp_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_tcp.parquet"

# class that embodies the state machine for parsing SAR logs for cpu utilization
class ParseCpuTime(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)
        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+CPU\s+'''
                                       r'''%usr\s+%nice\s+%sys\s+%iowait\s+%steal\s+%irq\s+%soft\s+%guest\s+%gnice\s+%idle''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<cpu>[\d\w]+)\s+'''
                                       r'''(?P<usr>\d+\.\d+)\s+(?P<nice>\d+\.\d+)\s+(?P<sys>\d+'''
                                       r'''\.\d+)\s+(?P<iowait>\d+\.\d+)\s+(?P<steal>\d+\.\d+)'''
                                       r'''\s+(?P<irq>\d+\.\d+)\s+(?P<soft>\d+\.\d+)\s+'''
                                       r'''(?P<guest>\d+\.\d+)\s+(?P<gnice>\d+\.\d+)\s+(?P<idle>\d+\.\d+)''')

        self.fields = [('time', None), ('cpu', str), ('usr', float),
                       ('nice', float), ('sys', float), ('iowait', float),
                       ('steal', float), ('irq', float), ('soft', float),
                       ('guest', float), ('gnice', float), ('idle', float)]
        self.start = start_date
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_cpu_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_cpu.parquet"


class ParseCSwitchTime(ParseInterface):

    def __init__(self, start_date, parquet=None):
        super().__init__(start_date)
        self.regex_hdr = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+proc/s\s+cswch/s''')
        self.regex_data = re.compile(r'''(?P<time>\d+:\d+:\d+)\s+(?P<proc_s>\d+\.\d+)\s+(?P<cswch_s>\d+\.\d+)''')
        self.start = start_date

        self.fields = [('time', None), ('proc_s', float), ('cswch_s', float)]
        self.last_date = None
        if parquet:
            self.parquet_name = "sar_cswch_{}.parquet".format(parquet)
        else:
            self.parquet_name = "sar_cswch.parquet"


def parse_sysstat(file_name, suffix=None):
    with open(file_name, 'r') as f:

        # Get start date
        line = f.readline()
        start_date = parse_start_date(line)
        if not start_date:
            print("ERR: header not first line of Sar file, exiting")
            return 1

        # Initialize parsers
        parseCPU = ParseCpuTime(start_date, parquet=suffix)
        parseDisk = ParseDiskUtil(start_date, parquet=suffix)
        parseDev = ParseDevUtil(start_date, parquet=suffix)
        parseIface = ParseIfaceUtil(start_date, parquet=suffix)
        parseTcpTime = ParseTcpTime(start_date, parquet=suffix)
        parseCswitch = ParseCSwitchTime(start_date, parquet=suffix)

        line = f.readline()
        while (line):
            parseCPU.parse_for_header(line, f)
            parseDisk.parse_for_header(line, f)
            parseDev.parse_for_header(line, f)
            parseIface.parse_for_header(line, f)
            parseTcpTime.parse_for_header(line, f)
            parseCswitch.parse_for_header(line, f)
            line = f.readline()
    return 0

if __name__ == "__main__":
    exit(parse_sysstat(sys.argv[1]))
