#!/usr/bin/env python3
"""3차 측정 요약과 그림: 최신 커널(6.18.64)과 실제 프로그램, ftrace 프로파일.

results/round3/sessions/<세션>/ 의 lookup/summary.csv, lookup/presence.csv, ls/ls.csv,
real/real.csv, profile/profile.csv 를 읽어 analysis/ 에 아래 파일을 만든다.

  summary_round3_change.csv   커널 버전마다 원본→패치 비교(이름 조회, 있는/없는 이름, ls -l, 실제 프로그램)
  summary_round3_profile.csv  ext4_lookup, ext4_search_dir 호출 수와 평균 시간(프로파일러 켠 별도 실행)
  fig5_round3_real.png        실제 프로그램 시간, 커널 4개
  fig6_round3_lookup.png      이름 조회 시간, 커널 4개

블록 하나(s1..s4)에서 네 커널이 같은 시드를 쓴다. 세션 하나를 점 하나로 본다.
실행: python3 analysis/analyze_round3.py   (matplotlib 필요)
"""
import csv
import glob
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analyze import INK, INK2, MUTED, GRID, SURFACE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis")
SESSIONS = os.path.join(ROOT, "results", "round3", "sessions")
KERNELS = [("5.4.214-b0", "5.4 원본", "#104281"), ("5.4.214-tail", "5.4 패치", "#eb6834"),
           ("6.18.64-b0", "6.18 원본", "#6f9fd8"), ("6.18.64-tail", "6.18 패치", "#a8461a")]
COMPARISONS = [("5.4.214-b0", "5.4.214-tail", "5.4 원본→패치"), ("6.18.64-b0", "6.18.64-tail", "6.18 원본→패치")]
CASES = [("short13", "번호형"), ("long128", "긴 공통 접두사"), ("random128", "무작위 128B"),
         ("varied", "길이 섞임"), ("sametail", "끝이 같은 이름")]
TASKS = [("ls_photos", "ls -l\n사진 이름 9,999개"), ("find_linux", "find -ls\n커널 소스 트리"),
         ("tar_linux", "tar cf /dev/null\n커널 소스 트리"), ("git_linux", "git status\n커널 소스 트리")]


def sessions():
    found = {}
    for path in sorted(glob.glob(os.path.join(SESSIONS, "*"))):
        with open(os.path.join(path, "exit")) as f:
            if f.read().strip() != "0":
                raise SystemExit("session did not finish: " + path)
        with open(os.path.join(path, "uname.txt")) as f:
            found[os.path.basename(path)] = (f.read().split()[2], path)
    return found


def load(found):
    data = {}
    for name, (kernel, path) in found.items():
        with open(os.path.join(path, "lookup", "summary.csv"), newline="") as f:
            for r in csv.DictReader(f):
                if int(r["errors"]):
                    raise SystemExit("lookup error in " + name)
                key = ("lookup_us", r["case"], r["cache"])
                data.setdefault(key, {}).setdefault(kernel, {}).setdefault(name, []).append(
                    int(r["elapsed_ns"]) / int(r["queries"]) / 1000)
        presence = os.path.join(path, "lookup", "presence.csv")
        if os.path.exists(presence):
            with open(presence, newline="") as f:
                for r in csv.DictReader(f):
                    for kind in ("exists", "missing"):
                        key = (kind + "_us", r["case"], r["cache"])
                        data.setdefault(key, {}).setdefault(kernel, {}).setdefault(name, []).append(
                            float(r[kind + "_median_ns"]) / 1000)
        else:
            print("no presence.csv in", name)
        with open(os.path.join(path, "ls", "ls.csv"), newline="") as f:
            for r in csv.DictReader(f):
                key = ("ls_ms", r["case"], r["mode"])
                data.setdefault(key, {}).setdefault(kernel, {}).setdefault(name, []).append(int(r["elapsed_ns"]) / 1e6)
        with open(os.path.join(path, "real", "real.csv"), newline="") as f:
            for r in csv.DictReader(f):
                key = ("real_ms", r["task"], r["mode"])
                data.setdefault(key, {}).setdefault(kernel, {}).setdefault(name, []).append(int(r["elapsed_ns"]) / 1e6)
    return data


def per_block(sess):
    return {name.split("-")[0]: statistics.median(v) for name, v in sess.items()}


def compare(per, base, new):
    a, b = per_block(per[base]), per_block(per[new])
    am, bm = statistics.median(a.values()), statistics.median(b.values())
    pairs = {p: b[p] / a[p] - 1 for p in sorted(a) if p in b}
    overlap = not (max(b.values()) < min(a.values()) or min(b.values()) > max(a.values()))
    return a, b, am, bm, bm / am - 1, overlap, pairs


def write_change(path, data):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["measure", "case", "mode", "comparison", "base_sessions", "new_sessions", "base_median",
                    "new_median", "change_pct", "session_ranges_overlap", "block_changes_pct", "new_faster_blocks"])
        for (measure, case, mode), per in sorted(data.items()):
            for base, new, label in COMPARISONS:
                if base not in per or new not in per:
                    continue
                a, b, am, bm, ch, ov, pairs = compare(per, base, new)
                w.writerow([measure, case, mode, label, " ".join("%.3f" % v for _, v in sorted(a.items())),
                            " ".join("%.3f" % v for _, v in sorted(b.items())), "%.3f" % am, "%.3f" % bm,
                            "%.1f" % (100 * ch), "yes" if ov else "no",
                            " ".join("%+.1f" % (100 * v) for _, v in sorted(pairs.items())),
                            "%d/%d" % (sum(v < 0 for v in pairs.values()), len(pairs))])


def write_profile(path, found):
    rows = {}
    for name, (kernel, sp) in found.items():
        p = os.path.join(sp, "profile", "profile.csv")
        if not os.path.exists(p):
            continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                rows.setdefault((r["workload"], kernel, r["function"]), []).append(
                    (int(r["hits"]), float(r["total_us"])))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "kernel", "function", "runs", "hits_median", "avg_us_median", "total_us_median"])
        for (wl, kernel, func), vals in sorted(rows.items()):
            hits = statistics.median(v[0] for v in vals)
            tot = statistics.median(v[1] for v in vals)
            avg = statistics.median(v[1] / v[0] for v in vals if v[0])
            w.writerow([wl, kernel, func, len(vals), "%.0f" % hits, "%.4f" % avg, "%.1f" % tot])


def figure(path, title, subtitle, data, measure, items, mode, unit):
    fig, axes = plt.subplots(1, len(items), figsize=(2.4 * len(items) + 0.6, 4.2), dpi=200, facecolor=SURFACE,
                             squeeze=False)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.72, bottom=0.2, wspace=0.35)
    fig.text(0.01, 0.95, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.87, subtitle, fontsize=9, color=INK2, va="top")
    for j, (key, label) in enumerate(items):
        ax = axes[0][j]
        per = data.get((measure, key, mode), {})
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0, labelsize=8, labelcolor=MUTED)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        top = 0
        for x, (kernel, klabel, color) in enumerate(KERNELS):
            if kernel not in per:
                continue
            vals = list(per_block(per[kernel]).values())
            top = max(top, max(vals))
            ax.scatter([x] * len(vals), vals, s=16, color=color, zorder=3)
            ax.plot([x - 0.3, x + 0.3], [statistics.median(vals)] * 2, color=color, linewidth=2, zorder=2)
        for i, (base, new, _) in enumerate(COMPARISONS):
            if base in per and new in per:
                _, _, am, bm, ch, ov, _ = compare(per, base, new)
                ax.text(0.5 + 2 * i, top * 1.12, "%+.1f%%" % (100 * ch), ha="center", fontsize=8,
                        color=INK if not ov else MUTED, fontweight="bold")
        ax.set_xticks(range(len(KERNELS)))
        ax.set_xticklabels([k[1] for k in KERNELS], fontsize=7, color=INK2, rotation=30)
        ax.set_ylim(0, top * 1.3 if top else 1)
        ax.set_title(label, fontsize=9, color=INK, pad=8)
        if j == 0:
            ax.set_ylabel(unit, fontsize=8, color=MUTED)
    fig.text(0.01, 0.02, "Linux 5.4.214와 6.18.64 · ext4 · 커널마다 4번 부팅 · 점 하나 = 부팅 한 번의 중앙값 · "
             "숫자는 같은 버전 안에서 원본→패치 변화(회색 = 범위 겹침)", fontsize=7, color=MUTED)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main():
    found = sessions()
    data = load(found)
    write_change(os.path.join(OUT, "summary_round3_change.csv"), data)
    write_profile(os.path.join(OUT, "summary_round3_profile.csv"), found)
    figure(os.path.join(OUT, "fig5_round3_real.png"), "실제 프로그램 한 번에 걸린 시간 (3차 측정)",
           "dentry 캐시를 비운 직후 실행. 사진 이름 디렉터리와 커널 소스 트리(실제 파일 이름)",
           data, "real_ms", TASKS, "cold", "ms")
    figure(os.path.join(OUT, "fig6_round3_lookup.png"), "이름 하나를 찾는 데 걸린 시간 (3차 측정, 6.18 포함)",
           "dentry 캐시를 비운 뒤. 2차 측정과 같은 디렉터리", data, "lookup_us", CASES, "warmdir", "µs / 이름")
    with open(os.path.join(OUT, "summary_round3_change.csv")) as f:
        for r in csv.DictReader(f):
            print(r["measure"], r["case"], r["mode"], r["comparison"], r["base_median"], "->", r["new_median"],
                  r["change_pct"] + "%", "overlap=" + r["session_ranges_overlap"], r["block_changes_pct"])


if __name__ == "__main__":
    main()
