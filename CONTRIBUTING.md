# Contributing

`confluence-to-notion` 기여 가이드입니다. 이 프로젝트는 Claude Code 서브에이전트 파이프라인으로 Confluence → Notion 변환 규칙을 자동 발견하고, 결정론적 컨버터로 마이그레이션을 수행합니다.

이 문서는 개발 환경 구성부터 에이전트 추가, 프롬프트 변경 정책, 테스트, PR 규칙, 코드 스타일까지 기여자가 알아야 할 사항을 순서대로 정리합니다. 자세한 규칙은 각 섹션 끝의 `.claude/rules/*.md`를 참고하세요.

---

## 1. 개발 환경 설정 (Development Environment Setup)

### 요구 사항

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (패키지 매니저)
- Confluence / Notion API 자격 증명

### 설치

```bash
git clone https://github.com/let-sunny/confluence-to-notion.git
cd confluence-to-notion
uv sync
cp .env.example .env
```

### 환경 변수

`.env` 파일에 다음을 설정합니다. 공개 위키라면 `CONFLUENCE_BASE_URL`만 필수입니다.

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `CONFLUENCE_BASE_URL` | ✓ | Confluence 베이스 URL (예: `https://cwiki.apache.org/confluence`) |
| `CONFLUENCE_EMAIL` | 비공개 위키 | 계정 이메일 |
| `CONFLUENCE_API_TOKEN` | 비공개 위키 | API 토큰 |
| `CONFLUENCE_API_PATH` | 선택 | 자체 호스팅 경로 오버라이드 (기본값 `/rest/api`) |
| `NOTION_API_TOKEN` | ✓ | Notion 인티그레이션 토큰 (`ntn_...`) |
| `NOTION_ROOT_PAGE_ID` | ✓ | 마이그레이션 대상 Notion 루트 페이지 ID |

### 연결 확인

```bash
uv run cli notion-ping
```

Notion 토큰이 유효하면 워크스페이스 정보가 출력됩니다.

---

## 2. 에이전트 추가 방법 (How to Add an Agent)

에이전트는 **Claude Code 서브에이전트**이며, 각 에이전트는 독립된 `claude -p` 세션으로 실행됩니다. 에이전트 간 상태는 공유되지 않으며, 오직 **파일**로만 통신합니다.

### 2.1 에이전트 정의 파일

`.claude/agents/<pipeline>/<name>.md` 경로에 마크다운 파일을 생성합니다. 파이프라인 디렉터리와 파일 이름은 모두 kebab-case입니다.

에이전트 파일은 다음 순서로 작성합니다 (`.claude/rules/prompts.md` 참고):

1. **Purpose** — 에이전트가 하는 일을 한 줄로 요약
2. **Input** — 읽는 파일과 기대 포맷
3. **Output** — 생성하는 파일과 기대 포맷
4. **Instructions** — 상세 프롬프트 (제약, 예시 포함)
5. **Output schema reference** — 출력이 만족해야 할 Pydantic 모델

### 2.2 Pydantic-as-contract 규칙

에이전트 출력 스키마는 코드가 먼저입니다.

1. `src/**/schemas.py`에 Pydantic v2 모델을 정의한다.
2. 에이전트는 이 모델과 호환되는 JSON을 생성한다.
3. 오케스트레이션 스크립트는 `uv run cli validate-output <file> <schema>`로 출력을 검증한다.

모델이 계약이므로, 에이전트 프롬프트는 스키마를 참조하고 예시를 포함해야 합니다.

### 2.3 파이프라인 배선

오케스트레이션은 **bash 스크립트**입니다 (`scripts/discover.sh`, `scripts/develop.sh`). Claude 슬래시 커맨드가 아닙니다. 흐름 제어는 LLM 판단이 아닌 코드에 드러나야 합니다.

새 단계를 추가할 때는 기존 `run_step` / `run_agent` 패턴을 따릅니다. 에이전트 본문과 런타임 지시(입력 경로, 출력 경로)를 한 프롬프트로 이어 붙입니다.

```bash
# scripts/discover.sh — 예: 패턴 발견 단계와 유사
claude -p "$(cat .claude/agents/discover/pattern-discovery.md)

Analyze the XHTML files in samples/ and write discovered patterns to output/patterns.json" \
  --allowedTools "Read,Write,Bash,Glob,Grep,Edit"
```

`scripts/develop.sh`는 `run_agent` 헬퍼로 동일하게 `claude -p "<프롬프트>" --allowedTools ...` 형태를 사용합니다.

각 단계는 이전 단계가 생성한 파일을 입력으로 받고, 다음 단계를 위한 파일을 출력합니다. 실패한 단계만 재실행할 수 있도록 `--from N` 재개 옵션을 유지합니다.

### 2.4 파일 기반 통신

- 입력은 디스크의 파일 (예: `samples/*.xhtml`, `output/patterns.json`)
- 출력은 디스크의 파일 (예: `output/rules.json`, `output/dev/plan.json`)
- 공유 메모리, 컨텍스트 주입 금지

참고: [`.claude/rules/agents.md`](./.claude/rules/agents.md), [`.claude/rules/prompts.md`](./.claude/rules/prompts.md)

---

## 3. 프롬프트 변경 정책 (Prompt Modification Policy)

`.claude/agents/**/*.md` 파일을 수정한 PR은 **반드시** eval을 실행한 뒤 제출합니다.

```bash
bash scripts/run-eval.sh
```

- 결과는 `eval_results/<timestamp>.json`에 저장됩니다.
- Eval 고정 입력(fixture)은 `tests/fixtures/eval/`에 있습니다.

### 품질 기준

- **스키마 검증 통과** — 에이전트 출력이 대응되는 Pydantic 모델로 파싱되어야 합니다.
- **Fixture 비교 무회귀** — 고정 입력에 대한 출력이 기준선에서 품질이 저하되지 않아야 합니다.

회귀가 발생했다면 프롬프트를 수정해 재시도하거나, 변경이 의도된 것이라면 기준선을 업데이트한 이유를 PR 본문에 명시합니다.

참고: [`.claude/rules/prompts.md`](./.claude/rules/prompts.md)

---

## 4. 테스트 가이드 (Testing Guide)

### TDD 사이클

`src/` 아래 Python 코드는 **테스트 우선**으로 작성합니다.

1. **Red** — 실패하는 테스트 작성
2. **Green** — 테스트를 통과시키는 최소 구현
3. **Refactor** — 동작을 유지한 채 개선

### 도구와 구조

- 프레임워크: `pytest` + `pytest-asyncio`
- 테스트 파일 이름: `test_<module>.py`
- 픽스처 위치: `tests/fixtures/<agent>/`
- 공유 픽스처: `tests/conftest.py`
- 외부 I/O(Confluence, Notion, Anthropic)는 유닛 테스트에서 **반드시 모킹**
- httpx 요청 모킹: `respx`
- 통합 테스트: `tests/integration/`, 기본 스킵, `-m integration`으로 실행

### 커버리지

- `src/` 커버리지 목표: **80%+**
- CLI 배선 코드는 커버리지 요구 없음

### 실행

```bash
uv run pytest                          # 전체 유닛 테스트
uv run pytest -m integration           # 통합 테스트
uv run pytest tests/unit/test_foo.py   # 특정 파일
```

참고: [`.claude/rules/testing.md`](./.claude/rules/testing.md)

---

## 5. Pull Request 규칙 (Pull Request Rules)

### 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/) 형식을 따릅니다.

```
<type>: <subject>

[optional body]
```

허용 타입: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### PR 생성

- **Squash merge 전용** — 병합 시 하나의 커밋으로 합쳐집니다.
- 관련 이슈를 PR 본문에 `Closes #N` 키워드로 연결하면 병합 시 자동 클로즈됩니다.
- PR은 작고 주제가 분명해야 합니다. 여러 관심사가 섞여 있다면 분리하세요.
- 프롬프트를 수정한 PR은 **섹션 3 (프롬프트 변경 정책)**의 eval 결과를 본문에 첨부하거나 요약합니다.

### 체크리스트

- [ ] `uv run pytest` 통과
- [ ] `uv run ruff check src/ tests/` 통과
- [ ] `uv run mypy src/` 통과 (strict)
- [ ] 프롬프트 수정 시 `bash scripts/run-eval.sh` 실행
- [ ] `Closes #N` 링크 포함

---

## 6. 코드 스타일 (Code Style)

### 린트와 타입 체크

```bash
uv run ruff check src/ tests/   # 라인 길이 100, target py311, isort 호환
uv run mypy src/                # src/에 대해 strict
```

### 규약

- Python **3.11+** 문법 허용 (`match`, `Self`, `StrEnum` 등)
- 공개 함수는 **전체 타입 힌트** 필수
- 데이터 모델은 **Pydantic v2** — `model_config` 스타일 (내부 `Config` 클래스 금지)
- I/O는 **async-first** — `httpx.AsyncClient` 사용, `requests` 금지
- 출력은 `rich` 사용 — `print()` 금지
- 경로는 `pathlib.Path` 선호 (`os.path` 지양)
- import 정렬은 ruff(isort 호환)에 위임

### 보안

- 시크릿은 절대 커밋하지 않습니다. 자격 증명은 `.env` + `pydantic-settings`로만 다룹니다.

참고: [`.claude/rules/python-style.md`](./.claude/rules/python-style.md)

---

## 참고 자료 (Source of Truth)

이 문서는 개요이며, 세부 규칙은 아래 파일이 단일 출처입니다.

- [`.claude/rules/agents.md`](./.claude/rules/agents.md) — 서브에이전트 정의와 오케스트레이션
- [`.claude/rules/prompts.md`](./.claude/rules/prompts.md) — 프롬프트 파일 구조와 변경 정책
- [`.claude/rules/testing.md`](./.claude/rules/testing.md) — 테스트 구조, 커버리지, 모킹
- [`.claude/rules/python-style.md`](./.claude/rules/python-style.md) — 코딩 스타일, 타입 힌트, async 패턴
