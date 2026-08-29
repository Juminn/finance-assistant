"""pytest 전역 설정.

테스트 프로세스에서는 LangSmith 트레이싱을 강제로 끈다.

app.api.main은 import 시점에 load_dotenv()로 .env를 프로세스 환경에 올리는데,
.env에 LANGSMITH_TRACING=true가 있으면 그 뒤 langchain 도구·그래프를 invoke하는
모든 테스트가 LangSmith에 트레이스로 남는다 (pre-commit의 pytest 실행 포함).
conftest는 테스트 모듈보다 먼저 import되고, load_dotenv는 기본값(override=False)으로
이미 있는 환경변수를 덮어쓰지 않으므로 여기서 미리 꺼두면 전체 실행이 차단된다.
"""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
