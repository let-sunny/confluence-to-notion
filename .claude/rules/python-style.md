# Python Style Rules

- Python 3.11+ syntax features allowed: `match` statements, `Self` type, `StrEnum`, etc.
- Full type hints on all public functions; use `typing` imports only when necessary
- Pydantic v2 for all data models (`model_config` style, not Config inner class)
- Async-first for all I/O: use `httpx.AsyncClient`, not `requests`
- No `print()` calls; use `rich` console/logger for all output
- ruff config: line length 100, target py311
- Imports sorted by ruff (isort-compatible)
- Prefer `pathlib.Path` over `os.path`
