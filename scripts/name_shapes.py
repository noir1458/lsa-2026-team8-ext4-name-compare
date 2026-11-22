#!/usr/bin/env python3
"""Count which name pairs in real directories the tail patch helps, hurts, or ignores.

ext4 compares the name being looked up with entries in the same directory block.
Entries in one HTree leaf block are spread by hash, so a random pair of names from
the same directory stands in for a lookup name and a block entry. For every
ordered pair (a, b) of different names in one directory:

  length_differs  lengths differ: the original code already rejects by length
  short           same length but under 8 bytes: the patch does not run
  tail_differs    same length, last 8 bytes differ: the patch rejects in one compare
  tail_same       same length, last 8 bytes equal: the patch adds one compare (the loss case)

For same-length pairs it also reports the mean common-prefix length, the bytes the
original byte-by-byte memcmp reads before it finds a difference (sampled: at most
200 names per length group).

Reads directory listings only (no file contents). Directory paths under $HOME are
written with ~. Example: name_shapes.py --min-entries 100 --output out.csv /usr /etc
"""
import argparse
import collections
import csv
import os
import statistics


def common_prefix(a, b):
    i = 0
    for x, y in zip(a, b):
        if x != y:
            break
        i += 1
    return i


def prefix_means(by_len, cap=200):
    sums = {"tail_differs": [0, 0], "tail_same": [0, 0]}
    for length, group in by_len.items():
        if length < 8 or len(group) < 2:
            continue
        group = sorted(group)
        if len(group) > cap:
            step = len(group) / cap
            group = [group[int(i * step)] for i in range(cap)]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                key = "tail_same" if a[-8:] == b[-8:] else "tail_differs"
                sums[key][0] += common_prefix(a, b)
                sums[key][1] += 1
    return {("prefix_" + k): (v[0] / v[1] if v[1] else "") for k, v in sums.items()}


def classify(names):
    n = len(names)
    by_len = collections.defaultdict(list)
    for name in names:
        by_len[len(name)].append(name)
    same_len = sum(len(g) * (len(g) - 1) for g in by_len.values())
    short = sum(len(g) * (len(g) - 1) for length, g in by_len.items() if length < 8)
    tail_same = 0
    for length, group in by_len.items():
        if length < 8:
            continue
        tails = collections.Counter(name[-8:] for name in group)
        tail_same += sum(m * (m - 1) for m in tails.values())
    long_same = same_len - short
    row = {"entries": n, "pairs": n * (n - 1), "length_differs": n * (n - 1) - same_len,
           "short": short, "tail_differs": long_same - tail_same, "tail_same": tail_same}
    row.update(prefix_means(by_len))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--min-entries", type=int, default=100)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    home = os.path.expanduser("~")
    rows = []
    skip = ("/proc", "/sys", "/dev", "/run", "/snap")
    for root in args.roots:
        for path, dirs, files in os.walk(root, onerror=lambda e: None, followlinks=False):
            if path.startswith(skip):
                dirs[:] = []
                continue
            names = [os.fsencode(x) for x in dirs + files]
            if len(names) < args.min_entries:
                continue
            row = classify(names)
            shown = "~" + path[len(home):] if path == home or path.startswith(home + "/") else path
            row["directory"] = shown
            rows.append(row)
    fields = ["directory", "entries", "pairs", "length_differs", "short", "tail_differs", "tail_same",
              "prefix_tail_differs", "prefix_tail_same"]
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    total = {k: sum(r[k] for r in rows) for k in fields[1:7]}
    print("directories with >= %d entries: %d" % (args.min_entries, len(rows)))
    for key in ("length_differs", "short", "tail_differs", "tail_same"):
        share = [r[key] / r["pairs"] for r in rows]
        print("%-15s pooled %6.2f%%   median of directories %6.2f%%" % (
            key, 100 * total[key] / total["pairs"], 100 * statistics.median(share)))
    same_long = [r for r in rows if r["tail_differs"] + r["tail_same"]]
    loss_vs_gain = [r["tail_same"] / (r["tail_differs"] + r["tail_same"]) for r in same_long]
    print("among same-length pairs of 8+ bytes, tail_same share: pooled %.2f%%, median %.2f%%" % (
        100 * total["tail_same"] / (total["tail_same"] + total["tail_differs"]), 100 * statistics.median(loss_vs_gain)))
    for key in ("prefix_tail_differs", "prefix_tail_same"):
        vals = [r[key] for r in rows if r[key] != ""]
        print("%s: median of directories %.1f bytes (%d directories)" % (key, statistics.median(vals), len(vals)))


if __name__ == "__main__":
    main()
