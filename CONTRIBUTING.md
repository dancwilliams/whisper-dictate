# Contributing to Whisper Dictate

Thank you for your interest in contributing to Whisper Dictate! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Enhancements](#suggesting-enhancements)

## Code of Conduct

This project aims to foster an open and welcoming environment. We expect all contributors to:

- Use welcoming and inclusive language
- Respect differing viewpoints and experiences
- Accept constructive criticism gracefully
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/whisper-dictate.git
   cd whisper-dictate
   ```

3. **Add the upstream repository**:
   ```bash
   git remote add upstream https://github.com/dancwilliams/whisper-dictate.git
   ```

## Development Setup

### Prerequisites

- **Python 3.11 or higher**
- **uv package manager** (recommended) - [Installation instructions](https://github.com/astral-sh/uv)
- **CUDA 12.4 + cuDNN 9.5** (optional, for GPU support)
- **Windows OS** (primary target platform)

### Installing Dependencies

Using `uv` (recommended):
```bash
# Install all dependencies including dev tools
uv sync --extra dev

# Or if you don't have uv, use pip
pip install -e ".[dev]"
```

### Running the Application

```bash
# Using uv
uv run python -m whisper_dictate.gui

# Using standard Python
python -m whisper_dictate.gui
```

## Development Workflow

### Creating a Branch

Always create a new branch for your work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

Branch naming conventions:
- `feature/` for new features
- `fix/` for bug fixes
- `docs/` for documentation changes
- `refactor/` for code refactoring
- `test/` for test improvements

### Making Changes

1. **Write code** following our [Coding Standards](#coding-standards)
2. **Add tests** for new functionality
3. **Update documentation** as needed (README, docstrings, CLAUDE.MD)
4. **Run tests** to ensure nothing breaks
5. **Run linters** to ensure code quality

### Keeping Your Fork Updated

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

## Coding Standards

### Style Guide

We follow [PEP 8](https://pep8.org/) with some modifications:

- **Line length**: 100 characters (enforced by ruff)
- **Type hints**: Use modern PEP 604/585 syntax (`list[str]` not `List[str]`, `X | None` not `Optional[X]`)
- **Imports**: Organized by ruff (stdlib, third-party, local)
- **Docstrings**: Google-style docstrings for modules, classes, and public functions

### Code Organization

- **One responsibility per module**: Each module should have a clear, focused purpose
- **Prefer composition over inheritance**: Use classes when state management is needed
- **Avoid global state**: Except where absolutely necessary (like `audio.py`)
- **Use type annotations**: Add type hints to function signatures
- **Document complex logic**: Add inline comments for non-obvious code

### Error Handling

- **Use specific exceptions**: Never use bare `except Exception` without good reason
- **Document exceptions**: Use inline comments to explain what each exception represents
- **Fail gracefully**: Provide meaningful error messages to users
- **Log errors**: Use the logging system for debugging

### Example

```python
def process_text(text: str, max_length: int = 100) -> str:
    """
    Process and truncate text to maximum length.

    Args:
        text: Input text to process
        max_length: Maximum allowed length (default: 100)

    Returns:
        Processed text, truncated if necessary

    Raises:
        ValueError: If max_length is negative
    """
    if max_length < 0:
        raise ValueError("max_length must be non-negative")

    processed = text.strip()
    if len(processed) > max_length:
        processed = processed[:max_length].rstrip() + "..."

    return processed
```

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=whisper_dictate --cov-report=html

# Run specific test file
uv run pytest tests/test_module.py

# Run specific test
uv run pytest tests/test_module.py::test_function_name
```

### Writing Tests

- **Test file naming**: `test_<module_name>.py`
- **Test function naming**: `test_<what_it_tests>`
- **Use pytest fixtures**: For shared setup/teardown
- **Mock external dependencies**: Use `pytest-mock` for Windows APIs, file I/O, etc.
- **Aim for high coverage**: Target 70%+ for core modules

### Test Structure

```python
def test_function_handles_empty_input():
    """Test that function correctly handles empty input."""
    # Arrange
    input_data = ""

    # Act
    result = function_to_test(input_data)

    # Assert
    assert result is None
```

### Coverage Requirements

- **Core modules**: Aim for 70%+ coverage
- **GUI modules**: Test coverage optional (difficult to test GUI code)
- **Integration tests**: Required for major features

## Pull Request Process

### Before Submitting

1. **Run all tests**: `uv run pytest`
2. **Run linter**: `uv run ruff check whisper_dictate/ tests/`
3. **Format code**: `uv run ruff format whisper_dictate/ tests/`
4. **Check type hints** (optional): `uv run mypy whisper_dictate/`
5. **Update CHANGELOG.md**: Add your changes under `[Unreleased]`

### PR Guidelines

1. **Create a descriptive title**: `Add feature X` or `Fix bug in Y`
2. **Fill out the PR template**: Explain what changed and why
3. **Link related issues**: Use `Fixes #123` or `Relates to #456`
4. **Keep PRs focused**: One feature or fix per PR
5. **Add tests**: New features must include tests
6. **Update documentation**: If user-facing changes are made

### PR Template

```markdown
## Description
Brief description of what this PR does and why.

## Changes
- List of changes made
- Another change

## Testing
- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] Manual testing performed

## Checklist
- [ ] Code follows project style guidelines
- [ ] Documentation updated (if needed)
- [ ] CHANGELOG.md updated
- [ ] Tests pass with good coverage
```

### Review Process

- PRs require at least one approval before merging
- Address review comments promptly
- Keep the conversation constructive and professional
- Be open to feedback and suggestions

## Reporting Bugs

### Before Reporting

1. **Check existing issues**: Your bug might already be reported
2. **Try the latest version**: Bug may already be fixed
3. **Gather information**: Steps to reproduce, error messages, logs

### Bug Report Template

```markdown
**Description**
Clear description of the bug.

**Steps to Reproduce**
1. Step one
2. Step two
3. See error

**Expected Behavior**
What you expected to happen.

**Actual Behavior**
What actually happened.

**Environment**
- OS: Windows 10/11
- Python version: 3.11.x
- Whisper Dictate version: 0.1.0
- Device: CPU/CUDA

**Logs**
```
Paste relevant log output from ~/.whisper_dictate/logs/whisper_dictate.log
```

**Additional Context**
Any other relevant information.
```

## Suggesting Enhancements

We welcome feature suggestions! Please:

1. **Check existing issues/PRs**: Feature might already be planned
2. **Be specific**: Clearly describe the enhancement and use case
3. **Consider alternatives**: Discuss different approaches
4. **Think about impact**: How does it affect existing users?

### Enhancement Template

```markdown
**Feature Description**
Clear description of the proposed feature.

**Use Case**
Why is this feature needed? What problem does it solve?

**Proposed Implementation**
Ideas for how this could be implemented.

**Alternatives Considered**
Other approaches you've thought about.

**Additional Context**
Mockups, examples, or references.
```

## Questions?

If you have questions about contributing:

1. **Check the README**: Basic usage and setup information
2. **Check CLAUDE.MD**: Technical architecture and implementation details
3. **Open a discussion**: Use GitHub Discussions for questions
4. **Open an issue**: For specific problems or suggestions

---

Thank you for contributing to Whisper Dictate! Your efforts help make privacy-focused speech-to-text accessible to everyone.
