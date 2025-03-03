import click
import sys
import os
import logging
import subprocess
from pathlib import Path
import llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_git(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error("Git error: %s", e)
        sys.exit(1)

def is_git_repo():
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def get_staged_diff(truncation_limit=4000, no_truncation=False):
    diff = run_git(["git", "diff", "--cached", "--histogram"])
    if not diff:
        logging.error("No staged changes. Use 'git add'.")
        sys.exit(1)
    if not no_truncation and len(diff) > truncation_limit:
        logging.warning(f"Diff is large; truncating to {truncation_limit} characters.")
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


def build_prompt(style_description, diff, commit_style, hint):
    """
    Build the prompt string based on the style description, diff, and constraints.
    
    :param style_description: The description of the commit message style.
    :param diff: The code diff to be included in the prompt.
    :param commit_style: Optional commit style name.
    :return: A formatted string containing the entire prompt.
    """
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

def generate_commit_message(diff, commit_style=None, model=None, max_tokens=400, temperature=0.8, hint=None):
    import llm
    from llm.cli import get_default_model
    from llm import get_key

    style_description = get_style_description(commit_style)
    prompt = build_prompt(style_description, diff, commit_style, hint)

    model_obj = llm.get_model(model or get_default_model())
    if model_obj.needs_key:
        model_obj.key = get_key("", model_obj.needs_key, model_obj.key_env_var)
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
        max_tokens=max_tokens,
        temperature=temperature
    )
    return clean_message(response)

def commit_changes(message):
    try:
        subprocess.run(["git", "commit", "-s", "-m", message],
                       check=True, capture_output=True, text=True)
        logging.info("Committed:\n%s", message)
    except subprocess.CalledProcessError as e:
        logging.error("Commit failed: %s", e)
        sys.exit(1)

def confirm_commit(message, auto_yes=False):
    click.echo(f"Commit message:\n{message}\n")
    if auto_yes:
        return True
    while True:
        ans = input("Commit this message? (yes/no): ").strip().lower()
        if ans in ("yes", "y"):
            return True
        elif ans in ("no", "n"):
            return False
        click.echo("Please enter 'yes' or 'no'.")

def clean_message(message):
    message = message.text().strip()
    # Remove triple backticks at the beginning and end, if present
    if message.startswith("```") and message.endswith("```"):
        message = message[3:-3].strip()
    return message

@llm.hookimpl
def register_commands(cli):
    import llm
    from llm.cli import get_default_model
    from llm import get_key

    @cli.command(name="commit")
    @click.option("-y", "--yes", is_flag=True, help="Commit without prompting")
    @click.option("--model", help="LLM model to use")
    @click.option("--max-tokens", type=int, default=100, help="Max tokens")
    @click.option("--temperature", type=float, default=0.3, help="Temperature")
    @click.option("--truncation-limit", type=int, default=4000, help="Character limit for diff truncation")
    @click.option("--no-truncation", is_flag=True, help="Disable diff truncation. Can cause issues with large diffs")
    @click.option("--semantic", is_flag=True, help="Enforce Semantic Commit Messages format")
    @click.option("--conventional", is_flag=True, help="Enforce Conventional Commits format")
    @click.option("--hint", help="Hint message to guide the commit message generation")
    def commit_cmd(yes, model, max_tokens, temperature, truncation_limit, no_truncation, semantic, conventional, hint):
        if semantic and conventional:
            logging.error("Cannot use both --semantic and --conventional simultaneously.")
            sys.exit(1)
        if semantic:
            commit_style = "semantic"
        elif conventional:
            commit_style = "conventional"
        else:
            commit_style = "default"

        if not is_git_repo():
            logging.error("Not a Git repository.")
            sys.exit(1)
        diff = get_staged_diff(truncation_limit=truncation_limit, no_truncation=no_truncation)
        message = generate_commit_message(diff, commit_style, model=model, max_tokens=max_tokens, temperature=temperature, hint=hint)
        if confirm_commit(message, auto_yes=yes):
            commit_changes(message)
        else:
            logging.info("Commit aborted.")
            sys.exit(0)
