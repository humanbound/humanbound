"""Unit tests for the webhooks command group."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_WEBHOOK,
    assert_exit_error,
    assert_exit_ok,
)

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.webhooks.HumanboundClient"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestHappyPath:
    @patch(PATCH_TARGET)
    def test_list_webhooks(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_WEBHOOK]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks"])
        assert_exit_ok(result)
        mock.get.assert_called_once_with("organisations/org-123/webhooks", include_org=False)
        assert "wh-001" in result.output or "Slack Alerts" in result.output

    @patch(PATCH_TARGET)
    def test_list_webhooks_empty(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": []}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks"])
        assert_exit_ok(result)
        assert "No webhooks configured" in result.output

    @patch(PATCH_TARGET)
    def test_list_webhooks_json(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_WEBHOOK]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "--json"])
        assert_exit_ok(result)
        data = json.loads(result.output.strip())
        # webhooks --json outputs extracted list, not the wrapper dict
        assert isinstance(data, list)
        assert data[0]["id"] == "wh-001"

    @patch(PATCH_TARGET)
    def test_add_webhook(self, MockClient):
        mock = _make_client()
        mock.create_webhook.return_value = {"id": "wh-new"}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "add", "--url", "https://example.com/hook"])
        assert_exit_ok(result)
        mock.create_webhook.assert_called_once()
        call_kwargs = mock.create_webhook.call_args
        assert call_kwargs.kwargs["url"] == "https://example.com/hook"
        assert "wh-new" in result.output

    @patch(PATCH_TARGET)
    def test_add_webhook_with_name_and_events(self, MockClient):
        mock = _make_client()
        mock.create_webhook.return_value = {"id": "wh-new"}
        MockClient.return_value = mock
        result = runner.invoke(
            cli,
            [
                "webhooks",
                "add",
                "--url",
                "https://example.com/hook",
                "--name",
                "My SIEM",
                "--events",
                "finding.created,finding.regressed",
            ],
        )
        assert_exit_ok(result)
        call_kwargs = mock.create_webhook.call_args.kwargs
        assert call_kwargs["name"] == "My SIEM"
        assert call_kwargs["event_types"] == ["finding.created", "finding.regressed"]

    @patch(PATCH_TARGET)
    def test_remove_webhook(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "remove", "wh-001", "--force"])
        assert_exit_ok(result)
        mock.delete_webhook.assert_called_once_with("wh-001")
        assert "deleted" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_test_webhook(self, MockClient):
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "test", "wh-001"])
        assert_exit_ok(result)
        mock.test_webhook.assert_called_once_with("wh-001")
        assert "delivered" in result.output.lower() or "success" in result.output.lower()


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks"])
        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(PATCH_TARGET)
    def test_no_org(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks"])
        assert_exit_error(result)
        assert "No organisation" in result.output

    @patch(PATCH_TARGET)
    def test_add_not_authenticated(self, MockClient):
        mock = _make_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "add", "--url", "https://example.com/hook"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_add_no_org(self, MockClient):
        mock = _make_client(organisation_id=None, _organisation_id=None)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "add", "--url", "https://example.com/hook"])
        assert_exit_error(result)

    @patch(PATCH_TARGET)
    def test_remove_api_error(self, MockClient):
        mock = _make_client()
        mock.delete_webhook.side_effect = APIError("Webhook not found", 404)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "remove", "wh-bad", "--force"])
        assert_exit_error(result)
        assert "Webhook not found" in result.output

    @patch(PATCH_TARGET)
    def test_test_webhook_api_error(self, MockClient):
        mock = _make_client()
        mock.test_webhook.side_effect = APIError("Delivery failed", 502)
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "test", "wh-001"])
        assert_exit_error(result)
        assert "Delivery failed" in result.output

    @patch(PATCH_TARGET)
    def test_add_no_url_shows_error(self, MockClient):
        """--url is required; Click should reject the invocation."""
        mock = _make_client()
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "add"])
        assert result.exit_code != 0


class TestFlags:
    @patch(PATCH_TARGET)
    def test_json_outputs_list(self, MockClient):
        mock = _make_client()
        mock.get.return_value = {"data": [MOCK_WEBHOOK, MOCK_WEBHOOK]}
        MockClient.return_value = mock
        result = runner.invoke(cli, ["webhooks", "--json"])
        data = json.loads(result.output.strip())
        assert isinstance(data, list)
        assert len(data) == 2
