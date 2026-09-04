import csv
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# .env 파일 로드
load_dotenv()


class FilterOutput(BaseModel):
    query: str = Field(description="필터 조건을 제외한 검색 쿼리")
    filter: str = Field(description="Google Cloud Discovery Engine API EBNF 필터 표현식")


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

    prompt = f"""사용자의 질문에서 Filter와 Query 를 분리해주세요. 
Filter 구문은 Google Cloud Discovery Engine API에서 사용하는 Extended Backus–Naur Form 표현식을 사용해야 합니다. 
적용할 필터 설명: 
 - title: 문서 제목 ex) 1도금 코일 내권부 지관 삽입 협동로봇 개발(제이디_견적서)
 - ecm_file_modify_date: 문서 수정 날짜 ex) 2026-08-10T11:10:12
 - ecm_cabinet_name: 팀명, 부서명, 문서함명 ex) DX기획그룹, 제조인텔리전스그룹, 안전환경그룹
 - ecm_content_source: 출처(메일/결재/문서관리(ECM)) ex) MAIL, ECM, APPROVE
 - ecm_file_format: 파일 확장자, 대소문자가 섞여 있음 ex) PDF, pptx, xlxs, pdf
 - ecm_folder_name: 폴더 이름 ex) '4. 데이터센터', '로봇기획'
 - ECM_OPEN_FLAG_NAME: 공개/비공개 ex) 공개, 비공개
 - ECM_REGIST_DATE: 문서 등록 날짜 ex) 2026-08-10T11:10:12
 - object_name: 파일이름 ex) 업무협조-동력섹션 수봉변 점검용 CCTV.pdf 
 - ecm_security_level_name: 보안등급 (사외비A/사외비B/기밀/일반) ex) 사외비A, 사외비B, 기밀, 일반
 - owner_name: 작성자 이름 ex) 나대엽, 김태성, 이현정
 
 필터 적용 방법
 - "오늘", "어제", "지난주", "지난달", "지난분기", "작년" 과 같은 기간에 대한 내용이 나오면 오늘 날짜({datetime.now().strftime('%Y-%m-%d')}) 를 기준으로 계산해서 ecm_file_modify_date 와 ecm_regist_date 를 OR 로 연결해서 적용. 
 - ecm_folder_name 과 같은 폴더 이름에 따옴표가 있으면 따옴표를 제거하고 검색.
 
 
사용자 질문: {user_query}

example:
user_query: DX기획그룹 문서 중 이정훈 차장이 작성한 추진계획서 PPT 파일
result: 
```json
{
  "query":"추진계획서",
  "filter":"ecm_cabinet_name: ANY(\"DX기획그룹\") AND (owner_name: ANY(\"이정훈\") OR regist_user_name: ANY(\"이정훈\")) AND title: ANY(\"추진계획서\") AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\")"
}
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
    print(f"\n총 {len(queries)}개의 쿼리 테스트 시작...\n" + "=" * 60)
    for idx, q in enumerate(queries, 1):
        print(f"[{idx}] Input Query: {q}")
        try:
            result = get_filter(q, client=client)
            print("Structured Output (JSON):")
            print(result.model_dump_json(indent=2))
            results.append({
                "user_query": q,
                "query": result.query,
                "filters": result.filter,
            })
        except Exception as e:
            print(f"오류 발생: {e}")
            results.append({
                "user_query": q,
                "query": "",
                "filters": f"ERROR: {e}",
            })
        print("-" * 60)

    # result.csv 파일로 결과 저장
    output_file = Path("result.csv")
    with open(output_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["user_query", "query", "filters"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n결과가 {output_file}에 저장되었습니다. (총 {len(results)}건)")


if __name__ == "__main__":
    main()


