#!/usr/bin/env python3
"""4차 측정 요약과 그림: 1~3차의 비교를 정상 속도의 VM에서 커널 6개로 다시 잰 것.

1~3차는 VM이 지금보다 약 3배 느린 상태에서 쟀다(2026-11-25에 확인). 절차는 3차와 같고,
세션마다 앞·중간·뒤에 bench/cpu_state로 VM 속도를 적었다(state.txt).

results/round4/sessions/<세션>/ 을 읽어 analysis/ 에 아래 파일을 만든다.
  summary_round4_change.csv    비교마다 세션 중앙값의 중앙값, 변화율, 범위 겹침, 블록별 변화율
  summary_round4_profile.csv   ext4_lookup, ext4_search_dir 호출 수와 평균 시간(프로파일러 켠 별도 실행)
  summary_round4_state.csv     세션마다 VM 속도(120바이트 비교 한 번, ns)
  fig7_round4_lookup.png, fig8_round4_real.png

실행: python3 analysis/analyze_round4.py   (matplotlib 필요)
"""
import csv
import glob
import json
import os
import re

import analyze_round3 as r3

SESSIONS = os.path.join(r3.ROOT, "results", "round4", "sessions")
KERNELS = [("5.4.214-b0", "5.4 원본", "#104281"), ("5.4.214-tail", "5.4 패치", "#eb6834"),
           ("5.4.214-word", "5.4 word", "#3f7fbf"), ("5.4.214-wordtail", "5.4 word+패치", "#c9632f"),
           ("6.18.64-b0", "6.18 원본", "#6f9fd8"), ("6.18.64-tail", "6.18 패치", "#a8461a")]
PAIRS = [("5.4.214-b0", "5.4.214-tail", "5.4 원본→패치"),
         ("5.4.214-word", "5.4.214-wordtail", "5.4 word→word+패치"),
         ("6.18.64-b0", "6.18.64-tail", "6.18 원본→패치")]
EXTRA = [("5.4.214-b0", "5.4.214-word", "5.4 원본→word"),
         ("5.4.214-b0", "5.4.214-wordtail", "5.4 원본→word+패치")]


def write_state(path):
    rows = []
    for p in sorted(glob.glob(os.path.join(SESSIONS, "*"))):
        with open(os.path.join(p, "state.txt")) as f:
            v = [float(x) for x in re.findall(r"len 120: ([\d.]+)", f.read())]
        rows.append([os.path.basename(p)] + ["%.2f" % x for x in v])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session", "start_ns", "lookup_done_ns", "ls_done_ns", "end_ns"])
        w.writerows(rows)
    flat = [float(x) for r in rows for x in r[1:]]
    print("speed check: %d sessions, %.1f~%.1f ns per 120-byte compare" % (len(rows), min(flat), max(flat)))


def check_correctness():
    for p in sorted(glob.glob(os.path.join(SESSIONS, "*", "correctness.json"))):
        with open(p) as f:
            d = json.load(f)
        print(os.path.basename(os.path.dirname(p)), "correctness:",
              {k: v for k, v in d.items() if not isinstance(v, (dict, list))})


def main():
    r3.SESSIONS, r3.KERNELS, r3.COMPARISONS = SESSIONS, KERNELS, PAIRS + EXTRA
    found = r3.sessions()
    data = r3.load(found)
    out = os.path.join(r3.OUT, "summary_round4_change.csv")
    r3.write_change(out, data)
    r3.write_profile(os.path.join(r3.OUT, "summary_round4_profile.csv"), found)
    write_state(os.path.join(r3.OUT, "summary_round4_state.csv"))
    check_correctness()
    r3.COMPARISONS = PAIRS
    r3.figure(os.path.join(r3.OUT, "fig7_round4_lookup.png"), "이름 하나를 찾는 데 걸린 시간 (4차 측정, 정상 속도의 VM)",
              "dentry 캐시를 비운 뒤. word = 5.15의 8바이트 단위 memcmp를 넣은 커널", data, "lookup_us", r3.CASES,
              "warmdir", "µs / 이름")
    r3.figure(os.path.join(r3.OUT, "fig8_round4_real.png"), "실제 프로그램 한 번에 걸린 시간 (4차 측정, 정상 속도의 VM)",
              "dentry 캐시를 비운 직후 실행. 사진 이름 디렉터리와 커널 소스 트리(실제 파일 이름)", data, "real_ms",
              r3.TASKS, "cold", "ms")
    with open(out) as f:
        for r in csv.DictReader(f):
            print(r["measure"], r["case"], r["mode"], r["comparison"], r["base_median"], "->", r["new_median"],
                  r["change_pct"] + "%", "overlap=" + r["session_ranges_overlap"], r["block_changes_pct"])


if __name__ == "__main__":
    main()
