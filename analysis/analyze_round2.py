#!/usr/bin/env python3
"""2차 측정 요약과 그림: 최신 memcmp(word)와의 비교, 끝 8바이트가 같은 이름(sametail).

results/round2/sessions/<세션>/ 의 lookup/summary.csv, lookup/presence.csv, ls/ls.csv,
correctness.json 을 읽어 analysis/ 에 아래 파일을 만든다.

  summary_round2_change.csv    비교마다 세션 중앙값의 중앙값, 변화율, 범위 겹침, 블록별 변화율
  summary_round2_presence.csv  있는 이름 / 없는 이름 조회 시간 (커널별, 세션 중앙값의 중앙값)
  fig3_round2_lookup.png       이름 조회 시간, 커널 4개
  fig4_round2_ls.png           ls -l 시간, 커널 4개

비교는 세 가지다. B0→tail(패치), B0→word(최신 memcmp만), word→word+tail(최신 memcmp 위의 패치).
블록 하나(s1..s4)에서 네 커널이 같은 시드를 쓴다.
실행: python3 analysis/analyze_round2.py   (matplotlib 필요)
"""
import csv
import glob
import json
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analyze import INK, INK2, MUTED, GRID, SURFACE  # 같은 글꼴 설정도 함께 적용된다

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis")
SESSIONS = os.path.join(ROOT, "results", "round2", "sessions")
KERNELS = [("5.4.214-b0", "B0", "#104281"), ("5.4.214-word", "word", "#6f9fd8"),
           ("5.4.214-tail", "tail", "#eb6834"), ("5.4.214-wordtail", "word+tail", "#a8461a")]
COMPARISONS = [("5.4.214-b0", "5.4.214-tail", "B0→tail"),
               ("5.4.214-b0", "5.4.214-word", "B0→word"),
               ("5.4.214-word", "5.4.214-wordtail", "word→word+tail")]
CASES = [
    ("short13", "번호형\nfile_00000000"),
    ("long128", "긴 공통 접두사\n120바이트 + 번호"),
    ("random128", "무작위\n128바이트"),
    ("varied", "길이 섞임\n13~240바이트"),
    ("sametail", "끝이 같은 이름\n00000_report.pdf"),
]
CACHES = [("warmdir", "dentry 캐시를 비운 뒤 (ext4가 이름을 비교함)"),
          ("warm", "dentry 캐시에 있을 때 (ext4까지 가지 않음)")]
LS_MODES = [("cold", "dentry 캐시를 비운 뒤"), ("warm", "바로 다시 실행 (캐시에 있음)")]
FOOT = ("Linux 5.4.214 · ext4 · 디렉터리마다 파일 10,000개 · 커널마다 4번 부팅 · 점 하나 = 부팅 한 번의 중앙값 · "
        "word = 5.15의 8바이트 단위 memcmp를 넣은 커널")


def sessions():
    found = {}
    for path in sorted(glob.glob(os.path.join(SESSIONS, "*"))):
        name = os.path.basename(path)
        with open(os.path.join(path, "exit")) as f:
            if f.read().strip() != "0":
                raise SystemExit("session did not finish: " + name)
        with open(os.path.join(path, "uname.txt")) as f:
            kernel = f.read().split()[2]
        found[name] = (kernel, path)
    return found


def load(found):
    lookup, ls, presence = {}, {}, {}
    for name, (kernel, path) in found.items():
        with open(os.path.join(path, "lookup", "summary.csv"), newline="") as f:
            for row in csv.DictReader(f):
                if row["kernel"] != kernel or int(row["errors"]):
                    raise SystemExit("bad row in " + name)
                us = int(row["elapsed_ns"]) / int(row["queries"]) / 1000
                lookup.setdefault((row["case"], row["cache"], kernel, name), []).append(us)
        with open(os.path.join(path, "ls", "ls.csv"), newline="") as f:
            for row in csv.DictReader(f):
                ls.setdefault((row["case"], row["mode"], kernel, name), []).append(int(row["elapsed_ns"]) / 1e6)
        presence_path = os.path.join(path, "lookup", "presence.csv")
        if not os.path.exists(presence_path):
            print("no presence.csv in", name)
            continue
        with open(presence_path, newline="") as f:
            for row in csv.DictReader(f):
                for kind in ("exists", "missing"):
                    presence.setdefault((row["case"], row["cache"], kind, kernel, name), []).append(
                        float(row[kind + "_median_ns"]) / 1000)
    return lookup, ls, presence


def per_kernel(data, case, mode):
    """kernel -> {block: 세션 중앙값}"""
    per = {}
    for (c, m, kernel, name), vals in data.items():
        if (c, m) == (case, mode):
            per.setdefault(kernel, {})[name.split("-")[0]] = statistics.median(vals)
    return per


def compare(per, base, new):
    a, b = per[base], per[new]
    am, bm = statistics.median(a.values()), statistics.median(b.values())
    pairs = {p: b[p] / a[p] - 1 for p in sorted(a) if p in b}
    overlap = not (max(b.values()) < min(a.values()) or min(b.values()) > max(a.values()))
    return {"base": a, "new": b, "base_median": am, "new_median": bm, "change": bm / am - 1,
            "overlap": overlap, "pairs": pairs}


def write_change(path, lookup, ls):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["measure", "case", "mode", "comparison", "base_sessions", "new_sessions",
                    "base_median", "new_median", "change_pct", "session_ranges_overlap",
                    "block_changes_pct", "new_faster_blocks"])
        for measure, data, modes in (("lookup_us", lookup, CACHES), ("ls_ms", ls, LS_MODES)):
            for case, _ in CASES:
                for mode, _ in modes:
                    per = per_kernel(data, case, mode)
                    for base, new, label in COMPARISONS:
                        r = compare(per, base, new)
                        w.writerow([measure, case, mode, label,
                                    " ".join("%.3f" % v for _, v in sorted(r["base"].items())),
                                    " ".join("%.3f" % v for _, v in sorted(r["new"].items())),
                                    "%.3f" % r["base_median"], "%.3f" % r["new_median"],
                                    "%.1f" % (100 * r["change"]), "yes" if r["overlap"] else "no",
                                    " ".join("%+.1f" % (100 * v) for _, v in sorted(r["pairs"].items())),
                                    "%d/%d" % (sum(v < 0 for v in r["pairs"].values()), len(r["pairs"]))])


def write_presence(path, presence):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "kind"] + ["%s_us" % k for k, _, _ in KERNELS])
        for case, _ in CASES:
            for kind in ("exists", "missing"):
                cells = []
                for kernel, _, _ in KERNELS:
                    vals = [statistics.median(v) for (c, m, k, kn, _), v in presence.items()
                            if (c, m, k, kn) == (case, "warmdir", kind, kernel)]
                    cells.append("%.3f" % statistics.median(vals))
                w.writerow([case, kind] + cells)


def figure(path, title, subtitle, data, modes, unit):
    fig, axes = plt.subplots(len(modes), len(CASES), figsize=(12, 3.2 * len(modes) + 1.1),
                             dpi=200, facecolor=SURFACE, squeeze=False)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.8, bottom=0.1, hspace=0.75, wspace=0.32)
    fig.text(0.01, 0.965, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.925, subtitle, fontsize=9, color=INK2, va="top")
    fig.text(0.01, 0.012, FOOT, fontsize=7.5, color=MUTED)
    for i, (mode, mode_label) in enumerate(modes):
        for j, (case, case_label) in enumerate(CASES):
            ax = axes[i][j]
            per = per_kernel(data, case, mode)
            base = statistics.median(per[KERNELS[0][0]].values())
            ax.set_facecolor(SURFACE)
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(GRID)
            ax.tick_params(length=0, labelsize=8, labelcolor=MUTED)
            ax.grid(axis="y", color=GRID, linewidth=0.6)
            ax.set_axisbelow(True)
            top = max(max(per[k].values()) for k, _, _ in KERNELS)
            for x, (kernel, label, color) in enumerate(KERNELS):
                vals = list(per[kernel].values())
                ax.scatter([x] * len(vals), vals, s=18, color=color, zorder=3, alpha=0.9)
                med = statistics.median(vals)
                ax.plot([x - 0.3, x + 0.3], [med, med], color=color, linewidth=2, zorder=2)
                if x:
                    change = 100 * (med / base - 1)
                    ax.text(x, max(vals) + top * 0.04, "0%" if abs(change) < 0.5 else "%+.0f%%" % change, ha="center",
                            va="bottom", fontsize=7.5, color=color, fontweight="bold")
            ax.set_xticks(range(len(KERNELS)))
            ax.set_xticklabels([k[1] for k in KERNELS], fontsize=7.5, color=INK2, rotation=30)
            ax.set_xlim(-0.6, len(KERNELS) - 0.4)
            ax.set_ylim(0, top * 1.25)
            if i == 0:
                ax.set_title(case_label, fontsize=9, color=INK, pad=14)
            if j == 0:
                ax.set_ylabel(unit, fontsize=8, color=MUTED)
        y = axes[i][0].get_position().y1 + (0.075 if i == 0 else 0.03)
        fig.text(0.01, y, mode_label, fontsize=9.5, color=INK, fontweight="bold")
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main():
    found = sessions()
    lookup, ls, presence = load(found)
    write_change(os.path.join(OUT, "summary_round2_change.csv"), lookup, ls)
    if presence:
        write_presence(os.path.join(OUT, "summary_round2_presence.csv"), presence)
    figure(os.path.join(OUT, "fig3_round2_lookup.png"), "이름 하나를 찾는 데 걸린 시간 (2차 측정, 커널 4개)",
           "숫자는 B0 대비 변화. 파랑 계열 = 끝 8바이트 비교 없음, 주황 계열 = 있음, 옅은 색 = 8바이트 단위 memcmp",
           lookup, CACHES, "µs / 이름")
    figure(os.path.join(OUT, "fig4_round2_ls.png"), "ls -l 한 번에 걸린 시간 (2차 측정, 커널 4개)",
           "숫자는 B0 대비 변화. 파랑 계열 = 끝 8바이트 비교 없음, 주황 계열 = 있음, 옅은 색 = 8바이트 단위 memcmp",
           ls, LS_MODES, "ms")
    for name, (kernel, path) in sorted(found.items()):
        p = os.path.join(path, "correctness.json")
        if os.path.exists(p):
            with open(p) as f:
                r = json.load(f)
            print("correctness", name, kernel, r["result"], r["baseline"]["content_name_nlink_sha256"],
                  len(r["stages"]))
    with open(os.path.join(OUT, "summary_round2_change.csv")) as f:
        for row in csv.DictReader(f):
            print(row["measure"], row["case"], row["mode"], row["comparison"],
                  row["base_median"], "->", row["new_median"], row["change_pct"] + "%",
                  "overlap=" + row["session_ranges_overlap"], row["block_changes_pct"])


if __name__ == "__main__":
    main()
