# Contributing to URL Shortener

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd url-shortener
   ```

2. **Start the development environment**
   ```bash
   make up
   ```

3. **Run tests**
   ```bash
   make test
   ```

## Coding Standards

All code must follow the coding standards defined in `docs/coding-standards.md`. Key points:

- Use Python 3.12+ with full type annotations
- Follow Black formatting (120 character line length)
- Add comprehensive module docstrings with ASCII flow diagrams
- Include defensive assertions with descriptive messages
- Export public API via `__all__`
- No `Any` types - use specific types

## Development Workflow

1. Create a feature branch from `main`
2. Make your changes following the coding standards
3. Run tests: `make test`
4. Update documentation if needed
5. Submit a pull request

## Project Structure

```
.
├── app/                 # FastAPI application
├── tests/              # Test suite
├── docker/             # Docker configurations
├── docs/               # Documentation
├── docker-compose.yml  # Development orchestration
├── Makefile           # Common commands
└── pyproject.toml     # Project configuration
```

## Testing

- Unit tests for all public methods
- Integration tests for database/cache interactions
- E2E tests for full request cycles
- All tests must pass before merge

## Documentation

- Update README.md for user-facing changes
- Update architecture docs for structural changes
- Add strategy comparisons for new approaches
- Keep API docs in sync with code changes

## Phased Development

This project follows a phased approach:
1. **Phase 1**: Foundation (API, DB, cache, tests, docs)
2. **Phase 2**: Frontend + Analytics
3. **Phase 3**: Scalability features
4. **Phase 4**: Testing infrastructure
5. **Phase 5**: Complete documentation

## Questions?

- Check existing issues and documentation
- Review `docs/` folder for architecture and strategies
- Ask questions in issues for clarification
