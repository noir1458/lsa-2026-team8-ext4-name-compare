#!/usr/bin/env python3
"""Time `ls -l` on the read-only leaf fixtures (one lstat per name).

cold: drop_caches=2 right before the run, so every lstat goes through
ext4_lookup and the leaf name comparison. Directory blocks stay in the page
cache, so this is the same cache state as the benchmark's warmdir, not a disk
cold read. warm: the same command again right after, with the names already in
the dentry cache, where ext4 is not asked at all.

The output of every run is hashed. With a read-only mount, LC_ALL=C and TZ=UTC
the hash must be identical across runs and across kernels.

Example: sudo python3 scripts/run_ls.py --expected-kernel 5.4.214-tail \
    --fixtures fixtures/leaf-mount/leaf --names results/names \
    --output results/sessions/s1-tail/ls --reps 10 --cpu 0 --seed 1
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import time


def run_ls(directory, cpu):
    command = ["ls", "-l", "--color=never", str(directory)]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu)] + command
    env = dict(os.environ, LC_ALL="C", TZ="UTC")
    start = time.monotonic_ns()
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    elapsed = time.monotonic_ns() - start
    if result.returncode or result.stderr:
        raise RuntimeError("ls failed: %r" % result.stderr[:200])
    return elapsed, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expected-kernel", required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if platform.release() != args.expected_kernel:
        parser.error("unexpected kernel: " + platform.release())
    if args.output.exists():
        parser.error("output directory must be absent")
    manifest = json.loads((args.names / "manifest.json").read_text())
    cases = [(c["case"], c["positive"]) for c in manifest["cases"]]
    args.output.mkdir(parents=True)
    rng = random.Random(args.seed)
    rows, hashes = [], {}
    for rep in range(args.reps):
        order = list(cases)
        rng.shuffle(order)
        for case, files in order:
            directory = args.fixtures / case
            os.sync()
            Path("/proc/sys/vm/drop_caches").write_text("2\n")
            for mode in ("cold", "warm"):
                elapsed, out = run_ls(directory, args.cpu)
                lines = out.count(b"\n") - 1  # first line is "total N"
                digest = hashlib.sha256(out).hexdigest()
                if lines != files:
                    raise RuntimeError("%s: expected %d entries, got %d" % (case, files, lines))
                if hashes.setdefault(case, digest) != digest:
                    raise RuntimeError("%s: ls output changed between runs" % case)
                rows.append({"kernel": platform.release(), "rep": rep, "case": case,
                             "mode": mode, "entries": lines, "elapsed_ns": elapsed,
                             "output_sha256": digest})
                print(json.dumps(rows[-1]), flush=True)
    with (args.output / "ls.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "metadata.json").write_text(json.dumps({
        "kernel": platform.release(), "reps": args.reps, "cpu": args.cpu, "seed": args.seed,
        "command": "ls -l --color=never <dir>, LC_ALL=C TZ=UTC, stdout captured",
        "cold": "drop_caches=2 before the run (dentries and inodes dropped, page cache kept)",
        "warm": "same command immediately after the cold run",
        "output_sha256": hashes}, indent=2) + "\n")


if __name__ == "__main__":
    main()
