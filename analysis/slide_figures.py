#!/usr/bin/env python3
"""발표 슬라이드용 어두운 그림 2장.

analyze.py와 같은 원자료(results/sessions/)를 읽어, 슬라이드 배경(#111827)에 맞춘
한 줄짜리 그림을 analysis/slides/ 에 만든다.

  fig_lookup_dark.png   dentry 캐시를 비운 뒤 이름 하나를 찾는 시간
  fig_ls_dark.png       dentry 캐시를 비운 뒤 ls -l 한 번에 걸린 시간

실행: python3 analysis/slide_figures.py   (matplotlib 필요)
"""
import os
import statistics

import matplotlib.pyplot as plt

import analyze

OUT = os.path.join(analyze.OUT, "slides")
BG, CARD, INK, BODY, MUTED, GRID = "#111827", "#111827", "#F9FAFB", "#D1D5DB", "#9CA3AF", "#283040"
B0, TAIL = "#60A5FA", "#FB923C"
CASES = [("short13", "번호형 이름"), ("long128", "긴 공통 접두사"),
         ("random128", "무작위 128바이트"), ("varied", "길이 섞임")]


def figure(path, rows, mode, unit):
    fig, axes = plt.subplots(1, 4, figsize=(9.0, 2.9), dpi=200, facecolor=BG)
    fig.subplots_adjust(left=0.07, right=0.995, top=0.80, bottom=0.12, wspace=0.42)
    for ax, (case, label) in zip(axes, CASES):
        r = rows[(case, mode)]
        ax.set_facecolor(BG)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0, labelsize=9, labelcolor=MUTED)
        ax.grid(axis="y", color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        for x, (vals, color) in enumerate(((r["b0"], B0), (r["tail"], TAIL))):
            v = list(vals.values())
            ax.scatter([x] * len(v), v, s=26, color=color, zorder=3)
            med = statistics.median(v)
            ax.plot([x - 0.28, x + 0.28], [med, med], color=color, linewidth=2.4, zorder=2)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["원본", "패치"], fontsize=10, color=BODY)
        ax.set_xlim(-0.65, 1.65)
        top = max(max(r["b0"].values()), max(r["tail"].values()))
        ax.set_ylim(0, top * 1.22)
        clear = r["change"] < 0 and not r["overlap"]
        c = 100 * r["change"]
        label_text = "차이 없음" if not clear else ("%+.0f%%" % c if abs(c) >= 10 else "%+.1f%%" % c)
        ax.text(0.5, 0.99, label_text.replace("-", "−"), transform=ax.transAxes, ha="center", va="top",
                fontsize=13, fontweight="bold", color=TAIL if clear else MUTED)
        ax.set_title(label, fontsize=11, color=INK, pad=12, fontweight="bold")
    axes[0].set_ylabel(unit, fontsize=9, color=MUTED)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    found = analyze.sessions()
    lookup, ls = analyze.load(found)
    figure(os.path.join(OUT, "fig_lookup_dark.png"), analyze.compare(lookup, analyze.CACHES),
           "warmdir", "µs / 이름")
    figure(os.path.join(OUT, "fig_ls_dark.png"), analyze.compare(ls, analyze.LS_MODES), "cold", "ms")


if __name__ == "__main__":
    main()
