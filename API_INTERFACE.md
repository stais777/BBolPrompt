# API 연결과 검증 범위

`bbolprom_engine.api.analyze_card(card_ref, text, categories, tags, context=None, transport=None, config=None, examples=None)`은 카드 원문과 읽기 전용 맥락을 받아 검증한 태그만 반환한다. DB를 열거나 마스터를 수정하지 않는다. 기본값은 API 비활성이다.

- `categories`: `{id, name, definition, enabled, include?, exclude?, definition_revision?}`. 사용자가 확정한 정의가 없는 분류와 비활성 분류는 요청에서 제외한다. 분류명을 정의로 꾸미지 않는다.
- `tags`: 최신 `{id, name, category_id}` 표준 태그 목록. 같은 ID의 대표명/분류가 응답에서 임의 변경되면 거부 또는 미분류로 보존한다.
- `context`: `load_approved_context()` 결과 또는 같은 스키마의 읽기 전용 승인 사례. 원문 정답 조회 데이터가 아니다.
- `transport`: 테스트용 `callable(request)->response_dict_or_json`. 제공하면 결과 `mode=mock`이며 실제 API 성능 검증으로 취급할 수 없다.
- `examples`: `retrieve_approved_examples(text, enabled=True)`로 명시 선택한 관련 승인 카드 사례 목록. 생략하면 승인 카드 원문을 읽거나 전송하지 않는다. 앱은 API 전송 동의와 별도로 `use_approved_examples` 선택을 저장한다. 기존 API 동의 설정만으로 원문 사례를 추가 전송하지 않는다.
- `config`: `APIConfig(enabled=True, consent=True, endpoint='https://공급자/v1/chat/completions', model='사용자가 선택한 모델', key_env='BBOLPROM_API_KEY', timeout=30, max_calls=10, ...)`. OpenAI 호환 Chat Completions 구조화 응답을 사용하는 공급자용이다. 공급자별 호환성은 실제 호출 전까지 확인되지 않았다.

반환은 `{card_ref, source_text, status, tags, unclassified, warnings, usage, mode}`이다. 태그에는 API 정보와 엔진 호환 `tag/category_column/spans/source`가 있다. `spans`는 Python Unicode codepoint 기준 `[start_cp,end_cp)`이다. 동일 구절의 모든 정확한 출현을 반환한다. 반복 구절에는 `evidence_ambiguous`와 경고를 남긴다. 서로 다른 문맥의 반복 표현은 의미적 귀속까지 확정된 것이 아니다. `select_evidence_spans(text,quote,prefix=...,suffix=...)`는 인접한 정확한 원문 문맥으로 한 위치를 선택하며, 선택 결과가 없거나 여러 개이면 거부한다. 이 보조 선택자는 현재 API 기본 응답 스키마의 별도 필드로 연결하지 않았다. API에는 구별할 수 있는 더 긴 실제 인용을 요청한다. 존재하지 않는 구절이나 빈 근거는 태그를 삭제하지 않고 0구간 미분류로 보존한다. 브라우저는 `Array.from(text)`로 표시해야 한다.

`status`는 `ok`, `partial`, `api_disabled`, `api_unavailable`, `invalid_response`이다. 오류 시 원문을 그대로 반환하며 API 재호출을 자동 반복하지 않는다. HTTP 오류의 응답 본문·인증 헤더·키는 로그와 결과에 포함하지 않는다. 인증키는 지정한 프로세스 환경변수에서만 읽고 설정 JSON에 저장하지 않는다. 설정 생성 시 숫자의 자료형·유한성·범위와 비밀값이 없는 HTTPS 엔드포인트를 검사한다. HTTPS 검증과 상속된 네트워크 프록시를 유지하며 인증 헤더 유출을 막기 위해 API 리디렉션을 거부한다.

호출 수, 출력 토큰, 타임아웃을 제한할 수 있다. 비용 상한을 켜면 사용자가 해당 공급자/모델의 입출력 단가를 함께 지정해야 한다. 입력 UTF-8 바이트 수와 최대 출력 토큰으로 보수적으로 비용을 예약한다. 정상 응답에 입출력 사용량이 있으면 해당 단가로 비용을 조정하고 누적 사용량을 기록한다. 실패하거나 사용량이 없는 호출은 보수적인 예약 비용을 유지한다. 실패한 호출도 호출 수에서 차감한다. 실 청구액이 아니라 세션 보호 한도이며, 청구 내역은 공급자가 결정한다.

승인 사례 스냅샷은 SHA256 검증을 통과한 최종 XLSX의 `B_001-309_최종승인사전`, `C_001-150_승인사전29종`, `가로_다음차수적용기준`, `가로2차_다음차수적용기준`에서 추출한 285행이다. 파일명·워크북 SHA·시트·행 번호를 보존한다. 2,209개의 분류/명칭 표준 행에는 고유 명칭 2,200개가 있다. 같은 명칭이 여러 분류에 존재하는 기존 충돌을 임의 수정하지 않는다. 검색은 관련 사례를 고르는 어휘 기반 검색이며, 의미 판단 자체는 API가 맡는다. 사례를 무조건 치환 규칙으로 실행하거나 태그 검색 별칭 DB로 사용하지 않는다. 원문 정답·카드별 태그 매핑·이미지·형광펜은 스냅샷에 포함하지 않았다.

`CategoryManager`는 복사본에서만 분류 정책을 편집한다. 정의 변경은 기존 태그를 바꾸지 않는다. 비활성화는 이력과 근거를 보존하고 소속만 null로 옮긴다. 재활성화의 자동 복귀는 미확정 정책이므로 메서드는 `restore_tags=True/False`라는 사용자의 명시 선택이 없으면 오류를 낸다. 앱 저장 계층은 `snapshot()` 결과를 별도로 저장해야 한다.

`tests/test_api_v3.py`는 모의 응답과 연결 오류를 검증한다. 실제 API 키를 사용한 의미 정확도·부정/의도 해석 정확도·요금·공급자 호환성을 검증한 것이 아니다. 이 테스트의 통과를 A/B 태그 재현율 개선 수치로 보고하면 안 된다.


## 관련 승인 카드의 원문→태그→근거 사례

최신 사용자 요청에 따라 라벨과 정규화 이력뿐 아니라, 로컬 309카드에서 관련 **승인 원문·태그·정확한 근거**를 찾아 신규 카드 API의 참고 사례로 제공하는 경로를 추가했다. `approved_examples.py`의 `retrieve_approved_examples(text, enabled=False, catalog_path=None, catalog=None, ...)`는 기본 비활성이며, 켠 경우에만 읽기 전용 `assets/approved_catalog.json`을 연다. 기본 경로는 패키지 루트 기준이라 Windows 배포에도 같은 경로를 쓴다. 원문 반입·카드 분리와 독립 A/B 비교 엔진에서는 이 모듈을 호출하지 않는다.

반환 한도는 관련 카드 최대 3개, 카드별 실제 원문 최대 4,000 Unicode codepoint, 카드별 관련 승인 태그 최대 20개, 전체 사례 JSON 최대 12,000자다. 긴 원문은 실제 근거 근처의 **변경 없는 연속 부분 문자열**만 제공한다. 발췌의 원본 `[start_cp,end_cp)`, 원문 전체 SHA, 발췌 SHA를 구분하고, 각 근거에 원본 좌표와 발췌 기준 좌표를 모두 보존한다. 원래 근거가 발췌 밖에 있으면 해당 매핑을 보내지 않으며, 승인 당시 직접 근거가 0개였던 매핑은 근거 없음 상태를 그대로 보존한다. 이미지 바이트는 읽거나 보내지 않는다.

각 사례는 승인 카드 번호, 승인 마스터 SHA, 실제 카탈로그 바이트 SHA, 파일명과 함께 제공한다. 입력과 **완전히 같은 승인 원문은 SHA와 문자열로 제외**하며, 외부 요청 구성 단계에서도 다시 제외한다. 이것은 유사 사례를 찾아 판단 방법을 참고하는 기능이다. 관련 태그를 정답으로 강제하거나 309개 마스터를 신규 원문에 맞춰 재작성하는 기능이 아니다. 과거 사례의 분류 ID는 그때의 승인 이력을 나타내며, 신규 카드 분류에는 현재 활성 사용자 정의가 우선한다. 과거 분류를 현행 정의로 다시 작성하지 않는다.

API 기본 응답 스키마는 그대로이며, 요청에 `approved_card_examples`만 추가했다. `analyze_card(..., examples=사례목록)`과 `build_request(..., examples=사례목록)`은 전달된 사례의 필드·근거 문자열·원본/발췌 좌표·출처 SHA 형식·공개 분량을 다시 검사한다. API 어댑터가 자체적으로 카탈로그를 열거나 암묵적으로 사례 전송을 시작하지 않는다. 기존 표준 태그 ID는 원래와 동일하게 `std-` + SHA256(분류 ID + NUL + 대표명)의 앞 16자다.

`tests/test_api_examples.py`의 9개 테스트는 opt-in, 원문·근거·출처, 실제 카탈로그 불변, 정확히 같은 원문 제외, 분량 제한, 긴 원문 코드포인트 좌표와 모의 API 요청 연결을 검증했다. 이 테스트는 실제 API 호출·새 원문 의미 판단 품질·A/B 재현율 개선을 검증하지 않았다.
