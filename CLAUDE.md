# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`llm-commit` is a plugin for Simon Willison's [`llm`](https://llm.datasette.io/) CLI. It registers a new
`llm commit` command that reads the staged Git diff, sends it to an LLM to draft a commit message, and
(optionally) runs `git commit -s` with the generated message. The entire implementation lives in a single
module, `llm_commit.py`, discovered by `llm` via the `[project.entry-points."llm"]` hook in `pyproject.toml`
(`commit = "llm_commit"`) and `llm.hookimpl`-decorated `register_commands`.

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e '.[test]'
```

## Common commands

```bash
# Run the full test suite
python -m pytest

# Run a single test
python -m pytest tests/test_llm_commit.py::test_commit_cmd_hint -v

# Run the plugin locally against this repo (after installing into an `llm` environment)
git add .
llm commit
```

CI (`.github/workflows/test.yml`) runs `pytest -s` on Python 3.8–3.11. Release publishing
(`.github/workflows/publish.yml`) builds and uploads to PyPI via `twine` on GitHub release creation, gated on
the same test job passing.

## Architecture

Everything is in `llm_commit.py`, organized as a pipeline the `commit` CLI command drives end-to-end:

1. **Git interaction** (`run_git`, `is_git_repo`, `get_staged_diff`) — thin `subprocess` wrappers around git.
   `get_staged_diff` runs `git diff --cached --histogram` and truncates long diffs (default 4000 chars,
   configurable via `--truncation-limit`/`--no-truncation`) to keep prompts bounded.
2. **Prompt construction** (`get_style_description`, `build_prompt`) — builds an XML-tagged prompt
   (`<commit-style>`, `<hint>`, `<diff>`, `<request>`, `<constraints>`) from the diff, an optional user
   `--hint`, and a commit message style. Styles are `"semantic"`, `"conventional"`, or a default fallback,
   each just a format description string with no external template files — new styles are added directly to
   the `style_descriptions` dict in `get_style_description`.
3. **LLM invocation** (`generate_commit_message`) — resolves the model via `llm.get_model(model or
   get_default_model())`, pulls the API key via `llm.get_key` when the model needs one, and calls
   `model_obj.prompt(...)` with a fixed system prompt plus the built prompt. `--model`, `--max-tokens`, and
   `--temperature` map directly to this call. Any `llm.UnknownModelError` or model exception is converted to
   a `click.ClickException` so the CLI fails cleanly instead of raising a stack trace.
4. **Output cleanup** (`clean_message`) — strips whitespace and a wrapping ```` ``` ```` code fence some
   models add around the message.
5. **Confirmation and commit** (`confirm_commit`, `commit_changes`) — prints the generated message, prompts
   for confirmation unless `-y/--yes` is passed, then runs `git commit -s -m <message>` (commits are signed
   off by default).

The `commit_cmd` Click command wires these together and owns CLI-level validation (e.g. `--semantic` and
`--conventional` are mutually exclusive; the repo must be inside a Git work tree before doing anything else).

## Testing conventions

Tests (`tests/test_llm_commit.py`) monkeypatch `subprocess.run` and internal `llm_commit` functions rather
than hitting real Git or a real LLM backend — no network calls or actual git state are involved. CLI-level
behavior is tested through `click.testing.CliRunner` against a `Group` with `register_commands` invoked
manually (see `get_cli_group()`), not by installing the plugin into `llm`.
