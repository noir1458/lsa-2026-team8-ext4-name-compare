#!/usr/bin/env python3
"""Time real programs on the read-only "real" image (3차 측정).

Tasks (each run after drop_caches=2 as "cold", then once more as "warm"):
  ls_photos   ls -l on IMG_0001.JPG ... IMG_9999.JPG
  find_linux  find -ls over the linux-5.4.214 source tree (every entry is looked up)
  tar_linux   tar cf /dev/null of the tree (GNU tar does not read file data for /dev/null)
  git_linux   git status --porcelain in the tree (lstat of every tracked file)
Output hashes must stay the same across runs and kernels.
Example: sudo python3 scripts/run_real.py --expected-kernel 6.18.64-tail
  --root fixtures/real-mount/real --output results/round3/sessions/s1-tail/real --rounds 10 --cpu 0
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


def commands(root):
    linux = root / "linux"
    return {
        "ls_photos": ["ls", "-l", "--time-style=+%s", str(root / "photos")],
        "find_linux": ["find", str(linux), "-path", str(linux / ".git"), "-prune", "-o", "-ls"],
        "tar_linux": ["tar", "cf", "/dev/null", "--exclude=.git", "-C", str(root), "linux"],
        "git_linux": ["git", "-C", str(linux), "--no-optional-locks", "status", "--porcelain"],
    }


def run(cmd, cpu):
    if cpu is not None:
        cmd = ["taskset", "-c", str(cpu)] + cmd
    env = dict(os.environ, LC_ALL="C", GIT_OPTIONAL_LOCKS="0")
    start = time.perf_counter_ns()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    elapsed = time.perf_counter_ns() - start
    if p.returncode:
        raise RuntimeError("%s failed: %s" % (cmd, p.stderr.decode(errors="replace")[:300]))
    return elapsed, hashlib.sha256(p.stdout).hexdigest(), p.stdout.count(b"\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected-kernel", required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--cpu", type=int)
    ap.add_argument("--seed", type=int, default=20261123)
    args = ap.parse_args()
    if platform.release() != args.expected_kernel:
        ap.error("unexpected kernel: " + platform.release())
    if args.output.exists():
        ap.error("output directory must be absent")
    args.output.mkdir(parents=True)
    cmds = commands(args.root)
    rng = random.Random(args.seed)
    rows, hashes = [], {}
    for rnd in range(args.rounds):
        order = list(cmds)
        rng.shuffle(order)
        for task in order:
            for mode in ("cold", "warm"):
                if mode == "cold":
                    os.sync()
                    Path("/proc/sys/vm/drop_caches").write_text("2\n")
                elapsed, digest, lines = run(cmds[task], args.cpu)
                if hashes.setdefault(task, digest) != digest:
                    raise RuntimeError(task + ": output changed between runs")
                rows.append({"kernel": platform.release(), "round": rnd, "task": task, "mode": mode,
                             "elapsed_ns": elapsed, "output_lines": lines, "output_sha256": digest})
                print(json.dumps(rows[-1]), flush=True)
    with (args.output / "real.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (args.output / "commands.json").write_text(json.dumps(cmds, indent=2) + "\n")


if __name__ == "__main__":
    main()
