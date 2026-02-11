# Contributing to MCP Network Diagnostics

Thank you for your interest in contributing! We welcome all contributions, from bug reports to feature requests and code changes.

## Quick Start

1.  **Fork** the repository.
2.  **Clone** your fork locally.
3.  Install dependencies with `uv`:
    ```bash
    uv sync --all-extras --dev
    ```
4.  Create a branch for your changes:
    ```bash
    git checkout -b feature/my-new-feature
    ```

## Development Workflow

### Linting and Testing

We use `ruff` for linting and `pytest` for testing. Please ensure all checks pass before submitting a PR.

```bash
# Run tests
uv run pytest

# Run linter
uv run ruff check src/ tests/
```

### Pull Requests

1.  Ensure your code follows the existing style.
2.  Update documentation if necessary.
3.  Add tests for any new functionality.
4.  Fill out the Pull Request template completely.

## Release Process

Releases are automated via GitHub Actions when a new tag `v*` is pushed.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
