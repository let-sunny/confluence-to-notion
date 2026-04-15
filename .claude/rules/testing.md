# Testing Rules

- Framework: pytest + pytest-asyncio
- TDD cycle: red → green → refactor
- Every agent has unit tests with fixtures in `tests/fixtures/<agent>/`
- Every external I/O (Confluence, Notion, Anthropic) must be mocked in unit tests
- Use `respx` for mocking httpx requests
- Integration tests live in `tests/integration/`, skipped by default, run with `-m integration`
- Coverage target: 80%+ on `src/`, no coverage requirement on CLI wiring
- Test file naming: `test_<module>.py`
- Fixtures shared across tests go in `tests/conftest.py`
