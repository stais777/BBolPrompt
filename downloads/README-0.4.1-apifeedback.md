# 0.4.1 설정창 진행·오류 표시 보완

대상: 현재0.4.0-apiengine을 실행하는 사용자. 이 버전은 정의 초안 열기·확정의 진행/오류를 설정창 안에 표시한다. 사용자PC의 실제 초기화 실패 원인까지 해결됐다는 보고는 아니다.

[작은 패치 약163KB](Bbolprom-Definition-Feedback-Patch-v0.4.0-to-v0.4.1.zip) · [전체 Windows ZIP](Bbolprom-Windows-x64-v0.4.1-apifeedback.zip)

1. 앱 안의 **앱 종료**를 누른다.
2. 업데이트 ZIP의 내용 전체를 현재 **Bbolprom.exe가 있는 폴더**에 복사하고 같은 이름은 바꾼다.
3. **data 폴더는 그대로 보존**한다. PT 재등록과 키 재입력은 필요하지 않다.
4. 재실행해0.4.1-apifeedback 표시를 확인하고 정의 초안·교정 이력 열기를 누른다.
5. 실패하면 설정창 안에 나타나는 오류 문구를 공유한다. 키 값은 공유하지 않는다.

작은 패치는0.4.0용이며 이전 버전은 전체 Windows ZIP을 사용한다. 전체ZIP에도 사용자data·DB·API키는 없다.

새6개 및 기존API화면8개를 합성자료·모의응답으로 검증했다. 새Windows실행·사용자PC의 원래 실패 해결·실제API호환/품질은 미검증이다.

패치 SHA256: ff2bdb660733dc27d9c5eaeb06dd690492e22269f9bce1fdbafadca33b5ff646

전체 SHA256: a5b54740f2e7416589c9d6b5b4ae3944df78c205207793e25ffcdfb681a7ed72
