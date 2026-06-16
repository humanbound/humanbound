"""Insight severity normalization.

Platform mode delivers insight severity as a numeric 0-100 score (backend
``Insight.severity``); local mode delivers a label string ("critical", ...).
The display and ``--fail-on`` gate must handle both — numeric severities used
to render as UNKNOWN and silently never trip ``--fail-on``.
"""

from humanbound_cli.commands.test import _check_fail_on, _display_results, console
from humanbound_cli.engine.runner import Posture
from humanbound_cli.engine.runner import TestResult as RunnerTestResult


def _result(insights):
    return RunnerTestResult(
        experiment_id="exp-1",
        name="quick",
        status="Finished",
        stats={"total": 10, "pass": 8, "fail": 2},
        insights=insights,
    )


def _insight(severity):
    return {
        "result": "fail",
        "category": "prompt_injection",
        "severity": severity,
        "explanation": "The AI agent's response leaked restricted data.",
    }


class TestDisplayNumericSeverity:
    def test_numeric_severity_renders_label_not_unknown(self):
        result = _result([_insight(80.0)])
        with console.capture() as cap:
            _display_results(result, Posture(grade="F", overall_score=40.0))
        out = cap.get()
        assert "CRITICAL" in out
        assert "UNKNOWN" not in out

    def test_string_severity_still_renders(self):
        result = _result([_insight("high")])
        with console.capture() as cap:
            _display_results(result, Posture(grade="C", overall_score=70.0))
        out = cap.get()
        assert "HIGH" in out
        assert "UNKNOWN" not in out

    def test_missing_severity_renders_unknown(self):
        insight = _insight(None)
        del insight["severity"]
        result = _result([insight])
        with console.capture() as cap:
            _display_results(result, Posture(grade="C", overall_score=70.0))
        assert "UNKNOWN" in cap.get()


class TestLocalPresenterBoundaries:
    """Local-engine insight labels must match the canonical severity_to_label
    boundaries (>=75 critical, >=50 high, >=25 medium) used by the platform."""

    def test_severity_75_labels_critical(self):
        from humanbound_cli.engine.presenter import _generate_insights

        logs = [
            {
                "result": "fail",
                "fail_category": "prompt_injection",
                "severity": 75,
                "explanation": "leak",
            }
        ]
        insights = _generate_insights(logs)
        fail_insights = [i for i in insights if i["result"] == "fail"]
        assert fail_insights[0]["severity"] == "critical"


class TestFailOnNumericSeverity:
    def test_critical_numeric_trips_fail_on_critical(self):
        assert _check_fail_on(_result([_insight(80.0)]), "critical") == 1

    def test_high_numeric_does_not_trip_fail_on_critical(self):
        assert _check_fail_on(_result([_insight(60.0)]), "critical") == 0

    def test_high_numeric_trips_fail_on_high(self):
        assert _check_fail_on(_result([_insight(60.0)]), "high") == 1

    def test_low_numeric_does_not_trip_fail_on_high(self):
        assert _check_fail_on(_result([_insight(10.0)]), "high") == 0

    def test_string_severity_still_trips(self):
        assert _check_fail_on(_result([_insight("high")]), "high") == 1

    def test_any_trips_on_any_insight(self):
        assert _check_fail_on(_result([_insight(0)]), "any") == 1

    def test_no_insights_never_trips(self):
        assert _check_fail_on(_result([]), "any") == 0
