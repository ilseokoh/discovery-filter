import csv
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from datetime import datetime

# .env 파일 로드
load_dotenv()


class FilterOutput(BaseModel):
    query: str = Field(description="필터 조건을 제외한 검색 쿼리")
    filter: str = Field(description="Google Cloud Discovery Engine API EBNF 필터 표현식")


class EvaluationOutput(BaseModel):
    score: int = Field(description="10점 만점 기준 점수 (0-10)")
    reason: str = Field(description="점수 평가 이유 및 피드백")


def get_client() -> genai.Client:
    """환경 변수에 따라 Vertex AI (Google Cloud Project) 또는 Gemini Developer API 클라이언트를 반환합니다."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if project_id:
        return genai.Client(vertexai=True, project=project_id, location=location)
    return genai.Client()


def get_filter(user_query: str, client: genai.Client | None = None) -> FilterOutput:
    """사용자 입력 쿼리를 받아 Gemini 모델을 호출하여 Query와 Filter를 분리한 구조화된 결과를 반환합니다."""
    if client is None:
        client = get_client()

    prompt = f"""사용자의 질문에서 Filter와 Query를 분리해주세요.
Filter 구문은 Google Cloud Discovery Engine API의 Extended Backus–Naur Form (EBNF) 표현식을 사용해야 합니다.

[사용 가능한 필터 필드]
- title: 문서 제목 (특정 제목이 명시된 경우에만 사용)
- ecm_cabinet_name: 팀명, 부서명, 문서함명 (ex: DX기획그룹, 제조인텔리전스그룹)
- ecm_folder_name: 폴더 이름 (ex: 로봇기획, 데이터센터 - 따옴표 제외)
- owner_name: 소유자/작성자 이름 (ex: 나대엽, 김태성)
- regist_user_name: 등록자 이름 (ex: 나대엽, 강성민)
- ecm_file_format: 파일 확장자 (대소문자/변형 포함 ex: ANY("ppt", "pptx", "PPT", "PPTX"))
- ecm_file_modify_date: 문서 수정 일시 (ISO-8601 형식)
- ecm_regist_date: 문서 등록 일시 (ISO-8601 형식)
- ecm_content_source: 출처 (MAIL, ECM, APPROVE)
- ecm_security_level_name: 보안등급 (사외비A, 사외비B, 기밀, 일반)
- ecm_open_flag_name: 공개 여부 (공개, 비공개)

[필터 생성 규칙]
1. 작성자/담당자 조건: (owner_name: ANY("이름") OR regist_user_name: ANY("이름")) 형태로 생성
2. 기간 조건: "오늘", "작년" 등이 주어지면 ecm_regist_date 또는 ecm_file_modify_date에 UTC 타임스탬프 범위(>=, <=)를 적용
3. 확장자 조건
  - 파워포인트/PPT: ANY("ppt", "pptx", "PPT", "PPTX")
  - 엑셀/스프레드시트: ANY("xls", "xlsx", "XLS", "XLSX", "csv")
  - 워드/문서: ANY("doc", "docx", "DOC", "DOCX", "hwp", "HWP")
  - 이미지: ANY("jpg", "jpeg", "png", "JPG", "PNG")
4. 일반 검색 키워드는 query 필드에 남기고, 명확한 메타데이터 조건만 filter 필드에 적용

[오늘 날짜]: {datetime.now().strftime('%Y-%m-%d')}

[사용자 질문]: {user_query}

example:
user_query: DX기획그룹 문서 중 2026년에 이정훈 차장이 작성한 추진계획서 PPT 파일
result: 
```json
{{
  "query":"추진계획서",
  "filter":"ecm_cabinet_name: ANY(\"DX기획그룹\") AND owner_name: ANY(\"이정훈\") AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\") AND (ecm_regist_date >= 2026-01-01T00:00:00Z AND ecm_regist_date <= 2026-12-31T23:59:59Z)"
}}
```
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FilterOutput,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    return response.parsed


def evaluate_filter(user_query: str, query: str, filters: str, client: genai.Client | None = None) -> EvaluationOutput:
    """gemini-3.8-flash 모델을 사용하여 query와 filter 분리 결과를 10점 만점 기준으로 검증합니다."""
    if client is None:
        client = get_client()

    eval_prompt = f"""당신은 Google Cloud Discovery Engine 검색 시스템의 쿼리 및 필터 분리 결과 검증 전문가입니다.
사용자 질문(user_query)을 바탕으로 생성된 검색어(query)와 필터 표현식(filters)을 10점 만점 기준으로 엄격하게 평가해주세요.

[평가 기준]
1. 필터 필드 및 EBNF 문법 정확성 (4점):
   - Google Cloud Discovery Engine EBNF 문법(ANY, AND, OR, >=, <= 등) 준수 여부
   - 올바른 필드명(ecm_cabinet_name, owner_name, regist_user_name, ecm_file_format, ecm_regist_date 등) 사용 여부
2. 조건 반영 충실도 (3점):
   - 사용자 질문에 명시된 작성자/소유자, 부서, 확장자, 기간 등의 조건이 필터에 빠짐없이 정확히 반영되었는가?
3. 검색어(query) 정제도 (3점):
   - 필터 조건으로 분리된 속성을 제외하고 실제 검색할 핵심 키워드만 query로 남겼는가?
   - 질문에 필터링할 메타데이터가 없고 전문 검색이어야 하는 경우 filters가 비어있고 query에 전문이 들어가는 것이 적절함.

[검증 대상]
- 사용자 질문: {user_query}
- 생성된 쿼리: {query}
- 생성된 필터: {filters}
"""

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=eval_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EvaluationOutput,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    return response.parsed


def main():
    csv_file = Path("test_query.csv")
    if not csv_file.exists():
        print(f"Error: {csv_file} 파일이 존재하지 않습니다.")
        return

    queries = []
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            query = row.get("query", "").strip()
            if query:
                queries.append(query)

    if not queries:
        print("테스트할 쿼리가 없습니다.")
        return

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    api_key = os.environ.get("GEMINI_API_KEY")

    if project_id:
        print(f"Using Google Cloud Project: {project_id} (Location: {os.environ.get('GOOGLE_CLOUD_LOCATION', 'us-central1')})")
    elif api_key:
        print("Using GEMINI_API_KEY")
    else:
        print("GOOGLE_CLOUD_PROJECT 또는 GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.")
        return

    # 클라이언트 재사용
    client = get_client()

    results = []
    print(f"\n총 {len(queries)}개의 쿼리 테스트 및 gemini-3.8-flash 검증 시작...\n" + "=" * 60)
    for idx, q in enumerate(queries, 1):
        print(f"[{idx}] Input Query: {q}")
        try:
            result = get_filter(q, client=client)
            print("Structured Output (JSON):")
            print(result.model_dump_json(indent=2))

            # gemini-3.8-flash 모델을 사용하여 결과 검증 및 10점 만점 점수화
            eval_result = evaluate_filter(q, result.query, result.filter, client=client)
            print(f"Validation Score: {eval_result.score}/10 (이유: {eval_result.reason})")

            results.append({
                "user_input": q,
                "query": result.query,
                "filters": result.filter,
                "score": eval_result.score,
                "reason": eval_result.reason,
            })
        except Exception as e:
            print(f"오류 발생: {e}")
            results.append({
                "user_input": q,
                "query": "",
                "filters": f"ERROR: {e}",
                "score": 0,
                "reason": f"오류 발생: {e}",
            })
        print("-" * 60)

    # score.csv 파일로 검증 결과 저장
    score_file = Path("score.csv")
    with open(score_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["user_input", "query", "filters", "score", "reason"])
        writer.writeheader()
        writer.writerows(results)

    # result.csv 파일도 호환성을 위해 저장
    result_file = Path("result.csv")
    with open(result_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["user_input", "query", "filters", "score"])
        writer.writeheader()
        writer.writerows([{k: v for k, v in r.items() if k != "reason"} for r in results])

    print(f"\n검증 결과가 {score_file}에 저장되었습니다. (총 {len(results)}건)")


if __name__ == "__main__":
    main()



