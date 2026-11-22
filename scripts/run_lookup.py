#!/usr/bin/env python3
"""Time name lookups (fstatat) in the four test directories on the running kernel.

Works on any kernel without the old experiment switches (B0 or the tail kernel).
Each round runs every (case, cache mode) cell twice, as run1 and run2, in a
shuffled order, so run1/run2 show the noise inside one boot.
Example: sudo python3 scripts/run_lookup.py --expected-kernel 5.4.214-tail
 --bench bench/lookup_bench --fixtures fixtures/leaf-mount/leaf --names results/names
 --output results/sessions/s1-tail/lookup --rounds 8 --modes warmdir,warm --cpu 0
Kernels are compared across separate boots; never pair rows across sessions.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import time

import select


def wait_byte(fd, process, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], min(0.25, max(0, end - time.monotonic())))
        if ready:
            if os.read(fd, 1) == b"R":
                return
            raise RuntimeError("benchmark closed its handshake pipe")
        if process.poll() is not None:
            raise RuntimeError("benchmark exited before handshake")
    raise TimeoutError("benchmark handshake timed out")


def run_trial(args, case, cache, label, rep, trial, seed):
    prefix = args.output / ("trial_%04d_%s_%s_%s" % (trial, case["case"], cache, label))
    if args.drop_caches:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text(str(args.drop_caches) + "\n")
    ready_r, ready_w = os.pipe()
    start_r, start_w = os.pipe()
    done_r, done_w = os.pipe()
    release_r, release_w = os.pipe()
    parent_fds, child_fds = [ready_r, start_w, done_r, release_w], [ready_w, start_r, done_w, release_r]
    latencies = Path(str(prefix) + ".latencies.csv")
    command = [str(args.bench), "--dir", str(args.fixtures / case["directory"]),
               "--names", str(args.names / case["names_file"]), "--seed", str(seed),
               "--trial", str(trial), "--label", label, "--latencies", str(latencies),
               "--warm-dir", "--ready-fd", str(ready_w), "--start-fd", str(start_r),
               "--done-fd", str(done_w), "--release-fd", str(release_r)]
    if cache == "warm":
        command += ["--warmup", "1"]
    if args.cpu is not None:
        command = ["taskset", "-c", str(args.cpu)] + command
    record = {"phase": "session", "trial": trial, "round": rep, "case": case["case"],
              "cache": cache, "label": label,
              "seed": seed, "drop_caches": args.drop_caches,
              "names_sha256": case["names_sha256"],
              "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    process = None
    try:
        with Path(str(prefix) + ".csv").open("x") as out, Path(str(prefix) + ".stderr").open("x") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, pass_fds=child_fds)
            for fd in child_fds:
                os.close(fd)
            child_fds = []
            wait_byte(ready_r, process, args.timeout)
            os.write(start_w, b"G")
            wait_byte(done_r, process, args.timeout)
            os.write(release_w, b"G")
            record["returncode"] = process.wait(timeout=args.timeout)
            if record["returncode"]:
                raise RuntimeError("lookup_bench correctness or runtime failure")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        for fd in parent_fds + child_fds:
            os.close(fd)
        Path(str(prefix) + ".json").write_text(json.dumps(record, indent=2) + "\n")
    with Path(str(prefix) + ".csv").open() as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1 or int(rows[0]["errors"]):
        raise RuntimeError("unexpected measured passes or correctness failure")
    row = rows[0]
    if int(row["positive"]) != case["positive"] or int(row["negative"]) != case["negative"]:
        raise RuntimeError("query count mismatch")
    with latencies.open("rb") as src, gzip.open(str(latencies) + ".gz", "wb", compresslevel=3) as dst:
        shutil.copyfileobj(src, dst)
    latencies.unlink()
    row.update(case=case["case"], cache=cache, round=rep, drop_caches=args.drop_caches)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-kernel", required=True)
    parser.add_argument("--cases")
    parser.add_argument("--modes", default="warmdir")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--drop-caches", type=int, choices=(0, 2), default=2)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if platform.release() != args.expected_kernel:
        parser.error("unexpected kernel: " + platform.release())
    controls = Path("/sys/module/ext4/parameters")
    if any((controls / name).exists() for name in ("leaf_prefilter", "leaf_profile", "es_lookup_refresh")):
        parser.error("old experiment switches present; use the B0 or tail kernel")
    if args.rounds <= 0 or args.timeout <= 0:
        parser.error("positive rounds and timeout required")
    for key in ("bench", "fixtures", "names", "output"):
        setattr(args, key, getattr(args, key).resolve())
    if args.output.exists():
        parser.error("output directory must be absent")
    modes = args.modes.split(",")
    if len(set(modes)) != len(modes) or any(m not in ("warmdir", "warm") for m in modes):
        parser.error("invalid cache modes")
    manifest = json.loads((args.names / "manifest.json").read_text())
    available = {c["case"]: c for c in manifest["cases"]}
    selected = args.cases.split(",") if args.cases else list(available)
    if len(set(selected)) != len(selected) or any(c not in available for c in selected):
        parser.error("invalid case selection")
    cases = [available[c] for c in selected]
    for case in cases:
        if not (args.fixtures / case["directory"]).is_dir():
            parser.error("missing fixture directory")
        if hashlib.sha256((args.names / case["names_file"]).read_bytes()).hexdigest() != case["names_sha256"]:
            parser.error("names file hash mismatch")
    args.output.mkdir(parents=True)
    metadata = {"phase": "session", "kernel": platform.release(), "seed": args.seed,
                "rounds": args.rounds, "drop_caches": args.drop_caches,
                "cpu": args.cpu, "cases": cases, "modes": modes,
                "labels": ["run1", "run2"],
                "benchmark_sha256": hashlib.sha256(args.bench.read_bytes()).hexdigest(),
                "metric": "elapsed_ns / queries; per-call timing is a separate field",
                "cache_note": "warmdir enumerates names after drop_caches=2; warm also looks up all names once",
                "comparison_note": "B0 and tail are separate boot sessions; compare session summaries, not rows"}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rng = random.Random(args.seed)
    cells = [(case, mode, label) for case in cases for mode in modes for label in ("run1", "run2")]
    rows, checksums = [], {}
    for rep in range(args.rounds):
        if rep % 2 == 0:
            rng.shuffle(cells)
            order = list(cells)
        else:
            order.reverse()
        seed = (args.seed + rep * 1000003) % (2**64)
        for case, cache, label in order:
            row = run_trial(args, case, cache, label, rep, len(rows), seed)
            key = (case["case"], cache, rep)
            if checksums.setdefault(key, row["digest"]) != row["digest"]:
                raise RuntimeError("paired semantic checksum mismatch")
            rows.append(row)
            with (args.output / "summary.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader(); writer.writerows(rows)
            print(json.dumps({k: row[k] for k in ("case", "cache", "round", "label", "elapsed_ns", "errors")}), flush=True)


if __name__ == "__main__":
    main()
