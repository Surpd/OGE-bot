"""Produce full stratified metrics and paired comparisons from raw cumulative counters."""

import argparse
import csv
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

from simulate import HERE, POLICIES

RATIOS = dict(
    transfer_after_help=("transfer_after_help_yes", "transfer_after_help_n"),
    delayed_probe=("probe_yes", "probe_n"),
    delayed_probe_confirmed=("probe_confirmed_yes", "probe_confirmed_n"),
    gap_precision=("true_gap", "gaps"),
    gap_recall=("weak_found", "weak_truth"),
    false_closure_rate=("false_close", "closed"),
    fresh_accuracy=("new_correct", "unaided"),
    late_accuracy=("retention_yes", "retention_n"),
    session_completion=("complete", "sessions"),
    familiar_rate=("familiar", "offers"),
    help_rate=("assisted", "offers"),
    gap_delay=("latency_gap_sum", "latency_gap_n"),
    closure_day=("latency_award_sum", "latency_award_n"),
    seconds_per_session=("seconds", "sessions"),
)
MEANS = (
    "mastered",
    "latent_mean",
    "award",
    "due",
    "distinct_families",
    "offers",
    "gaps",
    "closed",
    "assisted",
    "hint_success",
)


def summarize(rows):
    out = {"n": len(rows)}
    for f in MEANS:
        out[f] = st.mean(r[f] for r in rows)
    for f, (a, b) in RATIOS.items():
        denom = sum(r[b] for r in rows)
        out[f] = sum(r[a] for r in rows) / denom if denom else None
        out[f + "_n"] = denom
    return out


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def graph(path, table):
    colors = ["#184d66", "#c05e27", "#4f7965"]
    strings = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="510" viewBox="0 0 900 510">',
        '<rect width="900" height="510" fill="#fff"/>',
        '<g font-family="Arial" fill="#18252c"><text x="45" y="38" font-size="23">'
        'День 90 · базовый сценарий</text>',
        '<text x="45" y="66" font-size="15">Ложные подтверждения '
        'среди новых переходов в confirmed, %</text>',
    ]
    for i, policy in enumerate(POLICIES):
        strings.append(
            f'<rect x="{70 + i * 200}" y="85" width="15" height="15" fill="{colors[i]}"/>'
            f'<text x="{92 + i * 200}" y="98">{policy}</text>'
        )
    for y in range(0, 101, 20):
        py = 425 - 3 * y
        strings.append(
            f'<path d="M 65 {py} H 865" stroke="#dedede"/><text x="25" y="{py + 5}">{y}</text>'
        )
    for j, profile in enumerate("ABCDEFGHIJ"):
        left = 75 + j * 79
        for i, policy in enumerate(POLICIES):
            rate = table["base", 90, profile, policy]["false_closure_rate"]
            if rate is not None:
                h = 300 * rate
                strings.append(
                    f'<rect x="{left + 17 * i}" y="{425 - h:.2f}" height="{h:.2f}" '
                    f'width="15" fill="{colors[i]}"/>'
                )
        strings.append(f'<text x="{left + 19}" y="454" font-size="16">{profile}</text>')
    strings.append(
        '<text x="65" y="490">Истинный порог в модели — 0,75. '
        'Профили A–J описаны в README.</text></g></svg>'
    )
    path.write_text("\n".join(strings), encoding="utf8")


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--dir", type=Path, default=HERE / "results")
    dest = cli.parse_args().dir
    groups = defaultdict(list)
    with (dest / "runs.csv").open(encoding="utf8") as f:
        for row in csv.DictReader(f):
            r = {
                k: (v if k in ("profile", "policy", "setting") else float(v))
                for k, v in row.items()
            }
            key = (r["setting"], int(r["day"]), r["profile"], r["policy"])
            groups[key].append(r)
            groups[(key[0], key[1], "ALL", key[3])].append(r)
    table = {k: summarize(rs) for k, rs in groups.items()}
    records = [
        dict(setting=k[0], day=k[1], profile=k[2], policy=k[3], **r)
        for k, r in sorted(table.items())
    ]
    write_csv(dest / "summary.csv", records)
    pairs = []
    for (setting, day, profile, policy), rows in groups.items():
        if policy == "rules":
            continue
        baseline = {(r["seed"], r["profile"]): r for r in groups[setting, day, profile, "rules"]}
        for field in (
            "award",
            "mastered",
            "latent_mean",
            "false_close",
            "closed",
            "gaps",
            "probe_yes",
        ):
            delta = [r[field] - baseline[r["seed"], r["profile"]][field] for r in rows]
            mean = st.mean(delta)
            se = st.stdev(delta) / math.sqrt(len(delta)) if len(delta) > 1 else 0.0
            pairs.append(
                dict(
                    setting=setting,
                    day=day,
                    profile=profile,
                    against_rules=policy,
                    metric=field,
                    mean_difference=mean,
                    mc_low=mean - 1.96 * se,
                    mc_high=mean + 1.96 * se,
                )
            )
    write_csv(dest / "paired.csv", pairs)
    graph(dest / "false-closures.svg", table)
    for k in ("base", "slow_fastforget", "fast_slowforget", "low_attendance"):
        for policy in POLICIES:
            s = table[k, 90, "ALL", policy]
            print(
                k,
                policy,
                *[
                    round(s[f], 3)
                    for f in (
                        "award",
                        "mastered",
                        "false_closure_rate",
                        "gap_precision",
                        "gap_recall",
                        "fresh_accuracy",
                        "late_accuracy",
                        "session_completion",
                    )
                ],
            )
    for p in "ABCDEFGHIJ":
        s = table["base", 90, p, "rules"]
        print(
            p,
            *[
                round(s[f], 3) if s[f] is not None else "-"
                for f in (
                    "award",
                    "mastered",
                    "false_closure_rate",
                    "gap_precision",
                    "gap_recall",
                    "fresh_accuracy",
                    "session_completion",
                    "due",
                )
            ],
        )


if __name__ == "__main__":
    main()
