#!/usr/bin/env python3
"""calclock 측정 요약: results/calclock/{calclock,counts}.csv -> analysis/summary_calclock_{time,count}.csv

실행: python3 calclock/analyze_calclock.py
"""
import csv
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, "results", "calclock")
OUT = os.path.join(ROOT, "analysis")


def rows(name):
    with open(os.path.join(IN, name), newline="") as f:
        return list(csv.DictReader(f))


def main():
    t = {}
    for r in rows("calclock.csv"):
        t.setdefault((r["workload"], r["function"]), {}).setdefault(r["variant"], {})[int(r["rep"])] = (
            int(r["calls"]), int(r["time_ns"]))
    lines = []
    for (wl, fn), v in sorted(t.items()):
        per = {k: [x[1] / x[0] for x in d.values()] for k, d in v.items()}
        calls = {k: sorted({x[0] for x in d.values()}) for k, d in v.items()}
        o, p = st.median(per["orig"]), st.median(per["tail"])
        pairs = [(v["tail"][i][1] / v["tail"][i][0]) / (v["orig"][i][1] / v["orig"][i][0]) - 1 for i in v["orig"]]
        overlap = not (max(per["tail"]) < min(per["orig"]) or min(per["tail"]) > max(per["orig"]))
        lines.append([wl, fn, len(pairs), "%d~%d" % (calls["orig"][0], calls["orig"][-1]),
                      "%d~%d" % (calls["tail"][0], calls["tail"][-1]), "%.1f" % o, "%.1f" % p,
                      "%.1f" % (100 * (p / o - 1)), "%.1f~%.1f" % (min(per["orig"]), max(per["orig"])),
                      "%.1f~%.1f" % (min(per["tail"]), max(per["tail"])), "yes" if overlap else "no",
                      "%d/%d" % (sum(x < 0 for x in pairs), len(pairs))])
    with open(os.path.join(OUT, "summary_calclock_time.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "function", "reps", "calls_orig", "calls_tail", "orig_ns_per_call", "tail_ns_per_call",
                    "change_pct", "orig_range", "tail_range", "ranges_overlap", "tail_faster_pairs"])
        w.writerows(lines)
    c = {}
    for r in rows("counts.csv"):
        c.setdefault((r["workload"], r["variant"]), {}).setdefault(r["step"], []).append(int(r["entries"]))
    with open(os.path.join(OUT, "summary_calclock_count.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "variant", "entries", "length_differs", "last_8_bytes_differ", "full_compare",
                    "full_compare_pct"])
        for (wl, var), s in sorted(c.items()):
            m = {k: st.median(v) for k, v in s.items()}
            total = sum(m.values())
            w.writerow([wl, var, "%.0f" % total] + ["%.0f" % m[k] for k in
                       ("length_differs", "last_8_bytes_differ", "full_compare")] +
                       ["%.2f" % (100 * m["full_compare"] / total)])
    for name in ("summary_calclock_time.csv", "summary_calclock_count.csv"):
        with open(os.path.join(OUT, name)) as f:
            print(f.read())


if __name__ == "__main__":
    main()
