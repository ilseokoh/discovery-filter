import csv
import os
import time
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
    desc: str = Field(description="filter 식의 조건과 query 검색어를 사람이 쉽게 이해할 수 있도록 풀어서 설명한 한 문장")


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


def get_filter(
    user_query: str,
    model: str = "gemini-3.5-flash-lite",
    my_name: str = "나대엽",
    client: genai.Client | None = None,
) -> tuple[FilterOutput, float]:
    """사용자 입력 쿼리를 받아 지정된 Gemini 모델을 호출하여 Query와 Filter를 분리하고 한 문장 설명(desc) 및 응답 시간(latency_sec)을 반환합니다."""
    if client is None:
        client = get_client()

    prompt = f"""사용자의 질문에서 Filter와 Query를 분리하고, 이를 사람이 이해하기 쉽게 설명하는 desc(한 문장)를 작성해주세요.
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
1. 작성자/담당자 조건: (owner_name: ANY("이름") OR regist_user_name: ANY("이름")) 형태로 생성 ("그룹장", "팀장", "대리", "차장", "부장", "님" 등 직급/호칭은 제외하고 성명만 추출)
2. 본인 지칭 조건: "내", "나의", "내가 작성한", "내가 소유한" 등 owner_name(소유자/작성자)을 나로 지칭한 경우 owner_name 필터를 [내이름] 값으로 적용 (ex: owner_name: ANY("{my_name}"))
3. 기간 조건: "오늘", "작년" 등이 주어지면 ecm_regist_date 또는 ecm_file_modify_date에 UTC 타임스탬프 범위(>=, <=)를 적용
4. 확장자 조건
  - 파워포인트/PPT: ANY("ppt", "pptx", "PPT", "PPTX")
  - 엑셀/스프레드시트: ANY("xls", "xlsx", "XLS", "XLSX", "csv")
  - 워드/문서: ANY("doc", "docx", "DOC", "DOCX", "hwp", "HWP")
  - 이미지: ANY("jpg", "jpeg", "png", "JPG", "PNG")
5. 불용어 및 검색어(query) 정제:
  - "문서", "파일", "자료", "내용", "내", "내가 작성한" 등 검색 대상의 일반 지칭어나 단순 명사는 query에서 반드시 제외
  - 메타데이터 조건을 제외하고 남은 유효한 검색 키워드가 없는 경우, query는 빈 문자열("")로 설정
6. 설명(desc) 작성 규칙:
  - filter 식의 조건(부서/문서함, 작성자/소유자, 확장자, 등록일시 등)과 query 검색어를 조합하여 사람이 이해할 수 있는 자연스러운 한국어 '한 문장'으로 작성
  - filter 식에 적용된 조건 내용을 구체적으로 풀어서 설명 (예: "ecm_cabinet_name: ANY(\"DX기획그룹\")" -> "DX기획그룹 문서함에서", "ecm_file_format: ANY(...)" -> "파워포인트(PPT) 파일 중", "owner_name: ANY(\"나대엽\")" -> "나대엽 소유/작성", "2026-01-01..." -> "2026년 등록된")
  - query가 존재하는 경우: 필터 조건과 함께 "'{{query}}' 키워드로 검색합니다." 형식으로 마무리
  - query가 빈 문자열("")인 경우: 필터 조건을 만족하는 문서를 검색함을 명시 (예: "오정완이 작성자이거나 등록자인 모든 문서를 검색합니다.")
  - filter가 빈 문자열("")인 경우: "별도 필터 조건 없이 '{{query}}' 키워드로 전문 검색합니다." 형식으로 작성

[내이름]: {my_name}
[오늘 날짜]: {datetime.now().strftime('%Y-%m-%d')}

[사용자 질문]: {user_query}

example 1:
user_query: DX기획그룹 문서 중 2026년에 이정훈 차장이 작성한 추진계획서 PPT 파일
result: 
```json
{{
  "query":"추진계획서",
  "filter":"ecm_cabinet_name: ANY(\"DX기획그룹\") AND (owner_name: ANY(\"이정훈\") OR regist_user_name: ANY(\"이정훈\")) AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\") AND (ecm_regist_date >= 2026-01-01T00:00:00Z AND ecm_regist_date <= 2026-12-31T23:59:59Z)",
  "desc":"DX기획그룹 문서함에서 이정훈이 작성하거나 등록한 2026년 등록 파워포인트(PPT) 파일 중 '추진계획서' 키워드로 검색합니다."
}}
```

example 2:
[내이름]: 나대엽
user_query: 내가 작성한 추진계획서 PPT 파일
result:
```json
{{
  "query":"추진계획서",
  "filter":"owner_name: ANY(\"나대엽\") AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\")",
  "desc":"나대엽이 작성/소유한 파워포인트(PPT) 파일 중 '추진계획서' 키워드로 검색합니다."
}}
```

example 3:
user_query: 오정완 그룹장 문서
result:
```json
{{
  "query":"",
  "filter":"(owner_name: ANY(\"오정완\") OR regist_user_name: ANY(\"오정완\"))",
  "desc":"소유자 또는 등록자가 오정완인 문서를 검색합니다."
}}
```

example 4:
user_query: Gemini Enterprise
result:
```json
{{
  "query":"Gemini Enterprise",
  "filter":"",
  "desc":"별도 필터 조건 없이 'Gemini Enterprise' 키워드로 전문 검색합니다."
}}
```
"""

    start_time = time.perf_counter()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FilterOutput,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    latency_sec = time.perf_counter() - start_time

    return response.parsed, round(latency_sec, 3)


def evaluate_filter(user_query: str, query: str, filters: str, desc: str = "", my_name: str = "나대엽", client: genai.Client | None = None) -> EvaluationOutput:
    """gemini-3.8-flash 모델을 사용하여 query, filter, desc 분리 결과를 10점 만점 기준으로 검증합니다."""
    if client is None:
        client = get_client()

    eval_prompt = f"""당신은 Google Cloud Discovery Engine 검색 시스템의 쿼리 및 필터 분리 결과 검증 전문가입니다.
사용자 질문(user_query)을 바탕으로 생성된 검색어(query), 필터 표현식(filters), 설명(desc)을 10점 만점 기준으로 엄격하게 평가해주세요.

[평가 기준]
1. 필터 필드 및 EBNF 문법 정확성 (3점):
   - Google Cloud Discovery Engine EBNF 문법(ANY, AND, OR, >=, <= 등) 준수 여부
   - 올바른 필드명(ecm_cabinet_name, owner_name, regist_user_name, ecm_file_format, ecm_regist_date 등) 사용 여부
2. 조건 반영 충실도 (3점):
   - 사용자 질문에 명시된 작성자/소유자("내", "내가 작성한" 등 본인 지칭 시 [내이름] 반영 포함), 부서, 확장자, 기간 등의 조건이 필터에 빠짐없이 정확히 반영되었는가?
3. 검색어(query) 정제도 (2점):
   - 필터 조건으로 분리된 속성을 제외하고 실제 검색할 핵심 키워드만 query로 남겼는가?
   - 질문에 필터링할 메타데이터가 없고 전문 검색이어야 하는 경우 filters가 비어있고 query에 전문이 들어가는 것이 적절함.
4. 설명(desc) 작성 충실도 (2점):
   - filter 식의 조건(부서, 작성자/소유자, 확장자, 기간 등)과 query 검색어를 사람이 알기 쉽게 한 문장으로 충실하게 풀어서 설명했는가?

[검증 대상]
- 사용자 질문: {user_query}
- 사용자 이름: {my_name}
- 생성된 쿼리: {query}
- 생성된 필터: {filters}
- 생성된 설명: {desc}
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
    my_name = os.environ.get("MY_NAME", "나대엽")

    # 비교 테스트할 모델 목록
    models_to_test = ["gemini-3.5-flash-lite", "gemini-3.7-flash"]

    results = []
    print(f"\n총 {len(queries)}개 쿼리 x {len(models_to_test)}개 모델 ({', '.join(models_to_test)}) Latency 및 품질 비교 테스트 시작 (기본 사용자명: {my_name})...\n" + "=" * 70)

    for idx, q in enumerate(queries, 1):
        print(f"\n[{idx}/{len(queries)}] Input Query: {q}")
        for model_name in models_to_test:
            print(f"  ▶ Model: {model_name}")
            try:
                result, latency_sec = get_filter(q, model=model_name, my_name=my_name, client=client)
                print(f"    - Latency: {latency_sec:.3f}초")
                print(f"    - Query: '{result.query}'")
                print(f"    - Filter: '{result.filter}'")
                print(f"    - Desc: '{result.desc}'")

                # gemini-3.8-flash 모델을 사용하여 결과 검증 및 10점 만점 점수화
                eval_result = evaluate_filter(q, result.query, result.filter, desc=result.desc, my_name=my_name, client=client)
                print(f"    - Validation Score: {eval_result.score}/10 (이유: {eval_result.reason})")

                results.append({
                    "user_input": q,
                    "model": model_name,
                    "latency_sec": latency_sec,
                    "query": result.query,
                    "filters": result.filter,
                    "desc": result.desc,
                    "score": eval_result.score,
                    "reason": eval_result.reason,
                })
            except Exception as e:
                print(f"    - 오류 발생: {e}")
                results.append({
                    "user_input": q,
                    "model": model_name,
                    "latency_sec": None,
                    "query": "",
                    "filters": f"ERROR: {e}",
                    "desc": f"오류 발생: {e}",
                    "score": 0,
                    "reason": f"오류 발생: {e}",
                })
        print("-" * 70)

    # 모델별 통계 요약
    print("\n" + "=" * 70)
    print("📊 모델별 Latency 및 품질 비교 요약")
    print("=" * 70)
    for model_name in models_to_test:
        model_results = [r for r in results if r["model"] == model_name]
        latencies = [r["latency_sec"] for r in model_results if isinstance(r["latency_sec"], (int, float))]
        scores = [r["score"] for r in model_results if isinstance(r["score"], (int, float))]

        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        min_lat = min(latencies) if latencies else 0.0
        max_lat = max(latencies) if latencies else 0.0
        avg_score = sum(scores) / len(scores) if scores else 0.0
        perfect_count = sum(1 for s in scores if s == 10)

        print(f"[{model_name}]")
        print(f"  - 평균 응답 시간(Latency): {avg_lat:.3f}초 (최소: {min_lat:.3f}초 / 최대: {max_lat:.3f}초)")
        print(f"  - 평균 검증 점수: {avg_score:.2f} / 10점 (만점 비율: {perfect_count}/{len(scores)}건)")
    print("=" * 70)

    # score.csv 파일로 검증 결과 저장
    score_file = Path("score.csv")
    with open(score_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["user_input", "model", "latency_sec", "query", "filters", "desc", "score", "reason"])
        writer.writeheader()
        writer.writerows(results)

    # result.csv 파일도 호환성을 위해 저장
    result_file = Path("result.csv")
    with open(result_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["user_input", "model", "latency_sec", "query", "filters", "desc", "score"])
        writer.writeheader()
        writer.writerows([{k: v for k, v in r.items() if k != "reason"} for r in results])

    print(f"\n검증 결과가 {score_file} 및 {result_file}에 저장되었습니다. (총 {len(results)}건)")


if __name__ == "__main__":
    main()



