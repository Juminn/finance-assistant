# 금융 통합 비서 (Finance Assistant)

예금·적금·주택담보대출·전세자금대출·개인신용대출 등 여러 금융상품을 한곳에서 비교하고
상담해주는 LLM 에이전트 챗봇입니다.

- **데이터**: 금융감독원 금융상품통합비교공시 오픈API (finlife.fss.or.kr)
- **에이전트**: LangGraph 멀티 에이전트 — supervisor(의도분류) + 상품군별 worker
- **서빙**: FastAPI + 웹 채팅 UI, 대화이력 SQLite 저장, 응답 PII 마스킹

## 실행 방법

```bash
# 1. 의존성 설치 (uv 필요: https://docs.astral.sh/uv/)
uv sync

# 2. 환경변수 설정 — .env.example을 복사해 키를 채운다
#    OPENAI_API_KEY / FINLIFE_API_KEY
cp .env.example .env

# 3. 서버 실행 후 http://localhost:8000 접속
uv run uvicorn app.api.main:app --reload
```

데모 로그인 계정: `demo` / `demo1234!`

## 개발

| 작업 | 명령 |
| --- | --- |
| 단위 테스트 | `uv run pytest` |
| 실 API 통합 테스트 | `uv run pytest -m integration` |
| 린트/포맷 | `uv run ruff check --fix .` · `uv run ruff format .` |
| 타입체크 | `uv run pyright` |
| 의도분류 eval | `uv run python evals/run_evals.py` |

- 결정적 코드(도구·DB·API·권한)는 TDD, LLM 동작은 골든셋 eval로 검증합니다.
- 커밋 시 pre-commit 훅이 lint → typecheck → test를 강제합니다. (`uv run pre-commit install`)

## 구조

```
app/
  core/    설정, 보안(해시·토큰), PII 마스킹
  tools/   금융상품 API 순수 함수 (LLM 의존성 없음)
  agents/  LangGraph 그래프, 프롬프트, 도구 바인딩
  db/      SQLAlchemy 모델·저장소 (사용자, 토큰, 대화이력)
  api/     FastAPI 라우터 (인증, 챗, 이력)
web/       정적 채팅 UI
evals/     의도분류 골든셋과 채점 스크립트
tests/     unit(mock 기반) / integration(실 API)
```
