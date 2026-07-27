# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Consolidated tests for the telemetry stack.

Covers:
  - baseline properties (humanbound_cli.telemetry.client.baseline)
  - consent decision matrix + state file (humanbound_cli.telemetry.consent)
  - PostHog wrapper (humanbound_cli.telemetry.client)
  - `hb telemetry` command
  - install event semantics + first-run notice (humanbound_cli.main)
  - per-command event call sites
"""

import json
import re
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from humanbound_cli import main as main_module
from humanbound_cli import telemetry as telemetry_pkg
from humanbound_cli.commands.telemetry import telemetry_group
from humanbound_cli.telemetry import client, consent

_ENV_VARS_TO_STRIP = (
    "DO_NOT_TRACK",
    "HB_TELEMETRY_DISABLED",
    "CI",
    "GITHUB_ACTIONS",
    "BUILDKITE",
    "JENKINS_HOME",
    "TF_BUILD",
    "GITLAB_CI",
    "CIRCLECI",
    "TRAVIS",
    "HUMANBOUND_DEV",
    "HB_POSTHOG_KEY",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Strip telemetry-relevant env vars, point HOME at tmp_path, force TTY,
    and reset cached state on both consent and client modules."""
    for v in _ENV_VARS_TO_STRIP:
        monkeypatch.delenv(v, raising=False)
    # Dead port: an unmocked send must never reach the real PostHog host.
    monkeypatch.setenv("HB_POSTHOG_HOST", "http://127.0.0.1:9")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    # Test suite runs from source; force non-editable so telemetry isn't auto-disabled.
    monkeypatch.setattr(consent, "_is_editable_install", lambda: False)
    consent.reset_cache()
    client.reset_for_tests()
    yield
    consent.reset_cache()
    client.reset_for_tests()


@pytest.fixture
def mock_posthog(monkeypatch):
    """Replace the bound `_posthog` module with a MagicMock."""
    m = MagicMock()
    monkeypatch.setattr("humanbound_cli.telemetry.client._posthog", m)
    return m


def _telemetry_file(tmp_home: Path) -> Path:
    return tmp_home / ".humanbound" / "telemetry.json"


def _read_state(tmp_home: Path) -> dict:
    f = _telemetry_file(tmp_home)
    if not f.exists():
        return {}
    return json.loads(f.read_text())


def _write_state(tmp_home: Path, state: dict) -> None:
    f = _telemetry_file(tmp_home)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state))


# === Section 1 — Baseline properties ===


def test_baseline_contains_hb_version():
    props = client.baseline(is_authenticated=False)
    assert isinstance(props["hb_version"], str)
    assert props["hb_version"]
    assert "." in props["hb_version"]


def test_baseline_is_authenticated_passes_through():
    assert client.baseline(is_authenticated=True)["is_authenticated"] is True
    assert client.baseline(is_authenticated=False)["is_authenticated"] is False


def test_baseline_tags_source_as_cli():
    # Every event ships with source="cli" so PostHog can distinguish CLI
    # events from Platform events when both feed the same project.
    assert client.baseline(is_authenticated=False)["source"] == "cli"


def test_baseline_does_not_duplicate_posthog_auto_props():
    """Regression guard: os, os_version, python_version, environment were
    all removed. posthog-python auto-attaches `$os`, `$python_version`, etc.
    on every event, so duplicating them adds noise."""
    props = client.baseline(is_authenticated=False)
    for k in ("os", "os_version", "python_version", "environment"):
        assert k not in props, f"unexpected baseline key: {k}"


# === Section 2 — Consent (env-var disable matrix) ===


def test_consent_enabled_on_clean_machine():
    assert consent.is_enabled() is True


def test_consent_disabled_by_do_not_track(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert consent.is_enabled() is False
    assert "DO_NOT_TRACK" in consent.disabled_reason()


def test_consent_disabled_by_hb_telemetry_disabled(monkeypatch):
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    assert consent.is_enabled() is False
    assert "HB_TELEMETRY_DISABLED" in consent.disabled_reason()


@pytest.mark.parametrize(
    "var",
    [
        "CI",
        "GITHUB_ACTIONS",
        "BUILDKITE",
        "JENKINS_HOME",
        "TF_BUILD",
        "GITLAB_CI",
        "CIRCLECI",
        "TRAVIS",
    ],
)
def test_consent_disabled_in_ci(monkeypatch, var):
    monkeypatch.setenv(var, "true")
    assert consent.is_enabled() is False
    assert var in consent.disabled_reason()


def test_consent_disabled_in_dev_mode(monkeypatch):
    monkeypatch.setenv("HUMANBOUND_DEV", "1")
    assert consent.is_enabled() is False
    assert "dev mode" in consent.disabled_reason()


def test_consent_disabled_in_editable_install(monkeypatch):
    monkeypatch.setattr(consent, "_is_editable_install", lambda: True)
    assert consent.is_enabled() is False
    assert "editable" in consent.disabled_reason()


def test_consent_disabled_when_not_tty(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert consent.is_enabled() is False
    assert "non-TTY" in consent.disabled_reason()


def test_consent_decision_is_cached(monkeypatch):
    assert consent.is_enabled() is True
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    # Cached: still enabled until reset
    assert consent.is_enabled() is True
    consent.reset_cache()
    assert consent.is_enabled() is False


def test_consent_first_match_wins(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("CI", "true")
    assert "DO_NOT_TRACK" in consent.disabled_reason()


# === Section 3 — Consent (state file) ===


def test_state_file_created_on_first_call(tmp_path):
    f = _telemetry_file(tmp_path)
    assert not f.exists()

    did, was_new = consent.get_distinct_id_and_new_flag()

    assert was_new is True
    assert did.startswith("tlm_")
    assert re.match(r"^tlm_[0-9a-f-]{36}$", did)
    assert f.exists()
    state = _read_state(tmp_path)
    assert state == {"id": did, "opted_out": False}
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_state_file_existing_uuid_returned_unchanged(tmp_path):
    _write_state(tmp_path, {"id": "tlm_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "opted_out": False})

    did, was_new = consent.get_distinct_id_and_new_flag()

    assert did == "tlm_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert was_new is False


def test_opted_out_flag_disables_telemetry(tmp_path):
    _write_state(tmp_path, {"id": "tlm_x", "opted_out": True})

    consent.reset_cache()
    assert consent.is_enabled() is False
    assert "opt-out" in consent.disabled_reason()


def test_write_opt_out_persists_and_sets_flag(tmp_path):
    consent.write_opt_out()
    consent.reset_cache()
    state = _read_state(tmp_path)
    assert state.get("opted_out") is True
    assert state.get("id", "").startswith("tlm_")
    assert consent.is_enabled() is False


def test_clear_opt_out_unsets_flag(tmp_path):
    _write_state(tmp_path, {"id": "tlm_existing", "opted_out": True})

    consent.clear_opt_out()
    state = _read_state(tmp_path)
    assert state == {"id": "tlm_existing", "opted_out": False}


def test_reenable_cycle_preserves_uuid(tmp_path):
    """Disable→enable cycle must keep the same anonymous UUID — matches
    industry default (VS Code, npm, PostHog SDK, etc.) and prevents phantom
    `install` events on re-enable."""
    did1, was_new1 = consent.get_distinct_id_and_new_flag()
    consent.write_opt_out()
    consent.reset_cache()
    consent.clear_opt_out()
    consent.reset_cache()
    did2, was_new2 = consent.get_distinct_id_and_new_flag()
    assert was_new1 is True
    assert was_new2 is False
    assert did2 == did1


# === Section 4 — Client (PostHog wrapper) ===


def test_capture_when_enabled_invokes_posthog(mock_posthog):
    client.capture("posture_view", {"is_local": True})

    assert mock_posthog.capture.call_count == 1
    call = mock_posthog.capture.call_args
    assert call.kwargs["distinct_id"].startswith("tlm_")
    assert call.kwargs["event"] == "posture_view"
    props = call.kwargs["properties"]
    assert props["is_local"] is True
    assert "hb_version" in props
    assert props["source"] == "cli"
    assert props["is_authenticated"] is False


def test_capture_when_disabled_does_not_invoke_posthog(monkeypatch, mock_posthog):
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    consent.reset_cache()
    client.capture("posture_view", {"is_local": True})
    mock_posthog.capture.assert_not_called()


def test_capture_swallows_exceptions(mock_posthog):
    mock_posthog.capture.side_effect = RuntimeError("network down")
    # Must not raise
    client.capture("posture_view", {"is_local": True})


def test_capture_accepts_none_properties(mock_posthog):
    client.capture("install")
    assert mock_posthog.capture.call_count == 1
    props = mock_posthog.capture.call_args.kwargs["properties"]
    assert "hb_version" in props


def test_identify_aliases_anonymous_id_to_user_id(mock_posthog):
    client.capture("install")
    anonymous_id = mock_posthog.capture.call_args.kwargs["distinct_id"]
    mock_posthog.reset_mock()

    client.identify("auth0|user123")

    assert mock_posthog.alias.call_count == 1
    alias_call = mock_posthog.alias.call_args
    assert alias_call.kwargs["previous_id"] == anonymous_id
    assert alias_call.kwargs["distinct_id"] == "auth0|user123"


def test_capture_after_identify_uses_user_id(mock_posthog):
    client.identify("auth0|user123")
    mock_posthog.reset_mock()

    client.capture("test_start", {"test_level": "unit"})

    call = mock_posthog.capture.call_args
    assert call.kwargs["distinct_id"] == "auth0|user123"
    assert call.kwargs["properties"]["is_authenticated"] is True


def test_identify_when_disabled_does_not_invoke_alias(monkeypatch, mock_posthog):
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    consent.reset_cache()
    client.identify("auth0|user123")
    mock_posthog.alias.assert_not_called()


def test_identify_swallows_exceptions(mock_posthog):
    mock_posthog.alias.side_effect = RuntimeError("boom")
    # Must not raise
    client.identify("auth0|user123")


def _write_credentials_with_user_id(tmp_path: Path, user_id: str | None) -> None:
    """Write a fake credentials.json whose api_token JWT carries `user_id` in
    the custom claim. Pass user_id=None to write a token with no claim."""
    import base64 as _b64
    import json as _json

    claims = {"sub": "m2m-app-id"}
    if user_id is not None:
        claims["https://aiandme.io/user_id"] = user_id
    payload = _b64.urlsafe_b64encode(_json.dumps(claims).encode()).rstrip(b"=").decode()
    fake_jwt = f"header.{payload}.sig"
    creds = tmp_path / ".humanbound" / "credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text(_json.dumps({"api_token": fake_jwt}))


def _write_credentials_with_user_id_and_email(
    tmp_path: Path, user_id: str, email: str | None
) -> None:
    """Fake credentials.json with a user_id-claim JWT plus a top-level email."""
    import base64 as _b64
    import json as _json

    claims = {"sub": "m2m-app-id", "https://aiandme.io/user_id": user_id}
    payload = _b64.urlsafe_b64encode(_json.dumps(claims).encode()).rstrip(b"=").decode()
    fake_jwt = f"header.{payload}.sig"
    creds = tmp_path / ".humanbound" / "credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    doc = {"api_token": fake_jwt}
    if email is not None:
        doc["email"] = email
    creds.write_text(_json.dumps(doc))


def test_identify_from_credentials_reads_user_id_claim(tmp_path, mock_posthog):
    _write_credentials_with_user_id(tmp_path, "auth0|user123")
    client.identify_from_credentials()
    assert mock_posthog.alias.call_count == 1
    assert mock_posthog.alias.call_args.kwargs["distinct_id"] == "auth0|user123"


def test_identify_from_credentials_noop_when_credentials_missing(tmp_path, mock_posthog):
    # No credentials.json on disk.
    client.identify_from_credentials()
    mock_posthog.alias.assert_not_called()


def test_identify_from_credentials_noop_when_claim_missing(tmp_path, mock_posthog):
    _write_credentials_with_user_id(tmp_path, None)  # JWT with no user_id claim
    client.identify_from_credentials()
    mock_posthog.alias.assert_not_called()


def test_capture_uses_user_id_from_credentials_when_present(tmp_path, mock_posthog):
    _write_credentials_with_user_id(tmp_path, "auth0|user123")
    client.capture("posture_view", {"is_local": True})
    assert mock_posthog.capture.call_args.kwargs["distinct_id"] == "auth0|user123"
    assert mock_posthog.capture.call_args.kwargs["properties"]["is_authenticated"] is True


def test_ensure_init_enables_geoip_enrichment(mock_posthog):
    # capture() triggers _ensure_init(); geo enrichment must be turned on
    # by flipping the SDK's disable_geoip default off.
    client.capture("install")
    assert mock_posthog.disable_geoip is False


def test_capture_sets_email_person_property_when_authed(tmp_path, mock_posthog):
    _write_credentials_with_user_id_and_email(tmp_path, "auth0|user123", "dev@example.com")
    client.capture("test_start", {"test_level": "unit"})
    props = mock_posthog.capture.call_args.kwargs["properties"]
    assert props["is_authenticated"] is True
    assert props["$set"] == {"email": "dev@example.com"}


def test_capture_omits_email_when_anonymous(mock_posthog):
    client.capture("install")
    props = mock_posthog.capture.call_args.kwargs["properties"]
    assert "$set" not in props


def test_capture_omits_email_when_authed_but_no_email_stored(tmp_path, mock_posthog):
    _write_credentials_with_user_id_and_email(tmp_path, "auth0|user123", None)
    client.capture("test_start", {"test_level": "unit"})
    props = mock_posthog.capture.call_args.kwargs["properties"]
    assert "$set" not in props


def test_shutdown_calls_flush_then_shutdown(mock_posthog):
    client.capture("install")  # prime init
    mock_posthog.reset_mock()

    client.shutdown()
    assert mock_posthog.flush.call_count == 1
    assert mock_posthog.shutdown.call_count == 1


def test_shutdown_swallows_exceptions(mock_posthog):
    client.capture("install")  # prime init
    mock_posthog.flush.side_effect = RuntimeError("boom")
    # Must not raise
    client.shutdown()


# === Section 5 — `hb telemetry` command ===


def _prime_consent_for_clirunner():
    """CliRunner replaces sys.stdout with a non-TTY buffer inside invoke().
    Pre-compute the consent decision while stdout is still TTY-patched."""
    consent.reset_cache()
    consent.is_enabled()


def test_telemetry_disable_sets_opt_out_flag_and_confirms(tmp_path, mock_posthog):
    # mock_posthog looks unused but intercepts the real telemetry_disabled send.
    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["disable"])
    assert result.exit_code == 0
    state = _read_state(tmp_path)
    assert state.get("opted_out") is True
    assert state.get("id", "").startswith("tlm_")
    assert "disabled" in result.output.lower()


def test_telemetry_enable_clears_opt_out_flag_and_confirms(tmp_path):
    _write_state(tmp_path, {"id": "tlm_persistent", "opted_out": True})

    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["enable"])
    assert result.exit_code == 0
    state = _read_state(tmp_path)
    assert state == {"id": "tlm_persistent", "opted_out": False}
    assert "enabled" in result.output.lower()


def test_telemetry_status_shows_enabled_when_clean():
    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["status"])
    assert result.exit_code == 0
    assert "enabled" in result.output.lower()


def test_telemetry_status_shows_disabled_reason_when_env_var_set(monkeypatch):
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    consent.reset_cache()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["status"])
    assert result.exit_code == 0
    assert "disabled" in result.output.lower()
    assert "HB_TELEMETRY_DISABLED" in result.output


# === Section 6 — Install event semantics ===


def test_install_fires_when_state_file_did_not_exist(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: captured.append((event, properties)),
    )

    telemetry_pkg.maybe_fire_install_event()

    assert captured == [("install", None)]


def test_install_does_not_fire_when_state_file_already_has_id(monkeypatch, tmp_path):
    _write_state(tmp_path, {"id": "tlm_existing-uuid", "opted_out": False})

    captured = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: captured.append((event, properties)),
    )

    telemetry_pkg.maybe_fire_install_event()

    assert captured == []


def test_install_does_not_fire_when_telemetry_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    consent.reset_cache()

    captured = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: captured.append((event, properties)),
    )

    telemetry_pkg.maybe_fire_install_event()

    assert captured == []
    assert not _telemetry_file(tmp_path).exists()


def test_install_does_not_fire_for_hb_telemetry_subcommand(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: captured.append((event, properties)),
    )

    telemetry_pkg.maybe_fire_install_event(argv=["hb", "telemetry", "status"])

    assert captured == []


# === Section 7 — Per-command event call sites ===


def test_login_fires_identify_from_credentials(monkeypatch):
    """After successful login, identify_from_credentials() is called."""
    from humanbound_cli.commands import auth as auth_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.identify_from_credentials",
        lambda: calls.append(True),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.default_organisation_id = None
            self.base_url = "https://api.humanbound.ai/api"
            self.username = "test-user"

        def is_authenticated(self):
            return False

        def login(self, callback_port=None):
            return True

        def logout(self, silent=False):
            pass

        def set_organisation(self, org_id):
            pass

        def list_organisations(self):
            return []

    monkeypatch.setattr("humanbound_cli.commands.auth.HumanboundClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(auth_module.login, [])
    assert calls == [True], (
        f"calls: {calls}, output: {result.output}, exception: {result.exception}"
    )


def test_connect_fire_init_helper_emits_event(monkeypatch):
    from humanbound_cli.commands import connect as connect_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    connect_module._fire_init_event(mode="endpoint", success=True, duration_ms=123)

    assert calls == [
        (
            "init",
            {
                "mode": "endpoint",
                "success": True,
                "duration_ms": 123,
                "no_test": False,
                "test_category": "humanbound/adversarial/owasp_agentic",
                "scope_provided": False,
            },
        ),
    ]


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"endpoint": "x", "prompt": None, "repo": None, "openapi": None}, "endpoint"),
        ({"endpoint": None, "prompt": "x", "repo": None, "openapi": None}, "text"),
        ({"endpoint": None, "prompt": None, "repo": "x", "openapi": None}, "agentic"),
        ({"endpoint": None, "prompt": None, "repo": None, "openapi": "x"}, "agentic"),
        ({"endpoint": None, "prompt": None, "repo": None, "openapi": None}, "none"),
    ],
)
def test_connect_resolve_init_mode_from_flags(flags, expected):
    from humanbound_cli.commands import connect as connect_module

    assert connect_module._resolve_init_mode(**flags) == expected


def test_test_fire_start_and_complete_helpers_emit_events(monkeypatch):
    from humanbound_cli.commands import test as test_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    test_module._fire_test_start(test_level="unit", category="owasp", is_local=True)
    test_module._fire_test_complete(
        test_level="unit",
        category="owasp",
        is_local=True,
        outcome="completed",
        duration_ms=1500,
        finding_count=0,
    )

    assert calls == [
        (
            "test_start",
            {"test_level": "unit", "category": "owasp", "is_local": True},
        ),
        (
            "test_complete",
            {
                "test_level": "unit",
                "category": "owasp",
                "is_local": True,
                "outcome": "completed",
                "duration_ms": 1500,
                "finding_count": 0,
            },
        ),
    ]


def test_posture_view_helper_emits_event(monkeypatch):
    from humanbound_cli.commands import posture as posture_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    posture_module._fire_posture_view(is_local=True, mode="current", has_coverage=False)

    assert calls == [
        ("posture_view", {"is_local": True, "mode": "current", "has_coverage": False}),
    ]


def test_findings_view_helper_emits_event(monkeypatch):
    from humanbound_cli.commands import findings as findings_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    findings_module._fire_findings_view(filter_applied=True)

    assert calls == [
        ("findings_view", {"filter_applied": True}),
    ]


def test_gated_command_hit_fires_on_not_authenticated_error(monkeypatch):
    """NotAuthenticatedError → gated_command_hit fires before SystemExit."""
    from humanbound_cli.exceptions import NotAuthenticatedError

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    def fake_cli(*args, **kwargs):
        raise NotAuthenticatedError("not logged in")

    monkeypatch.setattr("humanbound_cli.main.cli", fake_cli)

    with pytest.raises(SystemExit):
        main_module.main()

    events = [c[0] for c in calls]
    assert "gated_command_hit" in events


def test_gated_command_hit_fires_when_findings_short_circuits_on_auth(monkeypatch):
    """When `hb findings` short-circuits via `is_authenticated()` returning False
    (and exits via SystemExit rather than letting NotAuthenticatedError
    propagate), gated_command_hit must still fire — this is the most common
    real-world path.
    """
    from humanbound_cli.commands import findings as findings_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.project_id = None

        def is_authenticated(self):
            return False

    monkeypatch.setattr("humanbound_cli.commands.findings.HumanboundClient", FakeClient)

    runner = CliRunner()
    runner.invoke(findings_module.findings_group, [])

    events = [c[0] for c in calls]
    assert "gated_command_hit" in events


def test_gated_command_hit_fires_when_monitor_short_circuits_on_auth(monkeypatch):
    """Same as the findings test but for `hb monitor` — proves the wiring is
    consistent across the high-traffic gated commands."""
    from humanbound_cli.commands import monitor as monitor_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.project_id = None

        def is_authenticated(self):
            return False

    monkeypatch.setattr("humanbound_cli.commands.monitor.HumanboundClient", FakeClient)

    runner = CliRunner()
    runner.invoke(monitor_module.monitor_command, [])

    events = [c[0] for c in calls]
    assert "gated_command_hit" in events


def test_gated_command_hit_fires_when_providers_short_circuits_on_auth(monkeypatch):
    """Same as the findings test but for `hb providers` (uses console_err
    rather than console)."""
    from humanbound_cli.commands import providers as providers_module

    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: calls.append((event, properties)),
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.project_id = None

        def is_authenticated(self):
            return False

    monkeypatch.setattr("humanbound_cli.commands.providers.HumanboundClient", FakeClient)

    runner = CliRunner()
    runner.invoke(providers_module.providers_group, [])

    events = [c[0] for c in calls]
    assert "gated_command_hit" in events


# === Section 8 — First-run notice ===


def test_first_run_notice_prints_when_install_fires(monkeypatch, capfd):
    """When install event fires (was_new=True), notice is printed to stderr.

    Uses capfd (FD-level capture) so click.echo's writes to sys.stderr are
    captured at the OS level. We bypass the cached consent decision by
    monkeypatching the consent function directly — capfd/capsys replace
    sys.stdout with a non-TTY object which would otherwise invalidate the
    TTY-based consent check.
    """
    monkeypatch.setattr(
        "humanbound_cli.telemetry.consent.is_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: None,
    )

    telemetry_pkg.maybe_fire_install_event()

    captured = capfd.readouterr()
    assert "PRIVACY.md" in captured.err


def test_first_run_notice_does_not_print_on_subsequent_runs(monkeypatch, tmp_path, capfd):
    """If the state file already has an id, no install event and no notice."""
    _write_state(tmp_path, {"id": "tlm_existing-uuid", "opted_out": False})

    monkeypatch.setattr(
        "humanbound_cli.telemetry.consent.is_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: None,
    )

    telemetry_pkg.maybe_fire_install_event()

    captured = capfd.readouterr()
    assert "PRIVACY.md" not in captured.err


def test_first_run_notice_does_not_print_when_disabled(monkeypatch, capfd):
    """When telemetry is disabled, neither install event nor notice fires."""
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    consent.reset_cache()
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture",
        lambda event, properties=None: None,
    )

    telemetry_pkg.maybe_fire_install_event()

    captured = capfd.readouterr()
    assert "PRIVACY.md" not in captured.err


# === Section 9 — telemetry_disabled ping: consent helpers ===


@pytest.mark.parametrize("var", ["DO_NOT_TRACK", "HB_TELEMETRY_DISABLED"])
def test_disabled_ping_reason_env_vars(monkeypatch, var):
    monkeypatch.setenv(var, "1")
    assert consent.disabled_ping_reason() == var


def test_disabled_ping_reason_opt_out_state(tmp_path):
    _write_state(tmp_path, {"id": "tlm_x", "opted_out": True})
    assert consent.disabled_ping_reason() == "opt_out_state"


def test_disabled_ping_reason_none_on_clean_machine():
    assert consent.disabled_ping_reason() is None


def test_disabled_ping_reason_none_for_non_tty_only(monkeypatch):
    # Non-TTY disables telemetry but is not a user choice — not ping-eligible.
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert consent.disabled_ping_reason() is None


def test_disabled_ping_reason_priority_matches_compute(monkeypatch, tmp_path):
    # DO_NOT_TRACK wins over HB var and opt-out state, matching _compute() order.
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    _write_state(tmp_path, {"id": "tlm_x", "opted_out": True})
    assert consent.disabled_ping_reason() == "DO_NOT_TRACK"


def test_disabled_ping_flag_roundtrip(tmp_path):
    assert consent.disabled_ping_already_sent() is False
    assert consent.mark_disabled_ping_sent() is True
    assert consent.disabled_ping_already_sent() is True
    state = _read_state(tmp_path)
    assert state.get("disabled_ping_sent") is True


def test_mark_disabled_ping_preserves_existing_state(tmp_path):
    _write_state(tmp_path, {"id": "tlm_keep", "opted_out": True})
    assert consent.mark_disabled_ping_sent() is True
    state = _read_state(tmp_path)
    assert state == {"id": "tlm_keep", "opted_out": True, "disabled_ping_sent": True}


def test_mark_disabled_ping_creates_no_uuid(tmp_path):
    # A DO_NOT_TRACK-from-first-run machine must not get a machine UUID.
    assert consent.mark_disabled_ping_sent() is True
    state = _read_state(tmp_path)
    assert "id" not in state


def test_mark_disabled_ping_returns_false_on_write_failure(monkeypatch):
    def boom(state):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(consent, "_write_state", boom)
    assert consent.mark_disabled_ping_sent() is False


# === Section 10 — telemetry_disabled ping: client sender ===


def test_capture_disabled_ping_sends_minimal_event(monkeypatch, mock_posthog):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()

    client.capture_disabled_ping("DO_NOT_TRACK")

    assert mock_posthog.capture.call_count == 1
    call = mock_posthog.capture.call_args
    assert re.match(r"^tlm_optout_[0-9a-f-]{36}$", call.kwargs["distinct_id"])
    assert call.kwargs["event"] == "telemetry_disabled"
    props = call.kwargs["properties"]
    assert props["reason"] == "DO_NOT_TRACK"
    assert props["source"] == "cli"
    assert "hb_version" in props
    assert props["$geoip_disable"] is True
    assert props["$process_person_profile"] is False
    # Minimal property set — nothing beyond these keys.
    assert set(props) == {
        "reason",
        "source",
        "hb_version",
        "$geoip_disable",
        "$process_person_profile",
    }


def test_capture_disabled_ping_fresh_id_each_call(mock_posthog):
    client.capture_disabled_ping("DO_NOT_TRACK")
    client.capture_disabled_ping("DO_NOT_TRACK")
    ids = [c.kwargs["distinct_id"] for c in mock_posthog.capture.call_args_list]
    assert ids[0] != ids[1]


def test_capture_disabled_ping_never_attaches_email(tmp_path, mock_posthog):
    _write_credentials_with_user_id_and_email(tmp_path, "auth0|user123", "dev@example.com")
    client.capture_disabled_ping("HB_TELEMETRY_DISABLED")
    props = mock_posthog.capture.call_args.kwargs["properties"]
    assert "$set" not in props
    assert mock_posthog.capture.call_args.kwargs["distinct_id"].startswith("tlm_optout_")


def test_capture_disabled_ping_swallows_exceptions(mock_posthog):
    mock_posthog.capture.side_effect = RuntimeError("network down")
    client.capture_disabled_ping("DO_NOT_TRACK")


# === Section 11 — telemetry_disabled ping: startup orchestration ===


def _capture_ping_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture_disabled_ping",
        lambda reason: calls.append(reason),
    )
    return calls


@pytest.mark.parametrize("var", ["DO_NOT_TRACK", "HB_TELEMETRY_DISABLED"])
def test_ping_fires_for_env_var(monkeypatch, tmp_path, var):
    monkeypatch.setenv(var, "1")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == [var]
    state = _read_state(tmp_path)
    assert state.get("disabled_ping_sent") is True
    assert "id" not in state  # no machine UUID generated


def test_ping_fires_for_preexisting_opt_out(monkeypatch, tmp_path):
    _write_state(tmp_path, {"id": "tlm_old", "opted_out": True})
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == ["opt_out_state"]
    assert _read_state(tmp_path).get("disabled_ping_sent") is True


def test_ping_does_not_fire_when_enabled(monkeypatch, tmp_path):
    calls = _capture_ping_calls(monkeypatch)
    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])
    assert calls == []
    assert not _telemetry_file(tmp_path).exists()


def test_ping_fires_only_once(monkeypatch, tmp_path):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])
    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == ["DO_NOT_TRACK"]


@pytest.mark.parametrize("ci_var", ["CI", "GITHUB_ACTIONS", "GITLAB_CI"])
def test_ping_suppressed_in_ci(monkeypatch, tmp_path, ci_var):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv(ci_var, "true")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []
    assert not _telemetry_file(tmp_path).exists()


def test_ping_suppressed_in_dev_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("HUMANBOUND_DEV", "1")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []


def test_ping_suppressed_in_editable_install(monkeypatch, tmp_path):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setattr(consent, "_is_editable_install", lambda: True)
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []


def test_ping_suppressed_for_non_tty_only(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []
    assert not _telemetry_file(tmp_path).exists()


def test_ping_requires_tty_even_with_env_var(monkeypatch, tmp_path):
    # Containers/scripts get a fresh HOME per run, so a non-TTY ping would
    # fire once per container instead of once per machine. Headless runs
    # stay silent; only interactive users are counted.
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []
    assert not _telemetry_file(tmp_path).exists()


def test_ping_skipped_for_hb_telemetry_subcommand(monkeypatch, tmp_path):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "telemetry", "status"])

    assert calls == []
    assert not _telemetry_file(tmp_path).exists()


def test_ping_fail_closed_when_flag_unwritable(monkeypatch, tmp_path):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()
    calls = _capture_ping_calls(monkeypatch)

    def boom(state):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(consent, "_write_state", boom)

    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert calls == []


def test_ping_never_raises(monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()
    monkeypatch.setattr(
        "humanbound_cli.telemetry.capture_disabled_ping",
        lambda reason: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])


def test_main_fires_startup_events(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "humanbound_cli.telemetry.maybe_fire_install_event",
        lambda argv=None: calls.append("install"),
    )
    monkeypatch.setattr(
        "humanbound_cli.telemetry.maybe_fire_disabled_ping",
        lambda argv=None: calls.append("ping"),
    )
    monkeypatch.setattr("humanbound_cli.main.cli", lambda **kwargs: None)

    main_module.main()

    assert calls == ["install", "ping"]


# === Section 12 — telemetry_disabled ping: `hb telemetry disable` path ===


def test_disable_fires_final_event_with_machine_identity(tmp_path, mock_posthog):
    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["disable"])

    assert result.exit_code == 0
    assert mock_posthog.capture.call_count == 1
    call = mock_posthog.capture.call_args
    assert call.kwargs["event"] == "telemetry_disabled"
    assert call.kwargs["properties"]["reason"] == "command"
    # Normal identity — the machine UUID, not a one-shot optout id.
    assert call.kwargs["distinct_id"].startswith("tlm_")
    assert not call.kwargs["distinct_id"].startswith("tlm_optout_")
    state = _read_state(tmp_path)
    assert state.get("opted_out") is True
    assert state.get("disabled_ping_sent") is True
    assert "final" in result.output.lower()


def test_disable_does_not_fire_twice(tmp_path, mock_posthog):
    _write_state(tmp_path, {"id": "tlm_x", "opted_out": False, "disabled_ping_sent": True})
    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["disable"])

    assert result.exit_code == 0
    mock_posthog.capture.assert_not_called()
    assert _read_state(tmp_path).get("opted_out") is True


def test_disable_when_env_disabled_sends_nothing_and_leaves_flag_unset(
    monkeypatch, tmp_path, mock_posthog
):
    # Env-disabled at command time: no event now; the startup ping on a later
    # run owns the send (with the env reason), so the flag must stay unset.
    monkeypatch.setenv("HB_TELEMETRY_DISABLED", "1")
    _prime_consent_for_clirunner()
    runner = CliRunner()
    result = runner.invoke(telemetry_group, ["disable"])

    assert result.exit_code == 0
    mock_posthog.capture.assert_not_called()
    state = _read_state(tmp_path)
    assert state.get("opted_out") is True
    assert state.get("disabled_ping_sent") is not True


def test_disable_then_env_var_yields_one_event_total(monkeypatch, tmp_path, mock_posthog):
    _prime_consent_for_clirunner()
    runner = CliRunner()
    runner.invoke(telemetry_group, ["disable"])
    assert mock_posthog.capture.call_count == 1

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    consent.reset_cache()
    telemetry_pkg.maybe_fire_disabled_ping(argv=["hb", "test"])

    assert mock_posthog.capture.call_count == 1  # still just the command event


def test_disable_fail_closed_when_flag_unwritable(monkeypatch, mock_posthog):
    _prime_consent_for_clirunner()

    def boom(state):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(consent, "_write_state", boom)
    runner = CliRunner()
    runner.invoke(telemetry_group, ["disable"])

    # No event when the once-ever gate cannot be persisted.
    mock_posthog.capture.assert_not_called()


def test_first_run_notice_mentions_final_optout_event(monkeypatch, capfd):
    monkeypatch.setattr("humanbound_cli.telemetry.consent.is_enabled", lambda: True)
    monkeypatch.setattr("humanbound_cli.telemetry.capture", lambda event, properties=None: None)

    telemetry_pkg.maybe_fire_install_event()

    captured = capfd.readouterr()
    assert "final opt-out event" in captured.err
    assert "PRIVACY.md" in captured.err
