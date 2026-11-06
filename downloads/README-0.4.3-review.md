# 0.4.3 태그 검수 화면

[0.4.2용 작은 패치 약188KB](Bbolprom-Tag-Review-Patch-v0.4.2-to-v0.4.3.zip) · [전체 Windows ZIP](Bbolprom-Windows-x64-v0.4.3-review.zip)

1. 프로그램 안에서 **앱 종료**를 누른다.
2. 패치 내용 **전체**를 현재 **Bbolprom.exe 폴더**에 덮어쓴다. **data는 그대로 유지**한다.
3. 재실행해 **0.4.3-review**를 확인한다. 기존 신규 카드의 미분류 태그를 누르면 사유·원문 근거·같은 이름의 기준 태그가 표시된다.

**추가 API 분석은 필요 없다.** 저장된 결과를 읽는다. 태그·분류를 자동 변경하지 않으며 키·카드·PT 재등록도 필요 없다. 최초309개와 API 판단 기준은 유지한다.

HTTP17개·브라우저54개 통과. 새 버전의 실제 Windows 실행과 태그 의미 품질 전체 검수는 남아 있다. [구현·검증 범위](../docs/TAG_RESULT_REVIEW.md). SHA256은 [배포 목록](ARTIFACT_SHA256.json)을 따른다.

패치 SHA256: 558134d5a949899c234082a16eb2cb625e20bfa316e54a72609012228bc51466

전체 SHA256: f6a08c0c286d1b2c0315a2d7f5fffa248b65c2cd0d7e1a54a0fdce094a67b127

11개 프로그램 파일 패치다.0.4.2에 적용한1363개 전체 대상 파일이 새 배포본과 일치하며 합성data 표식을 보존했다. 패키지1362파일 SHA·PE·Linux 호스트 소스 smoke도 통과했다. [빌드·적용 영수증](../evaluation/tag-review-patch.json). 작은 패치는0.4.2용이며 다른 버전/새 설치는 전체 ZIP을 사용한다.
