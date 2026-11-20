"""Aggregation: medians and quartiles over isolated run records."""

from __future__ import annotations

from . import verdict

FIELDS = ("rss_peak_delta", "rss_final_delta", "traced_peak", "traced_cur")


def percentile(values, q):
    """Linear-interpolated percentile (q in 0..100) over a non-empty list."""
    data = sorted(values)
    if not data:
        raise ValueError("percentile of empty sequence")
    if not 0 <= q <= 100:
        raise ValueError("q must be within 0..100")
    if len(data) == 1:
        return float(data[0])
    pos = (len(data) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return float(data[lo]) * (1.0 - frac) + float(data[hi]) * frac


def summarize(records):
    """Group records by (workload, mode) and reduce each field to p25/median/p75."""
    groups = {}
    for rec in records:
        groups.setdefault((rec["workload"], rec["mode"]), []).append(rec)

    summary = {}
    for (name, mode), recs in sorted(groups.items()):
        entry = {"mode": mode, "runs": len(recs)}
        for field in FIELDS:
            vals = [r[field] for r in recs if r.get(field) is not None]
            if not vals:
                entry[field] = None
                continue
            entry[field] = {
                "median": percentile(vals, 50),
                "p25": percentile(vals, 25),
                "p75": percentile(vals, 75),
            }
        summary.setdefault(name, {})[mode] = entry
    return summary


def rows(summary):
    """Join control and traced summaries into one verdict row per workload."""
    out = []
    for name, modes in summary.items():
        ctl = modes.get("control")
        tr = modes.get("traced")
        if not ctl or not tr:
            continue
        rss_control = ctl["rss_peak_delta"]["median"]
        rss_traced = tr["rss_peak_delta"]["median"]
        v = verdict.classify(
            tr["traced_peak"]["median"] if tr.get("traced_peak") else None,
            rss_control,
            rss_traced,
            ctl["rss_final_delta"]["median"],
        )
        out.append({
            "workload": name,
            "traced_peak": tr["traced_peak"]["median"] if tr.get("traced_peak") else None,
            "traced_p25": tr["traced_peak"]["p25"] if tr.get("traced_peak") else None,
            "traced_p75": tr["traced_peak"]["p75"] if tr.get("traced_peak") else None,
            "rss_control": rss_control,
            "rss_control_p25": ctl["rss_peak_delta"]["p25"],
            "rss_control_p75": ctl["rss_peak_delta"]["p75"],
            "rss_traced": rss_traced,
            "rss_traced_p25": tr["rss_peak_delta"]["p25"],
            "rss_traced_p75": tr["rss_peak_delta"]["p75"],
            "retained_control": ctl["rss_final_delta"]["median"],
            "verdict": v,
        })
    return out


def mib(value):
    return "n/a" if value is None else "%.1f" % (value / 1048576.0)


def to_markdown(table):
    lines = [
        "| workload | traced peak | RSS peak (off) | RSS peak (on) | traced/RSS | verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in table:
        v = row["verdict"]
        if v["agreement"] == "rss-below-noise-floor" and v.get("lower_bound_ratio"):
            ratio = ">=%.0fx" % v["lower_bound_ratio"]
        else:
            ratio = "n/a" if v["traced_to_rss"] is None else "%.2fx" % v["traced_to_rss"]
        lines.append("| `%s` | %s MiB | %s MiB | %s MiB | %s | %s |" % (
            row["workload"], mib(row["traced_peak"]), mib(row["rss_control"]),
            mib(row["rss_traced"]), ratio, v["agreement"]))
    return "\n".join(lines)
