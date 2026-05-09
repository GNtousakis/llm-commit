# llm-commit

[LLM](https://llm.datasette.io/) plugin for generating Git commit messages using an LLM.

[![Tip Me](https://img.shields.io/badge/Tip_Me-Lightning-792EE5?style=flat&logo=lightning&logoColor=white)](https://quickchart.io/qr?size=500&text=lightning:lnbc1p5l7xhrpp59gny7x55gvcmmv8ukg9kajec493mhf93qujl3a3j3sq5epvghmmqdqqcqzzsxqrrs0fppqk2gu4kh4m397g4few2y86jx6876dvccysp5llsaw0ddlep6vlutdqzlsx2yxtxfrke5jl5393tqm3x705rqnrls9qxpqysgqrdh4e0vgsvpyz0a7sdf5dypw7gvfsf0jxj6rapsy7840jzudf5wyvcfjqm0j3r5yztfhnd7k8750zq39x2v6rgkrq6r75v4q8ur0hxqpg73795)

## Installation

Install this plugin in the same environment as LLM.

```bash
llm install llm-commit
```

## Usage

The plugin adds a new command, `llm commit`. This command generates a commit message from your staged Git diff and then commits the changes.

For example, to generate and commit changes

```bash
# Stage your changes first
git add .

# Generate and commit with an LLM-generated commit message
llm commit
```

You can also customize options:

```bash
# Skip the confirmation prompt
llm commit --yes

# Use a different LLM model, adjust max tokens, or change the temperature
llm commit --model gpt-4 --max-tokens 150 --temperature 0.8

# Control diff truncation behavior
llm commit --truncation-limit 2000  # Truncate diffs longer than 2000 characters
llm commit --no-truncation         # Never truncate diffs (use with caution on large changes)
```

## Development

To set up this plugin locally, first check out the code. Then create a new virtual environment:

```bash
cd llm-commit
python3 -m venv venv
source venv/bin/activate
```

Now install the dependencies and test dependencies:

```bash
pip install -e '.[test]'
```

To run the tests:

```bash
python -m pytest
```
