# 금융 통합 비서 (Finance Assistant)

예금·적금·주택담보대출·전세자금대출·개인신용대출 등 여러 금융상품을 한곳에서 비교하고
상담해주는 LLM 에이전트 챗봇입니다.

- 데이터 소스: 금융감독원 금융상품통합비교공시 오픈API (finlife.fss.or.kr)
- 에이전트: LangGraph 멀티 에이전트 (의도분류 supervisor + 상품군별 worker)
- 서빙: FastAPI + 웹 채팅 UI

> 개발 진행 중입니다. 아키텍처와 실행 방법은 추후 업데이트됩니다.
