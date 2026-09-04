# Discovery Engine Filter & Query Extractor (`discovery-filter`)

Google Cloud Discovery Engine API 검색 환경에서 사용자의 자연어 질문을 분석하여 **순수 검색 쿼리(`query`)** 와 **Discovery Engine EBNF(Extended Backus–Naur Form) 필터 표현식(`filter`)** 을 자동으로 분리 및 추출하는 시스템입니다.

---

## 📌 주요 기능 및 특징

1. **Gemini 기반 Query & Filter 분리 (`gemini-3.5-flash-lite`)**
   - 사용자 질문에서 문서 속성(부서, 작성자, 확장자, 등록일자 등)을 추출하여 Discovery Engine EBNF 표현식으로 변환
   - 속성 메타데이터를 제외한 실제 검색 대상 키워드만 `query`로 정제
   - Pydantic을 활용한 Structured Output(JSON) 규격 강제
   - 응답 지연 최소화를 위한 `thinking_budget=0` 및 `automatic_function_calling=disable` 설정 적용

2. **사내 ECM 메타데이터 스키마 반영**
   - `ecm_cabinet_name`: 부서명/팀명/문서함 매핑 (ex: DX기획그룹, AX 개발그룹)
   - `owner_name` / `regist_user_name`: 작성자/등록자 처리 (직급 제거 및 `(owner_name: ANY(...) OR regist_user_name: ANY(...))` OR 조건 결합)
   - `ecm_file_format`: 확장자 대소문자 및 관련 형식 일괄 처리 (ex: PPT -> `ANY("ppt", "pptx", "PPT", "PPTX")`, 엑셀 -> `ANY("xls", "xlsx", "XLS", "XLSX", "csv")`)
   - `ecm_regist_date`: 연도/기간 질의 시 ISO-8601 UTC 타임스탬프 범위 필터 생성

3. **자동 검증 및 평가 파이프라인 (`gemini-3.8-flash`)**
   - `gemini-3.8-flash` 모델을 심사관(LLM-as-a-Judge)으로 사용하여 10점 만점 기준으로 생성 결과를 정밀 평가
   - 평가 기준: EBNF 문법 및 필드명 준수(4점) + 조건 반영 충실도(3점) + 검색어 정제도(3점)
   - 검증 결과를 [score.csv](file:///Users/iloh/source/filter-function/score.csv) 및 [result.csv](file:///Users/iloh/source/filter-function/result.csv)로 자동 저장

---

## 🛠️ 기술 스택

- **언어 및 패키지 관리**: Python 3.14, [`uv`](https://github.com/astral-sh/uv)
- **LLM SDK**: [`google-genai`](https://github.com/googleapis/python-genai) (Vertex AI 연동)
- **사용 모델**:
  - 추출: `gemini-3.5-flash-lite`
  - 검증: `gemini-3.8-flash`
- **데이터 파싱/검증**: `pydantic`, `python-dotenv`

---

## 🚀 빠른 시작 (Getting Started)

### 1. 환경 설정
`.env` 파일에 Google Cloud 프로젝트 및 리전을 설정합니다.
```bash
cp .env.sample .env
```

`.env` 내용 예시:
```env
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global  # 또는 us-central1
GOOGLE_GENAI_USE_VERTEXAI=true
```

Google Cloud 인증(ADC):
```bash
gcloud auth application-default login
```

### 2. 패키지 설치 및 실행
```bash
# 의존성 설치
uv sync

# main.py 실행 (test_query.csv 입력 -> 쿼리/필터 추출 -> gemini-3.8-flash 검증 -> score.csv 저장)
uv run main.py
```

---

## 📊 검증 및 평가 결과 (`score.csv`)

[test_query.csv](file:///Users/iloh/source/filter-function/test_query.csv)의 테스트 질의 5건에 대한 [score.csv](file:///Users/iloh/source/filter-function/score.csv) 추출 및 검증 결과입니다:

| No | 사용자 질문 (`user_input`) | 추출 검색어 (`query`) | 추출 필터 (`filters`) | 점수 (`score`) | 검증 사유 (`reason`) |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **1** | AX 개발그룹 문서중에 김태원이 작성한 전사 AX 과제 추진 계획서 ppt 파일 | 전사 AX 과제 추진 계획서 | `ecm_cabinet_name: ANY("AX 개발그룹") AND (owner_name: ANY("김태원") OR regist_user_name: ANY("김태원")) AND ecm_file_format: ANY("ppt", "pptx", "PPT", "PPTX")` | **10 / 10** | 부서(`ecm_cabinet_name`), 작성자/등록자 OR 조건, 파일 확장자 대소문자 변형 처리가 EBNF 문법에 완벽히 부합하며, 핵심 키워드만 query로 깔끔하게 추출됨. |
| **2** | 2023년도에 정재홍이 작성한 엑셀 문서 | *(빈 문자열)* | `(owner_name: ANY("정재홍") OR regist_user_name: ANY("정재홍")) AND ecm_file_format: ANY("xls", "xlsx", "XLS", "XLSX", "csv") AND (ecm_regist_date >= 2023-01-01T00:00:00Z AND ecm_regist_date <= 2023-12-31T23:59:59Z)` | **10 / 10** | 작성자, 엑셀 확장자, 2023년 연도 범위가 EBNF 문법에 맞게 모두 필터로 변환됨. 질문의 모든 요소가 메타데이터로 분리되어 query를 빈 문자열로 정제한 처리가 완벽함. |
| **3** | 유희영 대리 소유 문서 중에 팀즈 관련 문서 좀 찾아줄래 | 팀즈 | `owner_name: ANY("유희영")` | **10 / 10** | 소유자 조건에서 직급('대리')을 제거하고 `owner_name` 필터로 정확히 추출함. 조사/어미를 제외하고 실제 검색 대상인 '팀즈'만 깔끔하게 검색어로 남김. |
| **4** | DX기획그룹 문서 중 이정훈 차장이 작성한 추진계획서 ppt 파일 | 추진계획서 | `ecm_cabinet_name: ANY("DX기획그룹") AND (owner_name: ANY("이정훈") OR regist_user_name: ANY("이정훈")) AND ecm_file_format: ANY("ppt", "pptx", "PPT", "PPTX")` | **10 / 10** | 부서, 작성자/등록자 OR 조건, 파일 형식(ppt/pptx) 조건이 누락 없이 정확히 반영되었으며, 검색어도 '추진계획서'로 정제됨. |
| **5** | 과제명 수소투자 그룹 투자/기획 업무 지원을 위한 AI 기반 정보통합 분석 및 대화형 검색 환경 구축 | 과제명 수소투자 그룹 투자/기획 업무 지원을 위한 AI 기반 정보통합 분석 및 대화형 검색 환경 구축 | *(필터 없음)* | **9 / 10** | 메타데이터 조건이 없어 필터를 빈 값으로 둔 것은 정확함. 다만 질의 앞부분의 단순 레이블성 접두어인 '과제명'을 제거하고 핵심 제목만 남겼다면 더욱 좋았을 것이라는 피드백으로 1점 감점. |

---

## 📝 사용된 프롬프트 (Prompts)

### 1. 쿼리 및 필터 분리 프롬프트 (`gemini-3.5-flash-lite`)
사용자의 자연어 질의에서 Discovery Engine EBNF 필터와 검색 쿼리를 분리하기 위해 사용된 프롬프트입니다:

```text
사용자의 질문에서 Filter와 Query를 분리해주세요.
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

[오늘 날짜]: {YYYY-MM-DD}

[사용자 질문]: {user_query}

example:
user_query: DX기획그룹 문서 중 2026년에 이정훈 차장이 작성한 추진계획서 PPT 파일
result: 
```json
{
  "query":"추진계획서",
  "filter":"ecm_cabinet_name: ANY(\"DX기획그룹\") AND owner_name: ANY(\"이정훈\") AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\") AND (ecm_regist_date >= 2026-01-01T00:00:00Z AND ecm_regist_date <= 2026-12-31T23:59:59Z)"
}
```
```

### 2. 결과 검증 및 점수화 프롬프트 (`gemini-3.8-flash`)
추출 결과의 정밀도를 10점 만점 기준으로 객관적 평가하기 위해 사용된 프롬프트입니다:

```text
당신은 Google Cloud Discovery Engine 검색 시스템의 쿼리 및 필터 분리 결과 검증 전문가입니다.
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
```

---

## 📁 프로젝트 파일 구성

- [main.py](file:///Users/iloh/source/filter-function/main.py): 필터 추출(`get_filter`), 검증(`evaluate_filter`), 배치 실행 진입점
- [sample.json](file:///Users/iloh/source/filter-function/sample.json): 사내 ECM 데이터 원본 스키마 샘플
- [test_query.csv](file:///Users/iloh/source/filter-function/test_query.csv): 테스트 입력 자연어 질의 목록
- [score.csv](file:///Users/iloh/source/filter-function/score.csv): `gemini-3.8-flash` 검증 점수 및 상세 사유가 포함된 결과 파일
- [result.csv](file:///Users/iloh/source/filter-function/result.csv): 기본 결과 파일 (`user_input,query,filters,score`)
- [pyproject.toml](file:///Users/iloh/source/filter-function/pyproject.toml): `uv` 프로젝트 의존성 설정 파일
