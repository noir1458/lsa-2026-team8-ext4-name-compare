#!/usr/bin/env python3
"""B0 / tail 비교 결과 요약과 그림.

results/sessions/<세션>/ 의 lookup/summary.csv, ls/ls.csv, correctness.json 을 읽어
analysis/ 에 요약표 3개와 그림 2장을 만든다.

  summary_lookup.csv   세션별 이름 조회 시간 (질의 하나당 µs, 세션 안 40회의 중앙값·최소·최대)
  summary_ls.csv       세션별 ls -l 시간 (ms, 세션 안 20회의 중앙값·최소·최대)
  summary_change.csv   커널별 세션 중앙값의 중앙값, 변화율, 세션 범위가 겹치는지, 쌍별 변화율
  summary_presence.csv 있는 이름 / 없는 이름으로 나눈 조회 시간과, 있는 이름에서 줄어든 시간 × 10,000을
                       ls -l(cold)에서 실제로 줄어든 시간과 나란히 놓은 표 (lookup/presence.csv 필요)
  fig1_lookup.png      이름 조회 시간
  fig2_ls.png          ls -l 시간

커널은 따로 부팅해서 쟀으므로 세션 하나를 점 하나로 보고 비교한다.
실행: python3 analysis/analyze.py   (matplotlib 필요)
"""
import csv
import glob
import json
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis")
KERNELS = [("5.4.214-b0", "B0 (원본)", "#104281"), ("5.4.214-tail", "tail (패치)", "#eb6834")]
CASES = [
    ("short13", "번호형 이름\nfile_00000000"),
    ("long128", "긴 공통 접두사\n120바이트 + 번호"),
    ("random128", "무작위\n128바이트"),
    ("varied", "길이 섞임\n13~240바이트"),
]
CACHES = [("warmdir", "dentry 캐시를 비운 뒤 (ext4가 이름을 비교함)"),
          ("warm", "dentry 캐시에 있을 때 (ext4까지 가지 않음)")]
LS_MODES = [("cold", "dentry 캐시를 비운 뒤"), ("warm", "바로 다시 실행 (캐시에 있음)")]

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
FOOT = "Linux 5.4.214 · ext4 · 디렉터리마다 파일 10,000개 · 커널마다 4번 부팅 · 점 하나 = 부팅 한 번의 중앙값"

_installed = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [n for n in ("Apple SD Gothic Neo", "NanumGothic", "Noto Sans CJK KR",
                                           "Malgun Gothic", "DejaVu Sans") if n in _installed]
plt.rcParams["axes.unicode_minus"] = False


def sessions():
    found = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "results", "sessions", "*"))):
        name = os.path.basename(path)
        with open(os.path.join(path, "exit")) as f:
            if f.read().strip() != "0":
                raise SystemExit("session did not finish: " + name)
        with open(os.path.join(path, "uname.txt")) as f:
            kernel = f.read().split()[2]
        found[name] = (kernel, path)
    return found


def summarize(values):
    return statistics.median(values), min(values), max(values)


def load(found):
    lookup, ls = {}, {}
    for name, (kernel, path) in found.items():
        with open(os.path.join(path, "lookup", "summary.csv"), newline="") as f:
            for row in csv.DictReader(f):
                if row["kernel"] != kernel or int(row["errors"]):
                    raise SystemExit("bad row in " + name)
                us = int(row["elapsed_ns"]) / int(row["queries"]) / 1000
                lookup.setdefault((row["case"], row["cache"], kernel, name), []).append(us)
        with open(os.path.join(path, "ls", "ls.csv"), newline="") as f:
            for row in csv.DictReader(f):
                ms = int(row["elapsed_ns"]) / 1e6
                ls.setdefault((row["case"], row["mode"], kernel, name), []).append(ms)
    return lookup, ls


def pair_of(name):
    return name.split("-")[0]


def write_session_table(path, data, unit):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "mode", "kernel", "session", "runs",
                    "median_" + unit, "min_" + unit, "max_" + unit])
        for (case, mode, kernel, name), vals in sorted(data.items()):
            med, lo, hi = summarize(vals)
            w.writerow([case, mode, kernel, name, len(vals), "%.3f" % med, "%.3f" % lo, "%.3f" % hi])


def compare(data, modes):
    """(case, mode) -> 커널별 세션 중앙값 목록, 변화율, 겹침, 쌍별 변화율"""
    rows = {}
    for case, _ in CASES:
        for mode, _ in modes:
            per = {}
            for (c, m, kernel, name), vals in data.items():
                if (c, m) == (case, mode):
                    per.setdefault(kernel, {})[pair_of(name)] = statistics.median(vals)
            b0, tail = per[KERNELS[0][0]], per[KERNELS[1][0]]
            b0m, tailm = statistics.median(b0.values()), statistics.median(tail.values())
            pairs = {p: tail[p] / b0[p] - 1 for p in sorted(b0) if p in tail}
            overlap = not (max(tail.values()) < min(b0.values()) or min(tail.values()) > max(b0.values()))
            rows[(case, mode)] = {"b0": b0, "tail": tail, "b0_median": b0m, "tail_median": tailm,
                                  "change": tailm / b0m - 1, "overlap": overlap, "pairs": pairs}
    return rows


def write_change(path, lookup_cmp, ls_cmp):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["measure", "case", "mode", "b0_sessions", "tail_sessions", "b0_median", "tail_median",
                    "change_pct", "session_ranges_overlap", "pair_changes_pct", "tail_faster_pairs"])
        for measure, cmp_rows in (("lookup_us", lookup_cmp), ("ls_ms", ls_cmp)):
            for (case, mode), r in cmp_rows.items():
                w.writerow([measure, case, mode,
                            " ".join("%.3f" % v for _, v in sorted(r["b0"].items())),
                            " ".join("%.3f" % v for _, v in sorted(r["tail"].items())),
                            "%.3f" % r["b0_median"], "%.3f" % r["tail_median"], "%.1f" % (100 * r["change"]),
                            "yes" if r["overlap"] else "no",
                            " ".join("%+.1f" % (100 * v) for _, v in sorted(r["pairs"].items())),
                            "%d/%d" % (sum(v < 0 for v in r["pairs"].values()), len(r["pairs"]))])


def figure(path, title, subtitle, cmp_rows, modes, unit):
    fig, axes = plt.subplots(len(modes), len(CASES), figsize=(10, 3.1 * len(modes) + 1.1),
                             dpi=200, facecolor=SURFACE, squeeze=False)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.78, bottom=0.08, hspace=0.95, wspace=0.35)
    fig.text(0.012, 0.965, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.925, subtitle, fontsize=9, color=INK2, va="top")
    fig.text(0.012, 0.012, FOOT, fontsize=7.5, color=MUTED)
    for i, (mode, mode_label) in enumerate(modes):
        for j, (case, case_label) in enumerate(CASES):
            ax = axes[i][j]
            r = cmp_rows[(case, mode)]
            ax.set_facecolor(SURFACE)
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(GRID)
            ax.tick_params(length=0, labelsize=8, labelcolor=MUTED)
            ax.grid(axis="y", color=GRID, linewidth=0.6)
            ax.set_axisbelow(True)
            for x, (kernel, label, color) in enumerate(KERNELS):
                vals = list((r["b0"] if x == 0 else r["tail"]).values())
                ax.scatter([x] * len(vals), vals, s=22, color=color, zorder=3, alpha=0.9)
                med = statistics.median(vals)
                ax.plot([x - 0.25, x + 0.25], [med, med], color=color, linewidth=2, zorder=2)
            ax.set_xticks([0, 1])
            ax.set_xticklabels(["B0", "tail"], fontsize=8.5, color=INK2)
            ax.set_xlim(-0.6, 1.6)
            top = max(max(r["b0"].values()), max(r["tail"].values()))
            ax.set_ylim(0, top * 1.25)
            note = "%+.0f%%" % (100 * r["change"])
            clear = r["change"] < 0 and not r["overlap"]
            ax.text(0.5, 0.97, note, transform=ax.transAxes, ha="center", va="top", fontsize=10,
                    fontweight="bold", color=KERNELS[1][2] if clear else INK2)
            if i == 0:
                ax.set_title(case_label, fontsize=9, color=INK, pad=14)
            if j == 0:
                ax.set_ylabel(unit, fontsize=8, color=MUTED)
        y = axes[i][0].get_position().y1 + (0.075 if i == 0 else 0.03)
        fig.text(0.012, y, mode_label, fontsize=9.5, color=INK, fontweight="bold")
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def correctness(found):
    out = {}
    for name, (kernel, path) in found.items():
        p = os.path.join(path, "correctness.json")
        if os.path.exists(p):
            with open(p) as f:
                r = json.load(f)
            out[name] = (kernel, r["result"], r["baseline"]["content_name_nlink_sha256"],
                         len(r["stages"]), r["experiment_switch_present"])
    return out


def presence(found, ls_cmp):
    """세션별 presence.csv(scripts/split_presence.py)에서 dentry 캐시를 비운 뒤의 조회만 본다."""
    per = {}
    for name, (kernel, path) in found.items():
        with open(os.path.join(path, "lookup", "presence.csv"), newline="") as f:
            for row in csv.DictReader(f):
                if row["cache"] != "warmdir":
                    continue
                for kind in ("exists", "missing"):
                    per.setdefault((row["case"], kind, kernel, name), []).append(
                        float(row[kind + "_median_ns"]) / 1000)
    def med(case, kind, kernel):
        return statistics.median(statistics.median(v) for (c, k, kn, _), v in per.items()
                                 if (c, k, kn) == (case, kind, kernel))
    rows = []
    for case, _ in CASES:
        b0, tail = KERNELS[0][0], KERNELS[1][0]
        e0, e1, m0, m1 = med(case, "exists", b0), med(case, "exists", tail), med(case, "missing", b0), med(case, "missing", tail)
        files = 10000
        r = ls_cmp[(case, "cold")]
        rows.append([case, "%.3f" % e0, "%.3f" % e1, "%.1f" % (100 * (e1 / e0 - 1)),
                     "%.3f" % m0, "%.3f" % m1, "%.1f" % (100 * (m1 / m0 - 1)),
                     "%.1f" % ((e0 - e1) * files / 1000), "%.1f" % (r["b0_median"] - r["tail_median"])])
    with open(os.path.join(OUT, "summary_presence.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "b0_exists_us", "tail_exists_us", "exists_change_pct",
                    "b0_missing_us", "tail_missing_us", "missing_change_pct",
                    "exists_saving_x10000_ms", "ls_cold_saving_ms"])
        w.writerows(rows)
    return rows


def main():
    found = sessions()
    lookup, ls = load(found)
    write_session_table(os.path.join(OUT, "summary_lookup.csv"), lookup, "us_per_query")
    write_session_table(os.path.join(OUT, "summary_ls.csv"), ls, "ms")
    lookup_cmp, ls_cmp = compare(lookup, CACHES), compare(ls, LS_MODES)
    write_change(os.path.join(OUT, "summary_change.csv"), lookup_cmp, ls_cmp)
    figure(os.path.join(OUT, "fig1_lookup.png"), "이름 하나를 찾는 데 걸린 시간",
           "fstatat로 있는 이름 10,000개와 없는 이름 10,000개를 섞어 찾은 평균. 숫자는 B0 대비 tail의 변화(주황: 부팅별 범위가 겹치지 않음)",
           lookup_cmp, CACHES, "µs / 이름")
    figure(os.path.join(OUT, "fig2_ls.png"), "ls -l 한 번에 걸린 시간",
           "파일 10,000개 디렉터리에서 ls -l (이름마다 lstat). 숫자는 B0 대비 tail의 변화(주황: 부팅별 범위가 겹치지 않음)",
           ls_cmp, LS_MODES, "ms")
    for row in presence(found, ls_cmp):
        print("presence", *row)
    for name, row in sorted(correctness(found).items()):
        print("correctness", name, *row)
    for (case, mode), r in lookup_cmp.items():
        print("lookup", case, mode, "%.2f -> %.2f us (%+.1f%%) overlap=%s pairs=%s" % (
            r["b0_median"], r["tail_median"], 100 * r["change"], r["overlap"],
            " ".join("%+.1f" % (100 * v) for v in r["pairs"].values())))
    for (case, mode), r in ls_cmp.items():
        print("ls", case, mode, "%.1f -> %.1f ms (%+.1f%%) overlap=%s pairs=%s" % (
            r["b0_median"], r["tail_median"], 100 * r["change"], r["overlap"],
            " ".join("%+.1f" % (100 * v) for v in r["pairs"].values())))


if __name__ == "__main__":
    main()
