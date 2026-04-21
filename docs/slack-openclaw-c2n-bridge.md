# Slack · OpenClaw · confluence-to-notion 브리지 — 에이전트 핸드오프

회사 내부 에이전트/구현팀이 **채팅 기반 규칙 반영 + Confluence → Notion 마이그레이션**을 구성할 때 참고하는 요약 문서다.  
이 레포(`confluence-to-notion`, 이하 **c2n**)는 **마이그레이션 엔진 + MCP**를 제공하고, **슬랙 대화 → 규칙 JSON** 브리지는 **본 레포 밖에서** 만든다는 전제다.

---

## 1. 목표 유저 플로우 (의도)

1. 사용자가 **Slack**(또는 OpenClaw가 붙은 채널)에서 자연어로 요구·검토·질문을 한다.  
2. **OpenClaw**가 대화를 처리하고, 필요 시 **다음 단계**(파일 쓰기, 스크립트, MCP 호출)를 실행한다.  
3. 대화에서 정리된 요구가 **마이그레이션 규칙**(`rules.json`으로 이어지는 산출물)에 반영된다.  
4. 같은 규칙으로 **사내 Confluence → Notion** 변환이 수행된다.  
5. 이상적인 그림은 **채팅에만 응답했는데 노션 반영까지 끝난 상태**이나, **보안·품질**상 완전 무인보다 **`dry_run` + 사람 승인** 한 번을 두는 편이 현실적이다.

---

## 2. 이 레포가 하는 일 / 하지 않는 일

### 2.1 이 레포가 제공하는 것

- **stdio MCP 서버** `c2n-mcp`: 도구로 `c2n_resolve_url`, `c2n_migrate`, `c2n_discover`, `c2n_fetch`, `c2n_convert`, `c2n_list_runs`, `c2n_status` 등 (README `MCP 설치` 참고).
- **CLI**: `uv run c2n …` — `finalize`, `migrate`, `convert`, `validate-output` 등.
- **규칙 확정**: `uv run c2n finalize output/proposals.json` → `rules.json` (및 검증 경로).
- **마이그레이션**: Confluence URL + `rules.json` 기준으로 Notion 반영.

### 2.2 이 레포가 기본으로 하지 않는 것

- **Slack 스레드 텍스트만으로** `rules.json`을 자동 생성하는 파이프라인은 **없다**.  
- **Discover(규칙 자동 발견)** 는 **Confluence 샘플/XHTML**과 `scripts/discover.sh` 기준이며, **채팅 로그를 입력으로 삼지 않는다**.

따라서 **“대화 → 규칙”** 은 **별도 브리지(회사 측 코드/스킬)** 의 책임이다.

---

## 3. Discover와 Claude Code CLI (중요)

- `scripts/discover.sh`는 **`claude -p`(Claude Code CLI)** 를 서브프로세스로 실행한다.  
- **OpenClaw가 쓰는 챗 LLM**(GPT 등)과는 별개다. Discover를 돌리려면 **해당 실행 환경에 `claude` CLI 설치·인증**이 필요하다.  
- **`output/rules.json`이 이미 있고** 마이그레이션만 할 때는, rediscover를 쓰지 않으면 **런타임에 Claude CLI가 없어도** convert/migrate 쪽은 동작시키기 쉽다.

**브리지 설계 시 선택지**

| 전략 | 설명 |
|------|------|
| A. 대화 기반 규칙만 쓴다 | LLM/에디터로 `proposals.json` 작성 → `finalize` → `migrate`. Discover는 생략 가능할 수 있음(스키마·품질은 팀 책임). |
| B. Discover와 병행 | Confluence 샘플로 `discover.sh` 실행 → `rules.json` + (필요 시) 브리지에서 만든 제안과 **병합 정책**을 팀이 정함. |

---

## 4. OpenClaw와 MCP 연결 (개념)

- OpenClaw 설정의 **`mcp.servers`** 에 stdio 서버로 등록한다.  
- **`cwd`(또는 `workingDirectory`)는 반드시 이 레포의 루트 절대 경로** — `c2n-mcp`가 자식 프로세스를 레포 루트 기준으로 실행한다 (README MCP 섹션).  
- 예시 형태 (실제 키 이름은 OpenClaw 버전 문서 따름):

```json
{
  "mcp": {
    "servers": {
      "c2n": {
        "command": "uv",
        "args": ["run", "c2n-mcp"],
        "cwd": "C:\\path\\to\\confluence-to-notion"
      }
    }
  }
}
```

- 레포 루트에 **`.env`** (Confluence / Notion 자격 증명 등) 필요.

---

## 5. Windows + 보안 가이드 (순수 Windows, WSL 없음)

- **Discover**는 **`bash scripts/discover.sh`** 이므로 **Bash**가 필요하다.  
- **Git for Windows(Git Bash)** 등 회사가 허용한 Bash 환경에서 `bash`가 PATH에 잡혀 있어야 한다.  
- 레포 경로는 **공백·비ASCII 최소화** 권장.  
- OpenClaw·Claude Code CLI·`uv`는 **같은 머신**에서 동작 확인 후 MCP `cwd`와 일치시킬 것.

---

## 6. MVP 브리지 — 이 레포 변경 최소화

회사 측 브리지만으로도 **레포 수정 없이** 갈 수 있는 최소 경로:

1. 브리지가 대화/승인 결과를 **`output/proposals.json`** (스키마 만족)으로 쓴다.  
2. `uv run c2n finalize output/proposals.json` → **`rules.json`**.  
3. `uv run c2n validate-output …` 등으로 검증 (CLI/README 참고).  
4. `uv run c2n migrate --url …` 또는 MCP `c2n_migrate`로 Notion 반영 (`dry_run` 먼저 권장).

이후 **레포에 손대고 싶어지는 경우**는 선택 사항이다. 예: MCP에 proposals 본문을 직접 넘기는 도구, `proposals` 병합/수리 서브커맨드, discover 산출과의 merge 정책을 코드화 등.

---

## 7. 현실적인 운영 가드

- **대화만으로 규칙 JSON이 항상 맞지 않음** → 스키마 검증 실패 시 재시도·사람 확인.  
- **어떤 Confluence URL/범위를 옮길지**는 채팅만으로 모호할 수 있음 → 명시적 URL 목록·스페이스·승인 단계 권장.  
- **민감 데이터**가 LLM/로그에 남지 않도록 회사 정책에 맞게 브리지·호스트·토큰 범위를 제한한다.

---

## 8. 용어 정리

| 용어 | 설명 |
|------|------|
| OpenClaw | 개인/팀 에이전트 런타임(구 Moltbot 등 이전 명칭과 동일 계열). 채널·MCP·스킬로 확장. |
| c2n / confluence-to-notion | 본 레포. Confluence XHTML → Notion 블록 규칙 + 변환 + MCP. |
| Discover | `discover.sh` + Claude Code CLI 기반 규칙 제안 파이프라인. |
| 브리지 | 회사가 구현하는 **Slack/OpenClaw ↔ proposals/finalize/migrate** 오케스트레이션. |

---

## 9. 참고 (레포 내부)

- `README.md` — MCP 설치, CLI, 워크플로우.  
- `CLAUDE.md` — 에이전트·discover·eval 정책.  
- `scripts/discover.sh` — `claude -p` 호출부.

---

*이 문서는 대화 기반으로 작성된 핸드오프용 요약이며, 구현 시 최신 README·CLI 도움말을 우선한다.*
