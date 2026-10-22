# 변경 이력

이 프로젝트의 주요 변경 사항을 버전별로 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/), 버전 번호는 [Semantic Versioning](https://semver.org/lang/ko/) 을 따릅니다.

- **MAJOR** — 저장된 데이터(로봇·설정 세트·맵·실행 기록)나 API 를 깨는 변경
- **MINOR** — 새 기능
- **PATCH** — 버그 수정, 문서 수정

## [Unreleased]

## [0.2.0] - 2026-10-22

### 추가
- **동시 실행 비교**: 설정이 다른 시뮬레이션을 2~4개(슬롯 A–D) 나란히 띄웁니다. 맵·로봇·장면은 같이 쓰고, 슬롯마다 스택과 파라미터가 다릅니다.
  - 모두 시작 / 슬롯별 시작·재시작·끄기, 모든 로봇을 출발점에서 같은 순간에 보내는 ‘동시 출발’, 슬롯 하나만 다시 주행
  - 화면 이동·확대 연동, 다른 슬롯 궤적 겹쳐 보기, 슬롯 색으로 구분한 로봇·궤적
  - 오른쪽 비교 패널: 슬롯별 상태, 속도·이격 그래프, 이번 주행 비교표(항목별 최고값 표시), ‘이 설정들로 벤치마크’
- **설정 세트**: 주행 스택 + 바꾼 파라미터를 이름 붙여 저장·불러오기·덮어쓰기·삭제. 슬롯 머리글, 벤치마크 설정 추가, 자동 튜닝 결과(‘설정 세트로 저장’)에서 씁니다.
- **맵 관리**: 맵 파일을 끌어다 놓거나 골라서 추가(YAML + 이미지, 또는 여러 맵이 든 zip), 이름 바꾸기, zip 으로 내보내기, 지우기. zip 에 시나리오를 넣으면 같이 들어옵니다.
- CLI `navstudio maps list | import | export | rename | remove`
- 화면 왼쪽 위에 버전 표시
- 개발: 단위 테스트(ROS 없이), Playwright 흐름 테스트 3종, 저장소 검사 `scripts/check.py`, 릴리스 스크립트 `scripts/release.py`, pre-commit 훅, GitHub Actions CI

### 변경
- 실시간 세션이 ROS_DOMAIN_ID 를 기본 91~94 네 개 씁니다 (`--domain` 은 0~146 또는 200~229).
- Nav2 가 ‘실행 중’ 이 되는 조건: lifecycle manager 가 모든 노드 활성을 보고해야 합니다. 여러 세션은 2초 간격으로 띄우고, 기동이 멈추면 한 번 다시 시작합니다.
- ‘튜닝 프리셋’ 을 ‘설정 세트’ 로 바꿨습니다. 기본 세트를 고르면 그 세트의 스택으로 바뀝니다.
- 주행이 끝나면 ‘이번 주행’ 기록(시간·거리 등)이 도착 시점 값으로 멈춥니다.
- 다른 스택에 해당하는 파라미터 값은 Nav2 설정을 만들 때 빠집니다.

### 수정
- 0.1.0 저장소에 플래너·BT 플러그인 C++ 소스(`plugins_src/*/src`)가 빠져 있어 `navstudio build-plugins` 와 Docker 빌드가 실패하던 문제. `scripts/check.py` 가 CMakeLists 에 적힌 소스가 모두 있는지 검사합니다.
- 자동 튜닝이 시작 직후나 ‘동시 trial’ 2개 이상에서 오류로 멈추던 문제: 진행률 조회가 결과 DB 를 동시에 만들려던 경합(`alembic_version`), 같은 trial 을 두 스레드가 받아 두 번 기록하던 경합(“Cannot tell a COMPLETE trial”)
- 맵 썸네일·격자 이미지가 같은 id 로 다시 올린 맵에서 예전 그림을 보이던 문제 (캐시 끔)

## [0.1.0] - 2026-10-22

nav_tuning 분석 저장소에서 앱만 분리한 첫 버전입니다.

### 추가
- 시뮬레이션: 맵 선택, 출발·목표 지정, 박스·기둥·의자·보행자 배치, 전역/지역 costmap·경로·라이다·궤적 실시간 표시, 속도·이격 텔레메트리, Nav2 메시지
- 파라미터: 스택별 파라미터 패널, 튜닝 프리셋, 운영 기본값 대비 diff, 고급 YAML 오버라이드, params.yaml 내보내기
- 로봇 설계: 차동·전방향·차량형 구동, 원형·다각형 footprint 편집, 라이다 배치, 3D 미리보기
- 벤치마크: 최대 4개 설정 병렬 비교, Wilson 신뢰구간, McNemar 짝비교, 에피소드 재생
- 자동 튜닝: Optuna(TPE) 탐색, 실시간 순위표, 최고 설정 적용·검증
- 배포: `navstudio` CLI(run · doctor · build-plugins), Docker 이미지, 사용 가이드 PDF

### 변경
- 공개 저장소에는 합성 맵 4종만 기본으로 넣습니다. 현장 맵은 맵 올리기로 추가합니다.
- Docker 는 기본으로 이 PC 에서만 접속됩니다 (`127.0.0.1:8765`).

[Unreleased]: https://github.com/Hwan-Yeong/nav2_simulator_app/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Hwan-Yeong/nav2_simulator_app/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Hwan-Yeong/nav2_simulator_app/releases/tag/v0.1.0
