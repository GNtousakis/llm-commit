import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic._internal._config")

import subprocess
import pytest
import click
import llm_commit  # Your plugin module
from click.testing import CliRunner
from click import Group

# Dummy subprocess.run for successful execution
def dummy_run_success(cmd, capture_output, text, check):
    class DummyCompletedProcess:
        def __init__(self):
            self.stdout = "dummy output"
        returncode = 0
        stderr = ""
    return DummyCompletedProcess()

# Dummy subprocess.run that raises an error
def dummy_run_failure(cmd, capture_output, text, check):
    raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output="", stderr="error message")

# --- run_git Tests ---
def test_run_git_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", dummy_run_success)
    output = llm_commit.run_git(["git", "status"])
    assert output == "dummy output"

def test_run_git_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", dummy_run_failure)
    with pytest.raises(click.ClickException) as exc_info:
        llm_commit.run_git(["git", "status"])
    assert "Git error" in str(exc_info.value)

# --- is_git_repo Tests ---
def test_is_git_repo_true(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    assert llm_commit.is_git_repo() is True

def test_is_git_repo_false(monkeypatch):
    def failing_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(subprocess, "run", failing_run)
    assert llm_commit.is_git_repo() is False

# --- get_staged_diff Tests ---
def test_get_staged_diff_success(monkeypatch):
    monkeypatch.setattr(llm_commit, "run_git", lambda cmd: "diff text")
    diff = llm_commit.get_staged_diff()
    assert diff == "diff text"

def test_get_staged_diff_empty(monkeypatch):
    monkeypatch.setattr(llm_commit, "run_git", lambda cmd: "")
    with pytest.raises(click.ClickException) as exc_info:
        llm_commit.get_staged_diff()
    assert "No staged changes" in str(exc_info.value)

def test_get_staged_diff_truncation(monkeypatch, capsys):
    long_diff = "a" * 5000
    monkeypatch.setattr(llm_commit, "run_git", lambda cmd: long_diff)
    
    # Test default truncation
    diff = llm_commit.get_staged_diff()
    expected = "a" * 4000 + "\n[Truncated]"
    assert diff == expected
    captured = capsys.readouterr()
    assert "Diff is large" in captured.err
    
    # Test custom truncation limit
    diff = llm_commit.get_staged_diff(truncation_limit=2000)
    expected = "a" * 2000 + "\n[Truncated]"
    assert diff == expected
    captured = capsys.readouterr()
    assert "truncating to 2000 characters" in captured.err

    # Test no truncation
    diff = llm_commit.get_staged_diff(no_truncation=True)
    expected = "a" * 5000
    assert diff == expected
    captured = capsys.readouterr()
    assert "truncating" not in captured.err

# --- get_style_description Tests ---
def test_get_style_description_semantic():
    desc = llm_commit.get_style_description("semantic")
    assert 'style="semantic"' in desc
    assert "The commit message should include a one-line summary" in desc

def test_get_style_description_conventional():
    desc = llm_commit.get_style_description("conventional")
    assert 'style="conventional"' in desc
    assert "BREAKING CHANGE" in desc

def test_get_style_description_default():
    desc = llm_commit.get_style_description("unknown")
    assert 'style="default"' in desc
    desc_default = llm_commit.get_style_description(None)
    assert 'style="default"' in desc_default

# --- build_prompt Tests ---
def test_build_prompt_basic():
    prompt = llm_commit.build_prompt("style desc", "diff text", None, None)
    assert "<commit-style>\nstyle desc\n</commit-style>" in prompt
    assert "<diff>\n$ git diff --staged --histogram\ndiff text\n</diff>" in prompt
    assert "<hint>" not in prompt
    assert "* Carefully follow" not in prompt

def test_build_prompt_with_style_and_hint():
    prompt = llm_commit.build_prompt("style desc", "diff text", "semantic", "my hint")
    assert "<hint>\nmy hint\n</hint>" in prompt
    assert "* Carefully follow the <commit-style/> Commit Messages format." in prompt
    assert "using information from the provided <hint/>" in prompt

# --- clean_message Tests ---
class DummyTextResponse:
    def __init__(self, text):
        self._text = text
    def text(self):
        return self._text

def test_clean_message_basic():
    msg = DummyTextResponse("  some message  ")
    assert llm_commit.clean_message(msg) == "some message"

def test_clean_message_backticks():
    msg = DummyTextResponse("```\nsummary\n```")
    assert llm_commit.clean_message(msg) == "summary"

# --- generate_commit_message Tests ---
class DummyResponse:
    def text(self):
        return "Summary\n- Change 1\n- Change 2"

class DummyModel:
    needs_key = False
    def prompt(self, prompt, system, **kwargs):
        return DummyResponse()

class DummyModelWithKey:
    needs_key = True
    key_env_var = "OPENAI_API_KEY"
    def prompt(self, prompt, system, **kwargs):
        # For testing, ensure our prompt mentions a one-line summary if desired.
        assert "concise and professional Git commit message" in prompt
        return DummyResponse()

def test_generate_commit_message_no_key(monkeypatch):
    monkeypatch.setattr(llm_commit.llm, "get_model", lambda model: DummyModel())
    message = llm_commit.generate_commit_message("diff text")
    assert message == "Summary\n- Change 1\n- Change 2"

# --- commit_changes Tests ---
def dummy_run_commit_success(cmd, capture_output, text, check):
    class DummyCompletedProcess:
        def __init__(self):
            self.stdout = ""
        returncode = 0
        stderr = ""
    return DummyCompletedProcess()

def dummy_run_commit_failure(cmd, capture_output, text, check):
    raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output="", stderr="commit error")

def test_commit_changes_success(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", dummy_run_commit_success)
    llm_commit.commit_changes("Test message")
    captured = capsys.readouterr()
    assert "Committed:" in captured.out

def test_commit_changes_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", dummy_run_commit_failure)
    with pytest.raises(click.ClickException) as exc_info:
        llm_commit.commit_changes("Test message")
    assert "Commit failed" in str(exc_info.value)

# --- confirm_commit Tests ---
def test_confirm_commit_yes(monkeypatch):
    monkeypatch.setattr(click, "confirm", lambda prompt: True)
    result = llm_commit.confirm_commit("Test message", auto_yes=False)
    assert result is True

def test_confirm_commit_no(monkeypatch):
    monkeypatch.setattr(click, "confirm", lambda prompt: False)
    result = llm_commit.confirm_commit("Test message", auto_yes=False)
    assert result is False

def test_confirm_commit_auto_yes():
    result = llm_commit.confirm_commit("Test message", auto_yes=True)
    assert result is True

# --- CLI Tests ---
def get_cli_group():
    # Create a simple Click group and register commands.
    cli = Group()
    llm_commit.register_commands(cli)
    return cli

def test_commit_cmd_full_flow_yes(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    monkeypatch.setattr(llm_commit, "get_staged_diff", lambda *args, **kwargs: "diff text")
    monkeypatch.setattr(llm_commit, "generate_commit_message", lambda *args, **kwargs: "Test message")
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "--model", "test-model", "--max-tokens", "50", "--temperature", "0.5"], input="y\n")
    assert result.exit_code == 0
    assert "Commit message:" in result.output
    assert "Test message" in result.output

def test_commit_cmd_auto_yes(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    monkeypatch.setattr(llm_commit, "get_staged_diff", lambda *args, **kwargs: "diff text")
    monkeypatch.setattr(llm_commit, "generate_commit_message", lambda *args, **kwargs: "Test message")
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "-y"])
    assert result.exit_code == 0
    assert "Commit message:" in result.output
    assert "Test message" in result.output

def test_commit_cmd_no(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    monkeypatch.setattr(llm_commit, "get_staged_diff", lambda *args, **kwargs: "diff text")
    monkeypatch.setattr(llm_commit, "generate_commit_message", lambda *args, **kwargs: "Test message")
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit"], input="n\n")
    assert result.exit_code == 0
    assert "Commit aborted" in result.output

def test_commit_cmd_not_git_repo(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: False)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit"])
    assert result.exit_code == 1
    assert "Not a Git repository" in result.output

def test_generate_commit_message_triple_backticks_removal(monkeypatch):
    # Dummy response that returns a commit message wrapped in triple backticks.
    class DummyResponseWithBackticks:
        def text(self):
            return "```\nSummary\n- Change 1\n- Change 2\n```"
    class DummyModelWithBackticks:
        needs_key = False
        def prompt(self, prompt, system, **kwargs):
            return DummyResponseWithBackticks()

    # Monkey-patch the llm.get_model to return our dummy model.
    monkeypatch.setattr(llm_commit.llm, "get_model", lambda model: DummyModelWithBackticks())
    
    # Call the function to generate the commit message.
    message = llm_commit.generate_commit_message("diff text")
    
    assert "```" not in message
    assert "Summary" in message

def test_generate_commit_message_unknown_model(monkeypatch):
    def raise_unknown_model(*args, **kwargs):
        raise llm_commit.llm.UnknownModelError("bad-model")
    monkeypatch.setattr(llm_commit.llm, "get_model", raise_unknown_model)
    with pytest.raises(click.ClickException) as exc_info:
        llm_commit.generate_commit_message("diff")
    assert "Unknown model" in str(exc_info.value)

def test_generate_commit_message_llm_error(monkeypatch):
    class ErrorModel:
        needs_key = False
        def prompt(self, *args, **kwargs):
            raise Exception("API failure")
    monkeypatch.setattr(llm_commit.llm, "get_model", lambda model: ErrorModel())
    with pytest.raises(click.ClickException) as exc_info:
        llm_commit.generate_commit_message("diff")
    assert "LLM error" in str(exc_info.value)

def test_commit_cmd_semantic_conventional_conflict(monkeypatch):
    runner = CliRunner()
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "--semantic", "--conventional"])
    assert result.exit_code != 0
    assert "Cannot use both --semantic and --conventional simultaneously" in result.output

def test_commit_cmd_hint(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    monkeypatch.setattr(llm_commit, "get_staged_diff", lambda *args, **kwargs: "diff text")

    def mock_generate(diff, commit_style, model, max_tokens, temperature, hint):
        return f"Message with hint: {hint}"

    monkeypatch.setattr(llm_commit, "generate_commit_message", mock_generate)
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)

    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "--hint", "test-hint"], input="y\n")
    assert result.exit_code == 0
    assert "Message with hint: test-hint" in result.output

def test_commit_cmd_custom_truncation(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    def mock_get_staged_diff(*args, **kwargs):
        truncation_limit = kwargs.get('truncation_limit', 4000)
        return f"diff text truncated at {truncation_limit}"
    monkeypatch.setattr(llm_commit, "get_staged_diff", mock_get_staged_diff)
    monkeypatch.setattr(llm_commit, "generate_commit_message", lambda diff, *args, **kwargs: f"Test message\n\n{diff}")
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "--truncation-limit", "2000"], input="y\n")
    assert result.exit_code == 0
    assert "diff text truncated at 2000" in result.output

def test_commit_cmd_no_truncation(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(llm_commit, "is_git_repo", lambda: True)
    def mock_get_staged_diff(*args, **kwargs):
        no_truncation = kwargs.get('no_truncation', False)
        return f"diff text {'not ' if no_truncation else ''}truncated"
    monkeypatch.setattr(llm_commit, "get_staged_diff", mock_get_staged_diff)
    monkeypatch.setattr(llm_commit, "generate_commit_message", lambda diff, *args, **kwargs: f"Test message\n\n{diff}")
    monkeypatch.setattr(llm_commit, "commit_changes", lambda msg: None)
    cli = get_cli_group()
    result = runner.invoke(cli, ["commit", "--no-truncation"], input="y\n")
    assert result.exit_code == 0
    assert "diff text not truncated" in result.output