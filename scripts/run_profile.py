#!/usr/bin/env python3
"""Where the lookup time goes: ftrace function profiler on ext4_lookup and ext4_search_dir.

ext4_search_dir() walks the entries of one directory block and calls ext4_match() on
each (inlined in 5.4.214, a separate ext4_match.part.0 in 6.18.64), so its time holds
the name comparisons. memcmp itself is notrace and cannot be profiled. For each
workload the profiler counts calls and total time (children included) of the two functions.
The profiler adds a fixed cost per traced call, so compare kernels, not absolute values.
These runs are separate from the timing runs.
Example: sudo python3 scripts/run_profile.py --expected-kernel 5.4.214-b0 --bench bench/lookup_bench
  --synthetic fixtures/leaf-mount/leaf --names results/round2/names --real fixtures/real-mount/real
  --output results/round3/sessions/s1-b0/profile --cpu 0
"""
import argparse
import csv
import os
from pathlib import Path
import platform
import subprocess

FUNCS = ("ext4_lookup", "ext4_search_dir")


def tracing_dir():
    for d in ("/sys/kernel/tracing", "/sys/kernel/debug/tracing"):
        if os.path.exists(d + "/function_profile_enabled"):
            return Path(d)
    raise SystemExit("function profiler not available")


def read_stats(t):
    stats = {}
    for f in sorted(t.glob("trace_stat/function*")):
        for line in f.read_text().splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 4 and parts[0] in FUNCS:
                hit = int(parts[1])
                total = float(parts[2])
                unit = parts[3]
                total_us = total / 1000 if unit == "ns" else total * 1000 if unit == "ms" else total
                s = stats.setdefault(parts[0], [0, 0.0])
                s[0] += hit
                s[1] += total_us
    return stats


def profiled(t, cmd, cpu, drop=True):
    (t / "set_ftrace_filter").write_text("\n".join(FUNCS) + "\n")
    (t / "function_profile_enabled").write_text("0\n")
    if drop:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text("2\n")
    (t / "function_profile_enabled").write_text("1\n")
    subprocess.run((["taskset", "-c", str(cpu)] if cpu is not None else []) + cmd, check=True,
                   stdout=subprocess.DEVNULL, env=dict(os.environ, LC_ALL="C", GIT_OPTIONAL_LOCKS="0"))
    (t / "function_profile_enabled").write_text("0\n")
    stats = read_stats(t)
    (t / "set_ftrace_filter").write_text("\n")
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected-kernel", required=True)
    ap.add_argument("--bench", type=Path, required=True)
    ap.add_argument("--synthetic", type=Path, required=True)
    ap.add_argument("--names", type=Path, required=True)
    ap.add_argument("--real", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cpu", type=int)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    if platform.release() != args.expected_kernel:
        ap.error("unexpected kernel: " + platform.release())
    if args.output.exists():
        ap.error("output directory must be absent")
    args.output.mkdir(parents=True)
    t = tracing_dir()
    linux = args.real / "linux"
    work = {}
    for case in ("short13", "long128", "random128", "varied", "sametail"):
        work["lookup_" + case] = [str(args.bench), "--dir", str(args.synthetic / case), "--names",
                                  str(args.names / (case + ".names")), "--seed", "1", "--trial", "0",
                                  "--label", "profile", "--warm-dir"]
    work["ls_photos"] = ["ls", "-l", str(args.real / "photos")]
    work["find_linux"] = ["find", str(linux), "-path", str(linux / ".git"), "-prune", "-o", "-ls"]
    work["git_linux"] = ["git", "-C", str(linux), "--no-optional-locks", "status", "--porcelain"]
    rows = []
    for rep in range(args.repeats):
        for name, cmd in work.items():
            stats = profiled(t, cmd, args.cpu)
            for func in FUNCS:
                hit, total = stats.get(func, (0, 0.0))
                rows.append({"kernel": platform.release(), "repeat": rep, "workload": name, "function": func,
                             "hits": hit, "total_us": round(total, 3),
                             "avg_us": round(total / hit, 4) if hit else ""})
    with (args.output / "profile.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("%s: %d rows" % (args.output / "profile.csv", len(rows)))


if __name__ == "__main__":
    main()
