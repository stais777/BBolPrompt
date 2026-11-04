# 뽈프롬 PromptManager 0.3 개발판

인계받은 Alpha v0.2의 결함을 별도 디렉터리에서 수정하고, 실제 사용 가능한 로컬 앱과 Windows x64 배포본을 구현했습니다. **정식 완료판이라는 뜻은 아닙니다.** 실제 PT 전체 재시험·실제 AI 의미 품질·Windows PC 실행은 아직 검증하지 못했습니다.

## 다운로드

- [Windows 프로그램 ZIP](https://github.com/stais777/BBolPrompt/raw/refs/heads/main/downloads/Bbolprom-Windows-x64-v0.3.zip)
- [소스·테스트 ZIP](https://github.com/stais777/BBolPrompt/raw/refs/heads/main/downloads/Bbolprom-Source-v0.3.zip)
- [검증 결과](docs/VALIDATION.md)
- [배포 ZIP SHA256](downloads/ARTIFACT_SHA256.json)

비공개 저장소라면 접근 권한이 있는 GitHub 계정으로 로그인한 상태에서 받으세요. 다운로드가 바로 시작되지 않으면 `downloads` 폴더에서 ZIP 파일을 연 뒤 **Download raw file**을 선택하세요.

## Windows 사용

`dist/Bbolprom-Windows-x64-v0.3.zip` 전체를 짧은 경로(예: `C:\Bbolprom`)에 풀고 **Bbolprom.exe**를 실행합니다. Python 별도 설치가 필요 없습니다. EXE와 `app`, `runtime` 폴더를 함께 유지하세요. 로컬 기본 브라우저가 UI로 열리며 데이터는 `%LOCALAPPDATA%\Bbolprom`에 저장됩니다. 종료는 화면의 **앱 종료** 버튼을 사용합니다.

이 EXE는 실제 PE32+ Windows x64 프로그램으로 교차 빌드했습니다. Windows에서 실행해 확인한 결과는 없습니다. `test_windows.ps1`은 파일 무결성·번들 Python·HWPX/Unicode/SQLite·실제 EXE 시작/HTTP 응답을 점검하는 Windows용 실행 시험입니다. 빌드와 Windows 실행을 구분하십시오. 단일 EXE에 모든 파일을 합친 형식은 아니며 Python을 포함한 폴더형 독립 배포입니다.

## 구현한 경로

- 구조 기반 HWPX 반입: 표 행·페이지/섹션·이미지 배치 사용, 중첩 문단 중복 수집 방지, 원문 공백/줄바꿈/코드포인트 및 원본 미디어 바이트 보존. 모호한 경계는 경고하고 검토창에서 병합·분리·이미지 귀속을 조정합니다.
- 원문 동일성은 UTF-8 SHA256으로 판정합니다. 이미지 MD5+SHA1+SHA256을 확인하고 같은 원문에는 이미지를 추가합니다. 다른 파일명/중복 반입도 출처 이력을 보존합니다. 원본 이름은 메타데이터로만 저장하고 실제 경로는 짧은 ID를 사용합니다.
- 첫 화면 승인 309카드 읽기 전용 갤러리, 신규 카드 등록, 보기 4종·테마 5종, 인스펙터 이미지 휠 전환, 태그명 부분검색 후보 선택·AND 필터, 다중 근거 하이라이팅. 승인 이미지 바이트는 인계물에 없어 **이미지 참조만** 표시합니다.
- 승인 카드와 동일한 신규 원문은 별도 사용자 데이터의 이미지/출처 overlay로 연결합니다. 기존 309카드를 합치거나 태그를 다시 쓰지 않습니다. 승인 309 중 원문이 동일한 카드가 복수인 경우 임의 귀속하지 않고 사용자가 대상을 선택합니다.
- 신규 카드 태그 직접 수정, 미분류 및 빈 근거 보존. API 오류/JSON 오류는 기존 카드·태그를 지우지 않습니다.
- SQLite 거래, 온라인 DB 백업과 미디어를 포함하는 `.bak.zip`, 새 XLSX 내보내기(카드·사용자 추가 분류·통합태그색인·원문근거). 확정 XLSX 파일은 쓰지 않습니다.
- API-POLICY-1.0 어댑터: 기본 꺼짐/명시적 외부 전송 동의, 모델·HTTPS endpoint·호출/출력/비용 한도, 사용자 분류 정의, 관련 승인 이력 검색, 구조화 JSON 검증, 기존 ID/명칭/분류 검증, 신규/미분류/근거 검증, 재시도 자동 반복 없음.

## 승인 자료와 운영/평가 분리

원본 인계 ZIP과 `/workspace/bbolprompt-handoff`는 수정하지 않았습니다. 최종 XLSX의 SHA256은 `b59c80d08222f33e8d2e23964e88ec2432153c3a12db48a14c788dc730284fbe`입니다. 감사 도구는 manifest 120개 파일, 309카드·8,471매핑·2,200고유 태그·10,358근거 및 승인된 빈 근거 17건을 검증합니다.

- `bbolprom_engine/analysis.py`, `hwpx.py`: 운영 반입. 승인 원문/정답과 대조하여 경계를 강제하지 않습니다.
- `bbolprom_engine/api.py`, `approved_context.py`, `data/approved_context.json`: 승인 XLSX 출처·행을 보존한 표준 태그와 실제 승인 판단 이력 285행. 관련 일부만 API에 전달하며 이것 자체를 태그 정답으로 반환하지 않습니다.
- `assets/approved_catalog.json`: **갤러리 표시 전용** 승인 원문·태그·근거. 반입 분리와 API에는 전달하지 않습니다.
- `evaluation/compare.py`, `evaluation/reference/`: 평가에서만 원문/카드별 정답을 읽습니다. Windows 배포에는 포함하지 않습니다.
- CLI `analyze`의 generic/approved_terms와 `tags.py`는 기존 A/B와 비교하기 위한 **규칙 진단**입니다. 의미 판단을 구현했다고 취급하지 않습니다. 앱은 규칙 진단 태그를 자동 등록하지 않습니다. `registry.py`는 이전 Alpha 시험 API 호환용으로만 남겨두었으며 새 앱과 CLI 등록은 `library.py`를 사용합니다.

## API 설정

프로그램 내 API·분류 창에서 공급자의 HTTPS Chat Completions endpoint와 모델을 설정하고 외부 전송에 동의합니다. 키 값은 UI/소스/ZIP/로그에 넣지 말고 Windows 사용자 환경변수 또는 보안 저장소에서 주입한 프로세스 환경으로 제공하십시오. 기본 변수명은 `BBOLPROM_API_KEY`입니다. 키 이름만 설정에 저장합니다.

초기 C~I는 승인 표시명만 있습니다. 확정 문서에는 완전한 분류 정의가 없으므로 만들어낸 정의를 사용자 승인 사실로 넣지 않았습니다. API에 보낼 분류 정의·포함/제외는 사용자가 설정창에서 확정할 수 있습니다. 새 대분류를 API가 만들 수 없으며 재활성화의 자동 복귀 정책을 전역으로 임의 확정하지 않습니다. UI의 재활성화 버튼은 **태그 자동 복귀 없음**이라는 명시적 개별 선택입니다.

전송 범위는 선택한 신규 카드 원문·활성 분류 정의·관련 표준 태그 및 승인 판단 이력 일부입니다. 승인 전체 원문, 실제 이미지 바이트, 평가 정답은 전송하지 않습니다. API 키가 제공되지 않아 이번에는 실제 API를 호출하지 않았습니다. 모의 응답 시험은 의미 품질 측정이 아닙니다.

## 개발/시험 재현

Python 3.12 이상 표준 라이브러리로 앱과 시험을 실행할 수 있습니다. Python 설치 안내는 개발자용이며 Windows 최종 사용자는 번들 EXE를 사용합니다.

```sh
python -m bbolprom_engine.app --self-test
python -m bbolprom_engine.app --data /tmp/bbolprom-user --no-browser
python -m unittest discover -s tests -v
python evaluation/audit_handoff.py --handoff /path/to/extracted/handoff
python evaluation/structural_regression.py --handoff /path/to/extracted/handoff
node scripts/browser_smoke.js
python scripts/build_windows.py
python scripts/verify_windows_bundle.py
```

일부 제한된 실행환경에서는 localhost 소켓/Chromium 실행 허용이 필요합니다. 브라우저 시험은 설치된 Playwright와 Chromium을 사용하며 기본 경로/환경변수는 스크립트를 참고하세요. `build_windows.py --offline`은 처음 받은 검증 완료 캐시를 재사용합니다. 원격 Python 런타임은 PSF NuGet SHA512, 컴파일러는 고정된 SHA256으로 검증하며 TLS를 끄지 않습니다.

실제 PT가 제공되면 다음 명령으로 **먼저 원본 SHA**와 구조 분리를 재시험할 수 있습니다. 결과는 규칙 진단이며 실제 API 의미 분석은 앱의 별도 명시적 호출입니다.

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
- 다중 카드 태그 일괄 편집, OS 키체인 직접 연동, 자동 업데이트/코드서명/설치 마법사는 구현하지 않았습니다. 직접 태그 수정과 환경변수 키 사용, 폴더형 배포를 제공합니다.
