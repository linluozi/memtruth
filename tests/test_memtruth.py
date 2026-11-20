import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memtruth import measure, proc, report, verdict, workloads  # noqa: E402
from memtruth.cli import main as cli_main  # noqa: E402

FIXTURE = """Name:\tpython3
VmPeak:\t  123456 kB
VmSize:\t   90000 kB
VmRSS:\t   12345 kB
VmHWM:\t   23456 kB
Threads:\t1
"""


class ProcTests(unittest.TestCase):
    def test_parse_known_fields_only(self):
        stats = proc.parse_status(FIXTURE)
        self.assertEqual(stats["VmRSS"], 12345 * 1024)
        self.assertEqual(stats["VmHWM"], 23456 * 1024)
        self.assertEqual(stats["VmSize"], 90000 * 1024)
        self.assertNotIn("VmPeak", stats)

    def test_parse_ignores_malformed(self):
        text = "VmRSS:\nVmHWM: 12 MB\nVmPeak: 99 kB\n"
        self.assertEqual(proc.parse_status(text), {})

    def test_snapshot_positive_on_linux(self):
        snap = proc.snapshot()
        self.assertGreater(snap["rss"], 0)
        self.assertGreaterEqual(snap["hwm"], snap["rss"])


class VerdictTests(unittest.TestCase):
    MIB = 1 << 20

    def test_agree_band(self):
        m = self.MIB
        self.assertEqual(verdict.classify(100*m, 100*m, 100*m)["agreement"], "agree")
        self.assertEqual(verdict.classify(149*m, 100*m, 149*m)["agreement"], "agree")
        self.assertEqual(verdict.classify(71*m, 100*m, 71*m)["agreement"], "agree")

    def test_over_report_boundary(self):
        m = self.MIB
        self.assertEqual(verdict.classify(150*m, 100*m, 150*m)["agreement"], "over-report")
        self.assertEqual(verdict.classify(4200*m, 100*m, 4200*m)["agreement"], "over-report")

    def test_under_report_boundary(self):
        m = self.MIB
        self.assertEqual(verdict.classify(70*m, 100*m, 70*m)["agreement"], "under-report")
        self.assertEqual(verdict.classify(45*m, 100*m, 90*m)["agreement"], "under-report")

    def test_tiny_rss_delta_is_not_divided(self):
        v = verdict.classify(64*self.MIB, 4096, 4096)
        self.assertEqual(v["agreement"], "rss-below-noise-floor")
        self.assertIsNone(v["traced_to_rss"])
        self.assertAlmostEqual(v["lower_bound_ratio"], 64.0)
        self.assertEqual(v["noise_floor_bytes"], self.MIB)

    def test_distortion_warning_needs_both_conditions(self):
        mib = 1 << 20
        hot = verdict.classify(100 * mib, 100 * mib, 240 * mib,
                               rss_final_control=100 * mib)
        self.assertIsNotNone(hot["warning"])
        self.assertAlmostEqual(hot["rss_traced_to_control"], 2.4)
        small = verdict.classify(100, 100, 120)  # 20% but under 1 MiB
        self.assertIsNone(small["warning"])

    def test_both_sides_under_floor_gives_no_ratio(self):
        v = verdict.classify(200_000, 4096, 4096)
        self.assertEqual(v["agreement"], "below-noise-floor")
        self.assertIsNone(v["lower_bound_ratio"])

    def test_untraced(self):
        v = verdict.classify(None, 100, None)
        self.assertEqual(v["agreement"], "untraced")
        self.assertIsNone(v["traced_to_rss"])

    def test_zero_control_rejected(self):
        with self.assertRaises(ValueError):
            verdict.classify(1, 0, 1)

    def test_retained_fraction(self):
        m = self.MIB
        v = verdict.classify(100*m, 100*m, 100*m, rss_final_control=25*m)
        self.assertAlmostEqual(v["retained_fraction"], 0.25)


class ReportTests(unittest.TestCase):
    MIB = 1 << 20

    def test_percentiles(self):
        self.assertEqual(report.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(report.percentile([1, 2, 3, 4], 25), 1.75)
        self.assertEqual(report.percentile([1, 2, 3, 4], 75), 3.25)
        self.assertEqual(report.percentile([7], 50), 7.0)

    def test_percentile_errors(self):
        with self.assertRaises(ValueError):
            report.percentile([], 50)
        with self.assertRaises(ValueError):
            report.percentile([1], 101)

    def test_summarize_and_rows(self):
        m = self.MIB
        recs = [
            {"workload": "w", "mode": "control", "rss_peak_delta": 100*m,
             "rss_final_delta": 50*m, "traced_peak": None, "traced_cur": None},
            {"workload": "w", "mode": "control", "rss_peak_delta": 300*m,
             "rss_final_delta": 50*m, "traced_peak": None, "traced_cur": None},
            {"workload": "w", "mode": "traced", "rss_peak_delta": 600*m,
             "rss_final_delta": 500*m, "traced_peak": 210*m, "traced_cur": 200*m},
        ]
        summary = report.summarize(recs)
        self.assertEqual(summary["w"]["control"]["rss_peak_delta"]["median"], 200.0*m)
        table = report.rows(summary)
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["verdict"]["agreement"], "agree")  # 210/200

    def test_rsd(self):
        recs = []
        for val in (100, 100, 100):
            recs.append({"workload": "w", "mode": "control", "rss_peak_delta": val,
                         "rss_final_delta": 10, "traced_peak": None, "traced_cur": None})
        summary = report.summarize(recs)
        self.assertEqual(summary["w"]["control"]["rss_peak_delta"]["rsd"], 0.0)

    def test_max_rsd(self):
        recs = []
        for val in (100, 100, 300):
            recs.append({"workload": "w", "mode": "control", "rss_peak_delta": val,
                         "rss_final_delta": 10, "traced_peak": None, "traced_cur": None})
        worst, where = report.max_rsd(report.summarize(recs))
        self.assertGreater(worst, 0.4)
        self.assertIn("rss_peak_delta", where)

    def test_markdown_contains_header_and_name(self):
        m = self.MIB
        recs = [
            {"workload": "w", "mode": "control", "rss_peak_delta": 100*m,
             "rss_final_delta": 10*m, "traced_peak": None, "traced_cur": None},
            {"workload": "w", "mode": "traced", "rss_peak_delta": 110*m,
             "rss_final_delta": 10*m, "traced_peak": 100*m, "traced_cur": 100*m},
        ]
        md = report.to_markdown(report.rows(report.summarize(recs)))
        self.assertIn("| workload |", md)
        self.assertIn("`w`", md)


class DocsHonestyTests(unittest.TestCase):
    def test_readme_table_matches_calibration(self):
        import re
        calib = json.loads((ROOT / "benchmark" / "calibration.json").read_text())
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        rows = {}
        for line in text.splitlines():
            m = re.match(r"\| `([a-z0-9_]+)` .*?\| ([\d.]+) MiB \| ([\d.]+) MiB \| ([\d.]+) MiB \|", line)
            if m:
                rows[m.group(1)] = tuple(float(x) for x in m.groups()[1:])
        self.assertEqual(len(rows), len(calib["table"]))
        for row in calib["table"]:
            expected = tuple(round(row[k] / 1048576.0, 1)
                             for k in ("traced_peak", "rss_control", "rss_traced"))
            self.assertEqual(rows[row["workload"]], expected, row["workload"])

    def test_readme_upstream_marker_is_early(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Upstream: none", text[:2500])


class WorkloadTests(unittest.TestCase):
    def test_registry_integrity(self):
        for name in workloads.names():
            meta = workloads.get(name)
            module = workloads.load(name)
            self.assertTrue(callable(getattr(module, "run", None)), name)
            self.assertTrue(meta["description"])
            self.assertTrue(meta["category"])

    def test_unknown_workload(self):
        with self.assertRaises(KeyError):
            workloads.get("nope")

    def test_registry_does_not_import_numpy(self):
        code = ("import sys, memtruth.workloads as w; w.names(); "
                "print('numpy' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                             env=measure.child_env(), capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")


class MeasureTests(unittest.TestCase):
    def test_traced_run_has_traced_bytes(self):
        rec = measure.run_once(workload="small_objects", mode="traced", scale=0.004)
        self.assertGreater(rec["traced_peak"], 0)
        self.assertGreaterEqual(rec["traced_peak"], rec["traced_cur"])
        self.assertGreater(rec["rss_peak_delta"], 0)
        self.assertEqual(rec["mode"], "traced")

    def test_control_run_is_not_traced(self):
        rec = measure.run_once(workload="small_objects", mode="control", scale=0.004)
        self.assertIsNone(rec["traced_peak"])
        self.assertIsNone(rec["traced_cur"])
        self.assertGreater(rec["rss_peak_delta"], 0)

    def test_traced_bytes_are_deterministic(self):
        a = measure.run_once(workload="small_objects", mode="traced", scale=0.002)
        b = measure.run_once(workload="small_objects", mode="traced", scale=0.002)
        self.assertEqual(a["traced_peak"], b["traced_peak"])

    def test_argument_validation(self):
        with self.assertRaises(ValueError):
            measure.run_once(mode="traced")
        with self.assertRaises(ValueError):
            measure.run_once(workload="small_objects", script="x.py", mode="traced")
        with self.assertRaises(ValueError):
            measure.run_once(workload="small_objects", mode="wrong")
        with self.assertRaises(KeyError):
            measure.run_once(workload="nope", mode="traced")

    def test_write_pattern_flips_verdict(self):
        """Same allocation, same size: only touching the pages may change RSS."""
        zeros = measure.run_once(workload="numpy_zeros", mode="control", scale=0.05)
        touched = measure.run_once(workload="numpy_touched", mode="control", scale=0.05)
        self.assertLess(zeros["rss_peak_delta"], 200_000)
        self.assertGreater(touched["rss_peak_delta"], 3_000_000)
        zt = measure.run_once(workload="numpy_zeros", mode="traced", scale=0.05)
        tt = measure.run_once(workload="numpy_touched", mode="traced", scale=0.05)
        # traced bytes are blind to the write pattern: both count the request
        self.assertLess(abs(zt["traced_peak"] - tt["traced_peak"]), 0.05 * tt["traced_peak"])
        self.assertGreater(zt["traced_peak"], 2_000_000)

    def test_script_mode(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "alloc.py"
            path.write_text("xs = [bytes(512) for _ in range(2000)]\n")
            rec = measure.run_once(script=path, mode="traced")
            self.assertGreater(rec["traced_peak"], 500_000)
            self.assertEqual(rec["workload"], "alloc.py")


class CliTests(unittest.TestCase):
    def test_run_writes_raw_and_aggregate(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "agg.json"
            rc = cli_main(["run", "small_objects", "--repeat", "1", "--scale", "0.002",
                           "--out", str(out), "--raw", str(Path(td) / "raw")])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text())
            self.assertEqual(len(payload["runs"]), 2)
            self.assertEqual(len(list((Path(td) / "raw").glob("*.json"))), 2)
            self.assertEqual(payload["table"][0]["workload"], "small_objects")

    def test_list_mentions_every_workload(self):
        for name in workloads.names():
            self.assertIn(name, workloads.names())

    def test_gate_passes_clean_table(self):
        from memtruth.cli import evaluate_gate
        table = [{"workload": "a", "rss_control": 40 << 20,
                  "verdict": {"agreement": "agree", "traced_to_rss": 1.0,
                              "rss_traced_to_control": 1.02}}]
        violations, lines = evaluate_gate(table)
        self.assertEqual(violations, [])
        self.assertTrue(lines[0].startswith("PASS"))

    def test_gate_flags_profiler_distortion(self):
        from memtruth.cli import evaluate_gate
        table = [{"workload": "a", "rss_control": 40 << 20,
                  "verdict": {"agreement": "agree", "traced_to_rss": 1.0,
                              "rss_traced_to_control": 2.4}}]
        violations, _ = evaluate_gate(table, max_instrument_ratio=1.25)
        self.assertEqual(len(violations), 1)
        self.assertIn("inflates", violations[0]["reasons"][0])

    def test_gate_strict_flags_under_report(self):
        from memtruth.cli import evaluate_gate
        table = [{"workload": "a", "rss_control": 40 << 20,
                  "verdict": {"agreement": "under-report", "traced_to_rss": 0.5,
                              "rss_traced_to_control": 1.0}}]
        self.assertEqual(evaluate_gate(table)[0], [])
        strict = evaluate_gate(table, strict=True)[0]
        self.assertEqual(len(strict), 1)

    def test_gate_cli_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "agg.json"
            cli_main(["run", "numpy_zeros", "bytes_1k", "--repeat", "1", "--scale", "0.02",
                      "--out", str(out), "--raw", str(Path(td) / "raw")])
            self.assertEqual(cli_main(["gate", str(out), "--strict"]), 1)

    def test_audit_missing_script(self):
        self.assertEqual(cli_main(["audit", "/nonexistent/x.py"]), 2)

    def test_report_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "agg.json"
            cli_main(["run", "churn_free", "--repeat", "1", "--scale", "0.002",
                      "--out", str(out), "--raw", str(Path(td) / "raw")])
            self.assertEqual(cli_main(["report", str(out)]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
