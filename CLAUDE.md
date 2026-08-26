# 개발 규칙

## 프로젝트
예금·적금·대출 등 여러 금융상품을 한 챗봇에서 비교·상담하는 LLM 에이전트.
스택: Python 3.12 / uv / LangGraph / OpenAI / FastAPI / PostgreSQL+pgvector(SQLAlchemy) / 정적 웹 UI.
데이터 소스: 금융감독원 금융상품통합비교공시 오픈API (finlife.fss.or.kr).

정형 조건(금리·기간)은 API를 실시간 호출하는 비교 도구가, 문장으로 된 조건(우대조건·가입대상)은
배치로 색인한 pgvector 시맨틱 검색이 담당한다. `DATABASE_URL`이 PostgreSQL이 아니면
조건 검색 도구는 스스로 비활성 안내를 반환하고, 나머지 기능은 SQLite로 동작한다.

## TDD (결정적 코드)
- `app/tools`, `app/db`, `app/api`와 라우팅·파싱·권한 로직은 **실패하는 테스트를 먼저** 작성한 뒤 구현한다 (red → green → refactor).
- 테스트 없는 결정적 코드는 커밋하지 않는다.
- 외부 HTTP는 respx로 mock한다. 실 API 호출 테스트는 `@pytest.mark.integration`으로 표시한다 (기본 실행과 CI에서 제외됨).

## Eval (LLM 동작)
- 프롬프트나 그래프 구조를 바꾸면 `uv run python evals/run_evals.py`를 로컬에서 실행해 의도분류 정확도가 떨어지지 않았는지 확인한다. (CI에서는 API 비용 때문에 실행하지 않는다.)

## 구조
- 레이어 의존 방향: `api → agents → tools/db`, `batch → tools/db`. 역방향 import 금지.
- 벡터 테이블은 `VectorBase`(별도 메타데이터)에 둔다. SQLite 테스트 DB에 만들어지면 안 된다.
- `app/tools/`는 LLM 의존성이 없는 순수 함수로 작성하고, httpx 클라이언트를 인자로 주입받는다.
- 프롬프트는 `app/agents/prompts.py`에 상수로 모은다.

## 시크릿
- 모든 키는 `.env`에만 둔다. 코드·로그·테스트 픽스처에 실제 키를 넣지 않는다.
- 설정은 `app/core/config.py`의 `get_settings()`로만 읽는다.

## 커밋
- 기능 단위로 작게 커밋한다. conventional commits (feat / fix / test / chore / docs / refactor).
- 커밋 전 `uv run pre-commit run -a`와 `uv run pytest`가 통과해야 한다.

## 명령어
- 의존성 설치: `uv sync`
- 테스트: `uv run pytest` (integration 포함 실행: `uv run pytest -m integration`)
- 린트/포맷: `uv run ruff check --fix .` / `uv run ruff format .`
- 타입체크: `uv run pyright`
- 서버 실행: `uv run uvicorn app.api.main:app --reload`
- 상품 색인 배치: `uv run python -m app.batch.sync_catalog`
