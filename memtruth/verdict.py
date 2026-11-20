"""Turn three numbers into a verdict.

The three numbers are: bytes tracemalloc says the workload peaked at, the
process peak RSS with tracing off, and the process peak RSS with tracing on.
No single one of them is "the" memory cost, and this module says which way
they disagree instead of averaging them into a comfortable middle.
"""

from __future__ import annotations

OVER_REPORT = 1.5     # traced >= 1.5x resident growth
UNDER_REPORT = 0.7    # traced <= 0.7x resident growth
DISTORTION = 1.10     # tracing inflates RSS by >= 10%
MIN_BYTES = 1 << 20   # ignore sub-megabyte noise when flagging distortion
NOISE_FLOOR = 1 << 20 # below 1 MiB, an RSS delta is not a usable denominator


def classify(traced_peak, rss_peak_control, rss_peak_traced,
             rss_final_control=None):
    """Classify the relationship between traced bytes and resident growth.

    ``traced_peak`` may be None (control runs are not traced).  ``rss_peak_*``
    are deltas over the pre-workload RSS baseline.
    """
    if rss_peak_control is None or rss_peak_control <= 0:
        raise ValueError("rss_peak_control must be a positive byte count")

    if traced_peak is None:
        return {
            "agreement": "untraced",
            "traced_to_rss": None,
            "rss_traced_to_control": None,
            "instrument_cost_bytes": None,
            "warning": None,
        }

    if rss_peak_control < NOISE_FLOOR and traced_peak < NOISE_FLOOR:
        return {
            "agreement": "below-noise-floor",
            "traced_to_rss": None,
            "lower_bound_ratio": None,
            "rss_traced_to_control": (
                round(rss_peak_traced / rss_peak_control, 4)
                if rss_peak_traced is not None else None),
            "instrument_cost_bytes": (
                rss_peak_traced - rss_peak_control
                if rss_peak_traced is not None else None),
            "warning": None,
            "retained_fraction": None,
            "noise_floor_bytes": NOISE_FLOOR,
        }

    if rss_peak_control < NOISE_FLOOR:
        # Dividing 64 MiB of traced bytes by a 4 KiB RSS delta produces a
        # spectacular but meaningless multiplier.  Report a lower bound
        # against the noise floor instead, and never the raw quotient.
        return {
            "agreement": "rss-below-noise-floor",
            "traced_to_rss": None,
            "lower_bound_ratio": round(traced_peak / NOISE_FLOOR, 4),
            "rss_traced_to_control": (
                round(rss_peak_traced / rss_peak_control, 4)
                if rss_peak_traced is not None else None),
            "instrument_cost_bytes": (
                rss_peak_traced - rss_peak_control
                if rss_peak_traced is not None else None),
            "warning": None,
            "retained_fraction": None,
            "noise_floor_bytes": NOISE_FLOOR,
        }

    ratio = traced_peak / rss_peak_control
    if ratio >= OVER_REPORT:
        agreement = "over-report"
    elif ratio <= UNDER_REPORT:
        agreement = "under-report"
    else:
        agreement = "agree"

    rss_ratio = (rss_peak_traced / rss_peak_control
                 if rss_peak_traced is not None else None)
    cost = (rss_peak_traced - rss_peak_control
            if rss_peak_traced is not None else None)
    warning = None
    if (cost is not None and rss_ratio is not None and cost >= MIN_BYTES
            and rss_ratio >= DISTORTION):
        warning = ("tracing itself added %.1f MiB (peak RSS x%.2f)"
                   % (cost / 1048576.0, rss_ratio))

    return {
        "agreement": agreement,
        "traced_to_rss": round(ratio, 4),
        "rss_traced_to_control": (round(rss_ratio, 4)
                                  if rss_ratio is not None else None),
        "instrument_cost_bytes": cost,
        "warning": warning,
        "retained_fraction": (
            # VmRSS and VmHWM are both kB-granular, so a final reading may
            # exceed the peak by one page; clamp instead of reporting >1.0.
            round(min(1.0, max(0.0, rss_final_control) / rss_peak_control), 4)
            if rss_final_control is not None else None),
    }


def headline(agreement):
    return {
        "over-report": "tracemalloc counts bytes the OS never made resident",
        "under-report": "memory lives outside Python's traced allocators",
        "agree": "traced bytes track resident growth within 0.7-1.5x",
        "rss-below-noise-floor": "RSS growth is under 1 MiB: only a lower bound is meaningful",
        "below-noise-floor": "both traced bytes and RSS growth are under 1 MiB",
        "untraced": "no tracing was active",
    }[agreement]
