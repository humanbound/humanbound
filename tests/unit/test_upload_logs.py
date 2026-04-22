"""
Unit tests for `hb logs upload` command.

NOTE: The `logs` group uses invoke_without_command=True with an optional
EXPERIMENT_ID argument. Click consumes 'upload' as experiment_id when
invoked via the full CLI path, so we invoke upload_command directly
for functional tests.
"""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.commands.logs import upload_command
from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.logs.HumanboundClient"


def _make_mock_client(**overrides):
    mock = MagicMock()
    mock.is_authenticated.return_value = True
    mock.organisation_id = "org-123"
    mock.project_id = "proj-456"
    mock._organisation_id = "org-123"
    mock._project_id = "proj-456"
    mock._username = "tester"
    mock._email = "test@example.com"
    mock.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


SAMPLE_CONVERSATIONS = [
    {
        "conversation": [
            {"u": "hello", "a": "hi there"},
            {"u": "how are you?", "a": "I'm doing well!"},
        ],
    },
    {
        "conversation": [
            {"u": "what is 2+2?", "a": "4"},
        ],
        "thread_id": "thread-001",
    },
]

MOCK_UPLOAD_RESPONSE = {
    "dataset_id": "ds-001",
    "id": "ds-001",
    "test_category": "humanbound/evaluation/uploaded",
    "conversations_count": 2,
}


def _write_conv_file(tmp_path, data=None, name="conversations.json"):
    """Helper to write a conversations file and return its path."""
    conv_file = tmp_path / name
    conv_file.write_text(json.dumps(data if data is not None else SAMPLE_CONVERSATIONS))
    return str(conv_file)


class TestHappyPath:
    def test_logs_help_shows_upload_subcommand(self):
        """logs --help lists upload as a subcommand."""
        result = runner.invoke(cli, ["logs", "--help"])
        assert result.exit_code == 0
        assert "upload" in result.output.lower()

    def test_upload_help(self):
        """upload --help shows usage and options."""
        result = runner.invoke(upload_command, ["--help"])
        assert result.exit_code == 0
        assert "--tag" in result.output
        assert "--lang" in result.output
        assert "--force" in result.output
        assert "FILE" in result.output

    @patch(PATCH_TARGET)
    def test_upload_valid_json(self, MockClient, tmp_path):
        """upload with valid JSON file succeeds."""
        mock = _make_mock_client()
        mock.upload_conversations.return_value = MOCK_UPLOAD_RESPONSE
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "Upload complete" in result.output or "ds-001" in result.output
        mock.upload_conversations.assert_called_once()
        call_args = mock.upload_conversations.call_args
        assert call_args[0][0] == "proj-456"  # project_id
        assert len(call_args[0][1]) == 2  # 2 conversations

    @patch(PATCH_TARGET)
    def test_upload_with_tag(self, MockClient, tmp_path):
        """upload with --tag passes tag to client."""
        mock = _make_mock_client()
        mock.upload_conversations.return_value = MOCK_UPLOAD_RESPONSE
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--tag", "prod-v2", "--force"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        call_kwargs = mock.upload_conversations.call_args
        assert call_kwargs[1]["tag"] == "prod-v2"

    @patch(PATCH_TARGET)
    def test_upload_with_lang(self, MockClient, tmp_path):
        """upload with --lang passes language to client."""
        mock = _make_mock_client()
        mock.upload_conversations.return_value = MOCK_UPLOAD_RESPONSE
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--lang", "english", "--force"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        call_kwargs = mock.upload_conversations.call_args
        assert call_kwargs[1]["lang"] == "english"

    @patch(PATCH_TARGET)
    def test_upload_shows_summary(self, MockClient, tmp_path):
        """upload displays file name and conversation count."""
        mock = _make_mock_client()
        mock.upload_conversations.return_value = MOCK_UPLOAD_RESPONSE
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path, name="my_data.json")

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "my_data.json" in result.output
        assert "2" in result.output  # 2 conversations

    @patch(PATCH_TARGET)
    def test_upload_shows_dataset_id(self, MockClient, tmp_path):
        """upload displays the returned dataset ID."""
        mock = _make_mock_client()
        mock.upload_conversations.return_value = MOCK_UPLOAD_RESPONSE
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "ds-001" in result.output


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_upload_not_authenticated(self, MockClient, tmp_path):
        """upload fails when not authenticated."""
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output or "login" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_upload_no_project(self, MockClient, tmp_path):
        """upload fails when no project selected."""
        mock = _make_mock_client(project_id=None, _project_id=None)
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code != 0
        assert "project" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_upload_invalid_json(self, MockClient, tmp_path):
        """upload fails with invalid JSON file."""
        mock = _make_mock_client()
        MockClient.return_value = mock

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("this is not json {{{")

        result = runner.invoke(upload_command, [str(bad_file), "--force"])
        assert result.exit_code != 0
        assert "Invalid JSON" in result.output or "JSON" in result.output

    @patch(PATCH_TARGET)
    def test_upload_not_array(self, MockClient, tmp_path):
        """upload fails when file contains a dict instead of array."""
        mock = _make_mock_client()
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path, data={"not": "an array"})

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code != 0
        assert "array" in result.output.lower() or "JSON" in result.output

    @patch(PATCH_TARGET)
    def test_upload_empty_array(self, MockClient, tmp_path):
        """upload fails with empty conversation array."""
        mock = _make_mock_client()
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path, data=[])

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code != 0
        assert "no conversations" in result.output.lower() or "empty" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_upload_api_error(self, MockClient, tmp_path):
        """upload handles APIError from upload_conversations."""
        mock = _make_mock_client()
        mock.upload_conversations.side_effect = APIError("Upload failed", status_code=500)
        MockClient.return_value = mock

        path = _write_conv_file(tmp_path)

        result = runner.invoke(upload_command, [path, "--force"])
        assert result.exit_code != 0
