# Discovery Engine Filter & Query Extractor (`discovery-filter`)

Google Cloud Discovery Engine API 검색 환경에서 사용자의 자연어 질문을 분석하여 **순수 검색 쿼리(`query`)** 와 **Discovery Engine EBNF(Extended Backus–Naur Form) 필터 표현식(`filter`)**, 그리고 필터 조건과 검색어를 사람이 이해하기 쉽게 풀어 쓴 **한 문장 설명(`desc`)** 을 자동으로 분리 및 추출하는 시스템입니다.

---

## 📌 주요 기능 및 특징

1. **다중 모델 지원 및 Latency 벤치마크 (`gemini-3.5-flash-lite` vs `gemini-3.7-flash`)**
   - 사용자 질문에서 문서 속성을 추출할 때 모델명을 변수로 주입 가능
   - 각 모델 호출 시 응답 시간(Latency, 초 단위)을 정밀 측정(`time.perf_counter()`)
   - **한 문장 설명(`desc`) 자동 생성**: 추출된 EBNF 필터 식의 조건(부서함, 작성자/소유자, 파일 확장자, 등록 기간 등)과 검색 키워드를 사람이 직관적으로 이해할 수 있는 자연스러운 한국어 한 문장으로 해설
   - Pydantic(`FilterOutput`)을 활용한 Structured Output(JSON) 규격 강제
   - 응답 지연 최소화를 위한 `thinking_budget=0` 및 `automatic_function_calling=disable` 설정 적용

2. **사내 ECM 메타데이터 스키마 반영**
   - `ecm_cabinet_name`: 부서명/팀명/문서함 매핑 (ex: DX기획그룹, AX 개발그룹)
   - `owner_name` / `regist_user_name`: 작성자/등록자 처리 (직급 제거 및 `(owner_name: ANY(...) OR regist_user_name: ANY(...))` OR 조건 결합)
   - `ecm_file_format`: 확장자 대소문자 및 관련 형식 일괄 처리 (ex: PPT -> `ANY("ppt", "pptx", "PPT", "PPTX")`, 엑셀 -> `ANY("xls", "xlsx", "XLS", "XLSX", "csv")`)
   - `ecm_regist_date`: 연도/기간 질의 시 ISO-8601 UTC 타임스탬프 범위 필터 생성

3. **자동 검증 및 평가 파이프라인 (`gemini-3.8-flash`)**
   - `gemini-3.8-flash` 모델을 심사관(LLM-as-a-Judge)으로 사용하여 10점 만점 기준으로 생성 결과를 정밀 평가
   - 평가 기준: EBNF 문법 및 필드명 준수(3점) + 조건 반영 충실도(3점) + 검색어 정제도(2점) + 설명(desc) 충실도(2점)
   - 검증 결과를 [score.csv](file:///Users/iloh/source/filter-function/score.csv) 및 [result.csv](file:///Users/iloh/source/filter-function/result.csv)에 `model`, `latency_sec` 필드를 포함하여 자동 저장

---

## 🛠️ 기술 스택

- **언어 및 패키지 관리**: Python 3.14, [`uv`](https://github.com/astral-sh/uv)
- **LLM SDK**: [`google-genai`](https://github.com/googleapis/python-genai) (Vertex AI 연동)
- **비교 분석 모델**:
  - `gemini-3.5-flash-lite`: 초경량 저지연 모델 (평균 Latency: 1.37초)
  - `gemini-3.7-flash`: 고성능 표준 모델 (평균 Latency: 3.73초)
- **검증 모델**: `gemini-3.8-flash`
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

# main.py 실행 (test_query.csv 입력 -> 2개 모델별 쿼리/필터/desc/latency 추출 -> gemini-3.8-flash 검증 -> score.csv 저장)
uv run main.py
```

---

## 📊 모델별 Latency 및 품질 비교 요약

| 지표 | `gemini-3.5-flash-lite` | `gemini-3.7-flash` | 차이 및 분석 |
| :--- | :---: | :---: | :--- |
| **평균 응답 시간 (Latency)** | **1.374초** | 3.731초 | **flash-lite가 약 2.7배 더 빠름** (최대 7.24초 vs 2.81초) |
| **최소 응답 시간** | **0.990초** | 1.779초 | 단순 인명/단문 필터 시 1초 미만 응답 가능 |
| **평균 검증 점수** | 9.89 / 10점 | **10.00 / 10점** | 두 모델 모두 매우 뛰어난 정확도 (3.7-flash는 9건 전건 만점) |
| **10점 만점 비율** | 8 / 9건 (88.9%) | **9 / 9건 (100%)** | 3.7-flash가 복잡한 전문 질의의 불용어 정제에서 미세하게 우세 |

---

## 📋 세부 검증 및 평가 결과 (`score.csv`)

[test_query.csv](file:///Users/iloh/source/filter-function/test_query.csv)의 테스트 질의 9건에 대해 두 모델을 실행한 [score.csv](file:///Users/iloh/source/filter-function/score.csv) 결과입니다:

| No | 사용자 질문 (`user_input`) | 모델 (`model`) | 소요시간 (`latency`) | 추출 검색어 (`query`) | 필터 및 쿼리 설명 (`desc`) | 점수 |
| :---: | :--- | :---: | :---: | :--- | :--- | :---: |
| **1** | AX 개발그룹 문서중에 김태원이 작성한 전사 AX 과제 추진 계획서 ppt 파일 | flash-lite<br>3.7-flash | 2.815s<br>3.444s | 전사 AX 과제 추진 계획서 | AX 개발그룹 문서함에서 김태원이 작성하거나 등록한 파워포인트(PPT) 파일 중 '전사 AX 과제 추진 계획서' 키워드로 검색합니다. | 10/10<br>10/10 |
| **2** | 2023년도에 정재홍이 작성한 엑셀 문서 | flash-lite<br>3.7-flash | 1.304s<br>2.464s | *(빈 값)* | 정재홍이 작성/등록한 2023년 등록 엑셀 파일 중 검색합니다. | 10/10<br>10/10 |
| **3** | 유희영 대리 소유 문서 중에 팀즈 관련 문서 좀 찾아줄래 | flash-lite<br>3.7-flash | 1.085s<br>4.536s | 팀즈 | 소유자 또는 등록자가 유희영인 문서 중 '팀즈' 키워드로 검색합니다. | 10/10<br>10/10 |
| **4** | DX기획그룹 문서 중 이정훈 차장이 작성한 추진계획서 ppt 파일 | flash-lite<br>3.7-flash | 1.298s<br>2.422s | 추진계획서 | DX기획그룹 문서함에서 이정훈이 소유/작성/등록한 파워포인트(PPT) 파일 중 '추진계획서' 키워드로 검색합니다. | 10/10<br>10/10 |
| **5** | 과제명 수소투자 그룹 투자/기획 업무 지원을 위한 AI 기반 정보통합 분석 및 대화형 검색 환경 구축 | flash-lite<br>3.7-flash | 1.158s<br>7.240s | 과제명 수소투자...<br>수소투자 그룹 투자... | 별도 필터 조건 없이 전문 검색합니다. *(3.7-flash는 '과제명' 불용어를 완벽 정제)* | 9/10<br>10/10 |
| **6** | Gemini Enterprise | flash-lite<br>3.7-flash | 1.173s<br>2.269s | Gemini Enterprise | 별도 필터 조건 없이 'Gemini Enterprise' 키워드로 전문 검색합니다. | 10/10<br>10/10 |
| **7** | 오정완 그룹장 문서 | flash-lite<br>3.7-flash | 0.990s<br>1.779s | *(빈 값)* | 소유자 또는 등록자가 오정완인 문서를 검색합니다. | 10/10<br>10/10 |
| **8** | 내가 작성한 2024년 사업계획서 ppt 파일 | flash-lite<br>3.7-flash | 1.227s<br>6.230s | 사업계획서<br>2024년 사업계획서 | 나대엽이 작성/소유한 파워포인트(PPT) 파일 중 검색합니다. | 10/10<br>10/10 |
| **9** | 내 소유 문서 중 클라우드 마이그레이션 보고서 | flash-lite<br>3.7-flash | 1.318s<br>3.198s | 클라우드 마이그레이션 보고서 | 나대엽 소유 문서 중 '클라우드 마이그레이션 보고서' 키워드로 검색합니다. | 10/10<br>10/10 |

---

## 📝 사용된 프롬프트 (Prompts)

### 1. 쿼리 및 필터 & 설명 분리 프롬프트 (`gemini-3.5-flash-lite`)
사용자의 자연어 질의에서 Discovery Engine EBNF 필터, 검색 쿼리, 한 문장 설명(desc)을 추출하기 위해 사용된 프롬프트입니다:

```text
사용자의 질문에서 Filter와 Query를 분리하고, 이를 사람이 이해하기 쉽게 설명하는 desc(한 문장)를 작성해주세요.
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
  - query가 존재하는 경우: 필터 조건과 함께 "'{query}' 키워드로 검색합니다." 형식으로 마무리
  - query가 빈 문자열("")인 경우: 필터 조건을 만족하는 문서를 검색함을 명시 (예: "오정완이 작성자이거나 등록자인 모든 문서를 검색합니다.")
  - filter가 빈 문자열("")인 경우: "별도 필터 조건 없이 '{query}' 키워드로 전문 검색합니다." 형식으로 작성

[내이름]: {my_name}
[오늘 날짜]: {YYYY-MM-DD}

[사용자 질문]: {user_query}

example 1:
user_query: DX기획그룹 문서 중 2026년에 이정훈 차장이 작성한 추진계획서 PPT 파일
result: 
```json
{
  "query":"추진계획서",
  "filter":"ecm_cabinet_name: ANY(\"DX기획그룹\") AND (owner_name: ANY(\"이정훈\") OR regist_user_name: ANY(\"이정훈\")) AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\") AND (ecm_regist_date >= 2026-01-01T00:00:00Z AND ecm_regist_date <= 2026-12-31T23:59:59Z)",
  "desc":"DX기획그룹 문서함에서 이정훈이 작성하거나 등록한 2026년 등록 파워포인트(PPT) 파일 중 '추진계획서' 키워드로 검색합니다."
}
```

example 2:
[내이름]: 나대엽
user_query: 내가 작성한 추진계획서 PPT 파일
result:
```json
{
  "query":"추진계획서",
  "filter":"owner_name: ANY(\"나대엽\") AND ecm_file_format: ANY(\"ppt\", \"pptx\", \"PPTX\", \"PPT\")",
  "desc":"나대엽이 작성/소유한 파워포인트(PPT) 파일 중 '추진계획서' 키워드로 검색합니다."
}
```

example 3:
user_query: 오정완 그룹장 문서
result:
```json
{
  "query":"",
  "filter":"(owner_name: ANY(\"오정완\") OR regist_user_name: ANY(\"오정완\"))",
  "desc":"소유자 또는 등록자가 오정완인 문서를 검색합니다."
}
```

example 4:
user_query: Gemini Enterprise
result:
```json
{
  "query":"Gemini Enterprise",
  "filter":"",
  "desc":"별도 필터 조건 없이 'Gemini Enterprise' 키워드로 전문 검색합니다."
}
```
```

### 2. 결과 검증 및 점수화 프롬프트 (`gemini-3.8-flash`)
추출 결과의 정밀도를 10점 만점 기준으로 객관적 평가하기 위해 사용된 프롬프트입니다:

```text
당신은 Google Cloud Discovery Engine 검색 시스템의 쿼리 및 필터 분리 결과 검증 전문가입니다.
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
```

---

## 📁 프로젝트 파일 구성

- [main.py](file:///Users/iloh/source/filter-function/main.py): 필터 추출(`get_filter`), 검증(`evaluate_filter`), 배치 실행 진입점
- [sample.json](file:///Users/iloh/source/filter-function/sample.json): 사내 ECM 데이터 원본 스키마 샘플
- [test_query.csv](file:///Users/iloh/source/filter-function/test_query.csv): 테스트 입력 자연어 질의 목록
- [score.csv](file:///Users/iloh/source/filter-function/score.csv): `gemini-3.8-flash` 검증 점수, 상세 사유 및 `desc`가 포함된 결과 파일
- [result.csv](file:///Users/iloh/source/filter-function/result.csv): 기본 결과 파일 (`user_input,query,filters,desc,score`)
- [pyproject.toml](file:///Users/iloh/source/filter-function/pyproject.toml): `uv` 프로젝트 의존성 설정 파일
