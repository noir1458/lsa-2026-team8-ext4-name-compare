#!/usr/bin/env python3
"""Split each trial's per-query times into names that exist and names that do not.

Reads trial_*.latencies.csv.gz written by run_lookup.py (one row per query) and
writes one row per trial: median and mean time for existing (expected_exists=1)
and missing (0) names, in nanoseconds.
Example: split_presence.py raw/latencies/s1-b0/lookup results/sessions/s1-b0/lookup/presence.csv
"""
import csv
import gzip
from pathlib import Path
import re
import statistics
import sys

PATTERN = re.compile(r"trial_(\d+)_([a-z0-9]+)_(warmdir|warm)_(run[12])\.latencies\.csv\.gz$")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for path in sorted(source.glob("trial_*.latencies.csv.gz")):
        match = PATTERN.search(path.name)
        if not match:
            raise SystemExit("unexpected file name: " + path.name)
        times = {"1": [], "0": []}
        with gzip.open(path, "rt") as f:
            for row in csv.DictReader(f):
                times[row["expected_exists"]].append(int(row["latency_ns"]))
        if not times["1"] or not times["0"]:
            raise SystemExit("missing existing or missing names in " + path.name)
        rows.append({"trial": int(match.group(1)), "case": match.group(2), "cache": match.group(3),
                     "label": match.group(4),
                     "exists_queries": len(times["1"]), "missing_queries": len(times["0"]),
                     "exists_median_ns": statistics.median(times["1"]),
                     "missing_median_ns": statistics.median(times["0"]),
                     "exists_mean_ns": round(statistics.fmean(times["1"]), 1),
                     "missing_mean_ns": round(statistics.fmean(times["0"]), 1)})
    if not rows:
        raise SystemExit("no latency files in " + str(source))
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("%s: %d trials" % (output, len(rows)))


if __name__ == "__main__":
    main()
