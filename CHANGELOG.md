# 변경 이력

이 프로젝트의 주요 변경 사항을 버전별로 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/), 버전 번호는 [Semantic Versioning](https://semver.org/lang/ko/) 을 따릅니다.

- **MAJOR** — 저장된 데이터(로봇·설정 세트·맵·실행 기록)나 API 를 깨는 변경
- **MINOR** — 새 기능
- **PATCH** — 버그 수정, 문서 수정

## [Unreleased]

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

[Unreleased]: https://github.com/Hwan-Yeong/nav2_simulator_app/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Hwan-Yeong/nav2_simulator_app/releases/tag/v0.1.0
