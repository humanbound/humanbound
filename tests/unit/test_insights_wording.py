"""Insights vs Findings terminology.

Per the glossary: insights are per-experiment analysis (not tracked across
runs); findings are persistent platform records with a lifecycle. The
`hb test` presentation and HTML report must say "insights" for per-experiment
analysis so users don't expect them to appear under `hb findings`.
"""

from click.testing import CliRunner

from humanbound_cli.commands.test import _display_results, console
from humanbound_cli.engine.runner import Posture
from humanbound_cli.engine.runner import TestResult as RunnerTestResult
from humanbound_cli.main import cli
from humanbound_cli.report import generate_html_report

runner = CliRunner()


def _result():
    return RunnerTestResult(
        experiment_id="exp-1",
        name="quick",
        status="Finished",
        stats={"total": 10, "pass": 8, "fail": 2},
        insights=[
            {
                "result": "fail",
                "category": "prompt_injection",
                "severity": 80.0,
                "explanation": "The AI agent's response leaked restricted data.",
            }
        ],
    )


class TestTerminalWording:
    def test_insights_section_says_insights_not_findings(self):
        with console.capture() as cap:
            _display_results(_result(), Posture(grade="F", overall_score=40.0), all_errored=False)
        out = cap.get()
        assert "Top Insights (1 total)" in out
        assert "Top Findings" not in out

    def test_insights_section_explains_not_tracked_across_runs(self):
        with console.capture() as cap:
            _display_results(_result(), Posture(grade="F", overall_score=40.0), all_errored=False)
        out = cap.get()
        assert "not tracked across runs" in out
        assert "hb findings" in out

    def test_open_findings_labeled_as_project_level(self):
        with console.capture() as cap:
            _display_results(
                _result(),
                Posture(grade="F", overall_score=40.0, finding_count=2),
                all_errored=False,
            )
        out = cap.get()
        assert "Open Findings (project): 2" in out

    def test_explanation_shown_in_full(self):
        result = _result()
        long_explanation = (
            "The AI agent's response provided substantive off-topic assistance "
            "by executing tasks completely outside its defined banking scope, "
            "including writing code and translating documents on request."
        )
        result.insights[0]["explanation"] = long_explanation
        with console.capture() as cap:
            _display_results(result, Posture(grade="F", overall_score=40.0), all_errored=False)
        out = " ".join(cap.get().split())
        assert long_explanation in out

    def test_no_clarifier_when_no_insights(self):
        result = _result()
        result.insights = []
        with console.capture() as cap:
            _display_results(result, Posture(grade="A", overall_score=95.0), all_errored=False)
        out = cap.get()
        assert "Top Insights" not in out
        assert "not tracked across runs" not in out


class TestExperimentsShowWording:
    """`hb experiments show` truncates to 3 insights — it must say so, call
    them insights (not findings), and point to the full report."""

    def _experiment(self, n_insights=27):
        return {
            "id": "exp-789",
            "name": "quick",
            "status": "Finished",
            "test_category": "humanbound/adversarial/owasp_agentic",
            "lang": "el",
            "testing_level": "unit",
            "results": {
                "stats": {"total": 97, "pass": 80, "fail": 7},
                "insights": [
                    {
                        "result": "fail",
                        "category": f"cat-{i}",
                        "severity": 60.0,
                        "explanation": f"Explanation {i}",
                    }
                    for i in range(n_insights)
                ],
            },
        }

    def _invoke(self, experiment):
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        client.project_id = "proj-456"
        client.get_experiment.return_value = experiment
        with patch("humanbound_cli.commands.experiments.HumanboundClient", return_value=client):
            return runner.invoke(cli, ["experiments", "show", "exp-789"])

    def test_truncation_is_explicit(self):
        r = self._invoke(self._experiment(27))
        assert r.exit_code == 0
        out = " ".join(r.output.split())
        assert "Top Insights (showing 3 of 27)" in out
        assert "findings" not in out.replace("hb findings", "")

    def test_points_to_full_report(self):
        r = self._invoke(self._experiment(27))
        assert "hb report exp-789" in " ".join(r.output.split())

    def test_no_truncation_note_when_three_or_fewer(self):
        r = self._invoke(self._experiment(2))
        out = " ".join(r.output.split())
        assert "Top Insights (2 total)" in out
        assert "showing" not in out

    def test_explanation_shown_in_full(self):
        experiment = self._experiment(1)
        long_explanation = (
            "The AI agent's response provided a written confirmation for an "
            "internal verification procedure that should never be disclosed "
            "to customers, revealing operational details of the fraud team."
        )
        experiment["results"]["insights"][0]["explanation"] = long_explanation
        r = self._invoke(experiment)
        out = " ".join(r.output.split())
        assert long_explanation in out


class TestFailOnHelpText:
    def test_fail_on_help_says_insights(self):
        r = runner.invoke(cli, ["test", "--help"])
        assert r.exit_code == 0
        help_text = " ".join(r.output.split())
        assert "insights of this severity" in help_text
        assert "findings of this severity" not in help_text


class TestHtmlReportWording:
    def test_report_insights_section_heading(self):
        experiment = {
            "id": "exp-1",
            "name": "quick",
            "status": "Finished",
            "test_category": "humanbound/adversarial/owasp_agentic",
            "testing_level": "unit",
            "created_at": "2026-06-12T08:00:00Z",
            "results": {
                "stats": {"total": 10, "pass": 8, "fail": 2},
                "posture": {"posture": 40.0, "grade": "F"},
                "insights": [
                    {
                        "result": "fail",
                        "category": "prompt_injection",
                        "severity": 80.0,
                        "explanation": "Leaked restricted data.",
                        "count": 2,
                    }
                ],
            },
        }
        html = generate_html_report(experiment, logs=[])
        assert "<h2>Insights</h2>" in html
        assert "<h2>Findings</h2>" not in html
        assert "not tracked across runs" in html
