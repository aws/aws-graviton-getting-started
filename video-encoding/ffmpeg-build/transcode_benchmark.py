import csv
import glob
import os
import subprocess
import sys
import time
from multiprocessing import Pool

try:
    import tqdm
    have_tqdm = True
except ModuleNotFoundError:
    have_tqdm = False

if have_tqdm and sys.stdout.isatty():
    def progress_bar(iterable, total=None):
        return tqdm.tqdm(iterable, total=total)
else:
    def progress_bar(iterable, total=None):
        return iterable

def transcode(args):
    filename, codec = args
    cmd = ['ffmpeg', '-i', filename, '-c:v', codec, '-f', 'null', '-']
    start = time.time()
    subprocess.run(cmd, capture_output=True)
    elapsed = time.time() - start
    return filename, codec, elapsed

if __name__ == '__main__':
    files = sorted(glob.glob('*.mp4'), key=os.path.getsize, reverse=True)
    jobs = [(f, c) for f in files for c in ('libx264', 'libx265')]
    workers = os.cpu_count() // 8
    
    print(f"Running {len(jobs)} tasks with {workers} workers")
    results = []
    start_time = time.time()
    with Pool(workers) as pool:
        for result in progress_bar(pool.imap_unordered(transcode, jobs), total=len(jobs)):
            filename, codec, elapsed = result
            print(f"{filename} -> {codec}: {elapsed:.2f}s")
            results.append(result)
    total_time = time.time() - start_time
    
    with open('benchmark_results.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'codec', 'runtime'])
        for filename, codec, elapsed in results:
            writer.writerow([filename, codec, f"{elapsed:.2f}"])
        writer.writerow(['TOTAL', '', f"{total_time:.2f}"])
