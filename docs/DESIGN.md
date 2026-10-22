# Nav Studio 설계 메모

브라우저 UI 에서 맵·로봇·파라미터를 고르고, 실제 Nav2 스택이 로봇을 실시간으로 움직이는 2D 시뮬레이션·벤치마크·튜닝 도구.

## 결정 사항

| 항목 | 결정 | 이유 |
|---|---|---|
| UI | 로컬 웹앱 (브라우저), 빌드 도구 없는 vanilla JS + Canvas | 설치 부담 없음, WSL/원격에서도 브라우저로 접속 |
| 백엔드 | Python FastAPI + rclpy 브리지 (WebSocket 스트리밍) | Nav2·시뮬레이터와 같은 ROS 2 환경 |
| 시뮬레이션 | 2D, 실시간 1배속 | Nav2 Humble 제어 루프가 wall-clock 주기라 배속 불가 |
| 로봇 설정 | 2D 상면도 CAD 편집기 + three.js 3D 미리보기 | 2D 내비게이션에 필요한 정보는 상면도로 충분, 3D 는 확인용 |
| 구동 방식 | 차동(diff), 전방향(omni/mecanum), 차량형(ackermann) | |
| 배포 | pip 패키지 + CLI (`navstudio`), Docker 이미지 | ROS 2 가 있는 PC 는 pip, 없는 PC 는 Docker |
| 기본 데이터 | 합성 맵 4종과 시나리오, Everybot 운영 Nav2 params·BT, Everybot 플래너·BT 플러그인 소스 | 현장 맵은 공개 저장소에 넣지 않고, 맵 올리기로 추가 |
| 언어 | UI 한국어, 파라미터 이름은 원문 | |

## 단계 (완료)

1. 핵심: 시뮬레이터 + 파라미터 생성 + 세션 관리 + ROS 브리지 + 서버 + 뷰어
2. UI: 맵 선택, 시나리오 도구, 파라미터 패널, 텔레메트리·로그, 레이어
3. 로봇 설계: 상면도 편집 + 3D 미리보기 + 프리셋 로봇
4. 벤치마크·튜닝: 실행·진행률·결과표·에피소드 재생, Optuna 튜닝·순위표·적용/검증
5. 배포: pip 패키지, CLI, doctor, 플러그인 빌드, Docker, README, 사용 가이드
