# Contributing to Prospere

First off, thank you for considering contributing to Prospere! It's people like you that make Prospere such a great tool.

## Development Setup

We use `uv` for dependency management and `pre-commit` to ensure code quality.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/vequalia/prospere.git
    cd prospere
    ```

2.  **Install dependencies using `uv`:**
    ```bash
    uv sync --all-extras --dev
    ```

3.  **Activate the virtual environment:**
    ```bash
    source .venv/bin/activate
    ```

4.  **Install pre-commit hooks:**
    ```bash
    pre-commit install
    ```

## Submitting Changes

1.  Create a new branch for your feature or bugfix.
2.  Make your changes.
3.  Ensure tests pass by running `pytest`.
4.  Ensure code style passes by running `ruff check .` (pre-commit will also run this).
5.  Submit a Pull Request to the `main` branch.

## Code Style

We use `ruff` for code formatting and linting. Your code will be automatically checked when you commit if you have `pre-commit` installed.
