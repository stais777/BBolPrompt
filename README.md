# 뽈프롬 PromptManager 베이스화·API 승인 참조 개발판

인계받은 Alpha v0.2의 결함을 별도 디렉터리에서 수정하고, 실제 사용 가능한 로컬 앱과 Windows x64 배포본을 구현했습니다. **정식 완료판이라는 뜻은 아닙니다.** 실제 PT 전체 재시험·실제 AI 의미 품질·Windows PC 실행은 아직 검증하지 못했습니다.

## 현재 진행 범위 (2026-11-05)

**시작 시 이전 앱 감지를 보완했습니다.** 같은 포트에 다른 자료 폴더의 뽈프롬이 응답하는 경우를 구분하고, 실제 이전 앱이면 해당 화면을 열어 [앱 종료]할 수 있도록 합니다. 현재 오류 이유·주소를 Windows 오류창에 표시하고 실행 시각/버전을 기록합니다. [범위·시험·사용자 재확인](docs/STARTUP_RECOVERY.md).

**자료를 프로그램 옆 data 폴더에 모으는 휴대형 보관**을 구현했습니다. 첫 PT 등록 시 원본 전체를 보관하고, 신규 카드별 원문·원본이미지와 태그 수정 이력을 함께 옮깁니다. 기존 사용자 자료는 복사·검증 후 가져옵니다. [배치·기존자료 이사·업데이트 안내](docs/PORTABLE_STORAGE.md).

**최초309개 정답을 보존하면서 사용자 수동 태그 수정·이력·원본 복원을 구현했습니다.** API 자동 재분석은 차단하고 최신 사용자 확정본은 선택한 신규 카드 사례 참고에 연결합니다. [사용법·보존·검증 범위](docs/BASELINE_TAG_EDITING.md). 그 외 후속 엔진 개선은 별도 범위입니다.

Windows 등록 시 접근 거부를 일으킬 수 있는 임시 백업 DB 연결 수명과 검토창 내 오류 표시를 수정했습니다. [재현·수정·검증 범위](docs/WINDOWS_REGISTRATION_FIX.md). 309개 기준과 태그/하이라이팅 판단은 유지하며, 실제 베이스파일 저장의 재확정 전 후속 엔진 개선은 보류합니다.

로컬 PT 재분리는 중단했습니다. 승인 기록 대조와 API 방법론 연결에 이어 **고정309카드의 SQLite 베이스화 등록·확정 PT의531이미지 참조 연결**을 구현했습니다. 같은 원문을 가진 역사적 카드도 각각 유지합니다. [등록 경로·시험 범위](docs/BASELINE_REGISTRATION.md), [승인 기록 분석](docs/APPROVAL_HISTORY_AUDIT.md), [추가 누락22항목 대조](docs/GAP_AUDIT_REVIEW.md)를 확인하세요. 원본 마스터/카탈로그는 불변입니다. 이후 사용자 요청으로 **UI인계 v0.8을 분석·적용**했습니다. [UI 반영·인수 범위](docs/UI_IMPLEMENTATION.md)를 확인하세요.0.3.8-startupfix 실행 배포본에는 이 변경을 포함합니다.

## 실제 PT 오류와 이전 Windows 배포판

사용자 PC에서 실제 PT 반입 검토 결과가 **495개**로 확인됐습니다. 초기 갤러리의 309개는 로컬 승인 자료를 미리 표시한 것이며 추출 성공 결과가 아닙니다. 이전0.3.1 배포판은 오류 카드로 이동하는 안내와 **구조 진단 ZIP 저장**, 선택적 **승인 카드 원문→태그→근거 API 사례 참조**를 보완합니다. **495→309 분리 문제가 해결됐다는 버전은 아닙니다.** [변경 내용과 진단 방법](docs/0.3.1-diagnostic.md)을 확인하세요.

## 다운로드

- [Windows 프로그램 ZIP](https://github.com/stais777/BBolPrompt/raw/refs/heads/main/downloads/Bbolprom-Windows-x64-v0.3.8-startupfix.zip)
- [이전0.3.1 소스·테스트 ZIP](https://github.com/stais777/BBolPrompt/raw/refs/heads/main/downloads/Bbolprom-Source-v0.3.1-diagnostic.zip)
- [검증 결과](docs/VALIDATION.md)
- [배포 ZIP SHA256](downloads/ARTIFACT_SHA256.json)

비공개 저장소라면 접근 권한이 있는 GitHub 계정으로 로그인한 상태에서 받으세요. 다운로드가 바로 시작되지 않으면 `downloads` 폴더에서 ZIP 파일을 연 뒤 **Download raw file**을 선택하세요.

## Windows 사용

`dist/Bbolprom-Windows-x64-v0.3.8-startupfix.zip` 전체를 짧은 경로(예: `C:\Bbolprom`)에 풀고 **Bbolprom.exe**를 실행합니다. Python 별도 설치가 필요 없습니다. EXE와 `app`, `runtime` 폴더를 함께 유지하세요. 로컬 기본 브라우저가 UI로 열리며 데이터는 **프로그램 폴더의 `data`**에 저장됩니다. 이전 기본 저장소 `%LOCALAPPDATA%\Bbolprom`은 최초 복사 원본으로만 사용하며 그대로 보존합니다. 종료는 화면의 **앱 종료** 버튼을 사용합니다.

이 EXE는 실제 PE32+ Windows x64 프로그램으로 교차 빌드했습니다. Windows에서 실행해 확인한 결과는 없습니다. `test_windows.ps1`은 파일 무결성·번들 Python·HWPX/Unicode/SQLite·실제 EXE 시작/HTTP 응답을 점검하는 Windows용 실행 시험입니다. 빌드와 Windows 실행을 구분하십시오. 단일 EXE에 모든 파일을 합친 형식은 아니며 Python을 포함한 폴더형 독립 배포입니다.

## 구현한 경로

- 현재 소스의 기본 반입은 베이스화 전용입니다. 확정 PT의 전체 SHA를 검사하고 고정522경로/531참조로 연결합니다. 309개로 다시 분리하지 않으며 다른/갱신 파일은 기존 데이터를 보존하고 거절합니다.
- 이전 구조 기반 HWPX 진단 경로: 표 행·페이지/섹션·이미지 배치 사용, 중첩 문단 중복 수집 방지, 원문 공백/줄바꿈/코드포인트 및 원본 미디어 바이트 보존. 모호한 경계는 경고하고 검토창에서 병합·분리·이미지 귀속을 조정합니다.
- 원문 동일성은 UTF-8 SHA256으로 판정합니다. 이미지 MD5+SHA1+SHA256을 확인하고 같은 원문에는 이미지를 추가합니다. 다른 파일명/중복 반입도 출처 이력을 보존합니다. 원본 이름은 메타데이터로만 저장하고 실제 경로는 짧은 ID를 사용합니다.
- 첫 화면 승인 309카드 읽기 전용 갤러리, 신규 카드 등록, 보기 4종·테마 5종, 인스펙터 이미지 휠 전환, 태그명 부분검색 후보 선택·AND 필터, 다중 근거 하이라이팅. 승인 이미지 바이트는 인계물에 없어 처음에는 참조만 표시하고, 확정 PT 이미지 연결 등록 후 원본을 표시합니다.
- 승인 카드와 동일한 신규 원문은 별도 사용자 데이터의 이미지/출처 overlay로 연결합니다. 기존 309카드를 합치거나 태그를 다시 쓰지 않습니다. 승인 309 중 원문이 동일한 카드가 복수인 경우 임의 귀속하지 않고 사용자가 대상을 선택합니다.
- 신규 카드 태그 직접 수정, 미분류 및 빈 근거 보존. API 오류/JSON 오류는 기존 카드·태그를 지우지 않습니다.
- SQLite 거래, 온라인 DB 백업과 미디어를 포함하는 `.bak.zip`, 새 XLSX 내보내기(카드·사용자 추가 분류·통합태그색인·원문근거). 확정 XLSX 파일은 쓰지 않습니다.
- API-POLICY-1.0 어댑터: 기본 꺼짐/명시적 외부 전송 동의, 모델·HTTPS endpoint·호출/출력/비용 한도, 사용자 분류 정의, 관련 승인 이력 검색, 구조화 JSON 검증, 기존 ID/명칭/분류 검증, 신규/미분류/근거 검증, 재시도 자동 반복 없음.

## 승인 자료와 운영/평가 분리

원본 인계 ZIP과 `/workspace/bbolprompt-handoff`는 수정하지 않았습니다. 최종 XLSX의 SHA256은 `b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe`입니다. 감사 도구는 manifest 120개 파일, 309카드·8,471매핑·2,200고유 태그·10,358근거 및 승인된 빈 근거 17건을 검증합니다.

- `bbolprom_engine/baseline.py`:고정ID/원문/태그를 DB에 등록하고 확정 매니페스트로 이미지를 연결합니다. 베이스화이며 독립 추출 성능으로 평가하지 않습니다.
- `bbolprom_engine/analysis.py`, `hwpx.py`: 이전 진단 반입. 승인 원문/정답과 대조하여 경계를 강제하지 않습니다.
- `bbolprom_engine/api.py`, `approved_context.py`, `data/approved_context.json`: 승인 XLSX 출처·행을 보존한 표준 태그와 실제 승인 판단 이력 285행. 관련 일부만 API에 전달하며 이것 자체를 태그 정답으로 반환하지 않습니다.
- `assets/approved_catalog.json`: **고정 베이스화/갤러리/API선택적참조용** 승인 원문·태그·근거. 반입 분리에는 전달하지 않습니다. API 설정에서 관련 승인 사례 참조를 명시적으로 켠 경우에만 관련 원문·태그·근거를 소수 검색해 API에 제공합니다.
- `evaluation/compare.py`, `evaluation/reference/`: 평가에서만 원문/카드별 정답을 읽습니다. Windows 배포에는 포함하지 않습니다.
- CLI `analyze`의 generic/approved_terms와 `tags.py`는 기존 A/B와 비교하기 위한 **규칙 진단**입니다. 의미 판단을 구현했다고 취급하지 않습니다. 앱은 규칙 진단 태그를 자동 등록하지 않습니다. `registry.py`는 이전 Alpha 시험 API 호환용으로만 남겨두었으며 새 앱과 CLI 등록은 `library.py`를 사용합니다.

## API 설정

API는 기본 꺼짐입니다. 키는 API 설정창의 전용 비밀번호 입력칸으로 등록·교체·삭제하며 Windows 자격 증명 관리자에만 보관합니다. 일반 설정·DB·백업·진단 ZIP에 저장하지 않고 기존 환경변수도 읽지 않습니다. 공식 `https://api.openai.com/v1/chat/completions`로만 전송하며 선택 모델은 `gpt-6.1-sol`입니다. [보안 구현·시험 범위](docs/API_KEY_SECURITY.md)를 확인하세요. Windows 보관함의 실제 동작과 실 API 호환성은 아직 검증하지 않았습니다.

초기 C~I는 승인 표시명만 있습니다. 확정 문서에는 완전한 분류 정의가 없으므로 만들어낸 정의를 사용자 승인 사실로 넣지 않았습니다. API에 보낼 분류 정의·포함/제외는 사용자가 설정창에서 확정할 수 있습니다. 새 대분류를 API가 만들 수 없으며 재활성화의 자동 복귀 정책을 전역으로 임의 확정하지 않습니다. UI의 재활성화 버튼은 **태그 자동 복귀 없음**이라는 명시적 개별 선택입니다.

전송 범위는 선택한 신규 카드 원문·활성 분류 정의·관련 표준 태그 및 승인 판단 이력 일부입니다. 승인 전체 원문, 실제 이미지 바이트, 평가 전용 정답 파일은 전송하지 않습니다. 관련 승인 사례 참조를 켜면 로컬 승인 카드의 원문 발췌·태그·근거가 최대 3건 추가됩니다. 전체 309카드를 일괄 전송하지 않습니다. API 키가 제공되지 않아 이번에는 실제 API를 호출하지 않았습니다. 모의 응답 시험은 의미 품질 측정이 아닙니다.

## 개발/시험 재현

Python 3.12 이상 표준 라이브러리로 앱과 시험을 실행할 수 있습니다. Python 설치 안내는 개발자용이며 Windows 최종 사용자는 번들 EXE를 사용합니다.

```sh
python -m bbolprom_engine.app --self-test
python -m bbolprom_engine.app --data /tmp/bbolprom-user --no-browser
python -m unittest discover -s tests -v
python evaluation/audit_handoff.py --handoff /path/to/extracted/handoff
python evaluation/structural_regression.py --handoff /path/to/extracted/handoff
node scripts/browser_smoke.js
node scripts/baseline_browser_smoke.js
node scripts/ui_handoff_browser_smoke.js
python scripts/build_windows.py --version 0.3.8-startupfix
python scripts/package_source.py --version 0.3.1-diagnostic
python scripts/verify_windows_bundle.py
```

일부 제한된 실행환경에서는 localhost 소켓/Chromium 실행 허용이 필요합니다. 브라우저 시험은 설치된 Playwright와 Chromium을 사용하며 기본 경로/환경변수는 스크립트를 참고하세요. `build_windows.py --offline`은 처음 받은 검증 완료 캐시를 재사용합니다. 원격 Python 런타임은 PSF NuGet SHA512, 컴파일러는 고정된 SHA256으로 검증하며 TLS를 끄지 않습니다.

현재 기본 흐름은 앱의 **확정 PT 이미지 연결**입니다. 아래 명령은 남겨둔 과거 구조 진단용이며 사용자가 중단한 로컬 재분리 작업의 재개 지침이 아닙니다. 실제 API 의미 분석은 신규 카드의 별도 명시적 호출입니다.

```sh
python -m bbolprom_engine test-pt --input PT.hwpx --out outputs/PT --baseline evaluation/reference/approved_baseline_309.json
```

공식 실제 PT SHA: `c5d52ce0cda5901d9da178f88c8d5c2eeb5614eefa5a0546916e4951df881ddf`. 다른 파일/합성 자료의 수치를 실제 PT 개선으로 보고하지 않습니다.

## 검증 결과와 남은 한계

`docs/ANALYSIS.md`, `docs/VALIDATION.md`, `evaluation/`의 실행 로그와 JSON을 확인하세요. 기존 다문단 회귀는 4→2카드, 중첩 표 회귀는 3카드/4참조→2카드/2참조로 수정했으며, 각 회귀의 원문·이미지 귀속은 2/2 일치합니다. 이 결과를 실제 A/B의 개선율로 확대해석하지 않습니다.

- 실제 605MB PT.hwpx가 없어 309/531 전체 재추출, 카드별 실제 이미지 귀속, 태그/근거 재현율 개선은 미측정입니다.
- 실제 API 호출/의미 태그 품질과 비용은 미측정입니다. 중복 근거 구절은 모든 실제 일치 구간을 표시하고 모호성 경고를 남깁니다. API 응답의 문맥별 단일 위치 선택은 완전히 연결되지 않았습니다.
- Windows 네이티브 실행·UI·실제 긴 경로 동작은 미검증입니다. 긴 이름을 짧은 저장 경로로 바꾸는 동작과 Unicode Windows 런처 manifest는 별도 검증했습니다. Windows 독립 실행에 성공했다고 보고하지 않습니다.
- 구조 기반 분리는 일반 HWPX의 완전한 의미 경계 판독기가 아닙니다. 모호한 문서에는 검토가 필요합니다. 인계물에 없는 승인 이미지 원본을 복원하거나 대신 생성하지 않았습니다.
- 다중 카드 태그 일괄 편집, 자동 업데이트/코드서명/설치 마법사는 구현하지 않았습니다. 직접 태그 수정, Windows 자격 증명 관리자 키 보관, 폴더형 배포를 제공합니다. Windows 보관함은 Win32 호출 모의시험만 수행했으며 실제 Windows 시험은 남아 있습니다.

## 로컬 PT 진단 로그

현재 버전에서는 좌측의 **진단 로그 내보내기**와 반입 검토창의 같은 버튼으로 작은 ZIP을 저장할 수 있습니다. 성공/실패·PT SHA256·309개 고정ID/원문해시/태그·근거개수·531참조/522경로·원본에서 측정한 이미지해시와 저장파일 재검증·DB상태·실행OS/버전을 기록합니다. 원문·이미지·XML·DB·API키는 포함하지 않고 자동 전송하지 않습니다. 저장된 ZIP을 사용자가 채팅에 첨부하면 진단할 수 있습니다. 상세 범위는 [진단 안내](docs/LOCAL_DIAGNOSTICS.md)를 확인하세요.
