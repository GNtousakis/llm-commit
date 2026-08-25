import click
import subprocess
import llm

DIFF_CMD = ["git", "diff", "--cached", "--histogram"]

def run_git(cmd, error_prefix="Git error"):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except FileNotFoundError:
        raise click.ClickException("Git not found. Please ensure Git is installed and on your PATH.")
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"{error_prefix}: {e.stderr.strip() or e}")

def is_git_repo():
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        return True
    except FileNotFoundError:
        raise click.ClickException("Git not found. Please ensure Git is installed and on your PATH.")
    except subprocess.CalledProcessError:
        return False

def get_current_staged_diff():
    return run_git(DIFF_CMD)

def get_staged_diff(truncation_limit=4000, no_truncation=False):
    if truncation_limit < 1:
        raise click.ClickException("truncation-limit must be a positive integer.")
    diff = run_git(DIFF_CMD)
    if not diff:
        raise click.ClickException("No staged changes. Use 'git add'.")
    if not no_truncation and len(diff) > truncation_limit:
        click.echo(f"Diff is large; truncating to {truncation_limit} characters.", err=True)
        diff = diff[:truncation_limit] + "\n[Truncated]"
    return diff

def get_style_description(commit_style):
    """
    Return the style description string based on the commit style.

    If the requested style is not found, return a default description.
    
    :param commit_style: Name of the commit style to retrieve (e.g. "semantic" or "conventional").
    :return: A string containing the style description.
    """
    style_descriptions = {
        "semantic": (
            "<description>"
            "The commit message should include a one-line summary at the top "
            "(with change type and optional scope), then an optional description of "
            "why the change was made, followed by points for the key changes.\n"
            "</description>\n"
            "<message-format style=\"semantic\">\n"
            "[type][optional scope]: [one-line summary]\n"
            "\n"
            "[short description of why this change was made]\n"
            "\n"
            "* [key change 1 and how it was made]\n"
            "* [key change 2 and how it was made]\n"
            "* [...]\n"
            "\n"
            "</message-format>\n"
            "<examples>\n"
            "</examples>\n"
        ),
        "conventional": (
            "<description>"
            "The commit message should include a one-line summary at the top "
            "(with change type, optional scope, and optional mark), then an "
            "optional description of why the change was made, followed by "
            "points for the key changes.\n"
            "</description>\n"
            "<message-format style=\"conventional\">"
            "[type][optional scope][optional mark]: [one-line summary]\n"
            "\n"
            "[short description of why this change was made]\n"
            "\n"
            "* [key change 1 and how it was made]\n"
            "* [key change 2 and how it was made]\n"
            "* [...]\n"
            "\n"
            "[optional BREAKING CHANGE if applicable]\n"
            "</message-format>\n"
            "<examples>\n"
            "</examples>\n"
        ),
    }

    # Default style description if style not found
    default_description = (
        "<description>"
        "The commit message should include a one-line summary at the top "
        "then an optional description of why the change was made, followed by "
        "points for the key changes.\n"
        "</description>\n"
        "<message-format style=\"default\">"
        "[short description of why this change was made]\n"
        "\n"
        "* [key change 1 and how it was made]\n"
        "* [key change 2 and how it was made]\n"
        "* [...]\n"
        "\n"
        "</message-format>\n"
    )

    return style_descriptions.get(commit_style, default_description)


_PROMPT_TAGS = ("commit-style", "hint", "diff", "request", "constraints")

def escape_prompt_tags(text):
    """
    Neutralize occurrences of this prompt's own structural tags (e.g. </diff>)
    inside untrusted content, so diff or hint text can't break out of its tag
    and inject new instructions into the prompt.
    """
    for tag in _PROMPT_TAGS:
        text = text.replace(f"</{tag}>", f"&lt;/{tag}&gt;").replace(f"<{tag}>", f"&lt;{tag}&gt;")
    return text

def build_prompt(style_description, diff, commit_style, hint):
    """
    Build the prompt string based on the style description, diff, and constraints.

    :param style_description: The description of the commit message style.
    :param diff: The code diff to be included in the prompt.
    :param commit_style: Optional commit style name.
    :return: A formatted string containing the entire prompt.
    """
    diff = escape_prompt_tags(diff)
    if hint:
        hint = escape_prompt_tags(hint)

    constraints = [
        "* Ensure the commit message is concise and follows professional standards.",
        "* Ensure the subject is in present tense and concise.",
        "* Include the relevant details from the diff in items of the commit message.",
        "* Avoid using markdown, HTML, or other syntax markers."
    ]

    if commit_style:
        constraints.insert(
            0,
            "* Carefully follow the <commit-style/> Commit Messages format."
        )

    constraints_str = "\n".join(constraints)

    prompt = []

    # Always include style
    prompt.extend([
        "<commit-style>",
        style_description,
        "</commit-style>"
    ])

    if hint:
        prompt.extend([
            "<hint>",
            hint,
            "</hint>"
        ])

    prompt.extend([
        "<diff>",
        "$ git diff --staged --histogram",
        diff,
        "</diff>",
        "<request>",
        "Generate a Git commit title and commit message based on the above <diff/>"
        + (", and using information from the provided <hint/>" if hint else "")
        + ".",
        "</request>",
        "<constraints>",
        constraints_str,
        "</constraints>"
    ])
    
    return "\n".join(prompt)

def generate_commit_message(diff, commit_style=None, model=None, max_tokens=None, temperature=None, hint=None):
    from llm.cli import get_default_model
    from llm import get_key

    style_description = get_style_description(commit_style)
    prompt = build_prompt(style_description, diff, commit_style, hint)

    try:
        model_obj = llm.get_model(model or get_default_model())
    except llm.UnknownModelError as e:
        raise click.ClickException(f"Unknown model: {e}")

    if model_obj.needs_key:
        model_obj.key = get_key("", model_obj.needs_key, model_obj.key_env_var)

    try:
        kwargs = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = model_obj.prompt(
            prompt,
            system=(
                "You are a professional developer with more than 20 years of "
                "experience. You're an expert at writing Git commit messages from "
                "code diffs. Focus on highlighting the added value of changes "
                "(meta-analysis, what could have happened without this change?), "
                "followed by bullet points detailing key changes (avoid "
                "paraphrasing). Use the specified commit Git style, while forbidding "
                "other syntax markers or tags (e.g., markdown, HTML, etc.)"
            ),
            **kwargs
        )
        return clean_message(response)
    except Exception as e:
        raise click.ClickException(f"LLM error: {e}")

def commit_changes(message):
    run_git(["git", "commit", "-s", "-m", message], error_prefix="Commit failed")
    click.echo(f"Committed:\n{message}")

def confirm_commit(message, auto_yes=False):
    click.echo(f"Commit message:\n{message}\n")
    if auto_yes:
        return True
    return click.confirm("Commit this message?")

def clean_message(message):
    message = message.text().strip()
    # Remove triple backticks at the beginning and end, if present
    if message.startswith("```") and message.endswith("```"):
        message = message[3:-3]
        # Drop a leading fence language tag (e.g. ```markdown) left on its own line
        first_line, sep, rest = message.partition("\n")
        if sep and first_line.strip() and " " not in first_line.strip():
            message = rest
        message = message.strip()
    return message

@llm.hookimpl
def register_commands(cli):
    @cli.command(name="commit")
    @click.option("-y", "--yes", is_flag=True, help="Commit without prompting")
    @click.option("--model", help="LLM model to use")
    @click.option("--max-tokens", type=int, help="Max tokens")
    @click.option("--temperature", type=float, help="Temperature")
    @click.option("--truncation-limit", type=click.IntRange(min=1), default=4000, help="Character limit for diff truncation")
    @click.option("--no-truncation", is_flag=True, help="Disable diff truncation. Can cause issues with large diffs")
    @click.option("--semantic", is_flag=True, help="Enforce Semantic Commit Messages format")
    @click.option("--conventional", is_flag=True, help="Enforce Conventional Commits format")
    @click.option("--hint", help="Hint message to guide the commit message generation")
    def commit_cmd(yes, model, max_tokens, temperature, truncation_limit, no_truncation, semantic, conventional, hint):
        if semantic and conventional:
            raise click.UsageError("Cannot use both --semantic and --conventional simultaneously.")

        if semantic:
            commit_style = "semantic"
        elif conventional:
            commit_style = "conventional"
        else:
            commit_style = "default"

        if not is_git_repo():
            raise click.ClickException("Not a Git repository.")

        baseline_diff = get_current_staged_diff()
        diff = get_staged_diff(truncation_limit=truncation_limit, no_truncation=no_truncation)
        message = generate_commit_message(diff, commit_style, model=model, max_tokens=max_tokens, temperature=temperature, hint=hint)
        if not message.strip():
            raise click.ClickException("Generated commit message was empty.")
        if confirm_commit(message, auto_yes=yes):
            if get_current_staged_diff() != baseline_diff:
                raise click.ClickException("Staged changes changed since the commit message was generated. Aborting.")
            commit_changes(message)
        else:
            click.echo("Commit aborted.")
