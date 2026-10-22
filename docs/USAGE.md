# Nav Studio 사용법

개요와 데모는 [README](../README.md), 화면별 설명은 [사용 가이드 PDF](guide/Nav_Studio_User_Guide.pdf) 를 보세요. 이 문서는 설치 옵션, 사용 흐름, 측정 방법, 확장·개발 방법을 정리합니다.

## 설치와 실행

### A. ROS 2 Humble 이 있는 Ubuntu 22.04 (WSL2 포함)

```bash
sudo apt install ros-humble-navigation2 python3-venv   # Nav2 가 없다면
git clone https://github.com/Hwan-Yeong/nav2_simulator_app.git && cd nav2_simulator_app
python3 -m venv ~/.navstudio-venv                      # 전용 가상환경 (시스템 Python 을 건드리지 않음)
~/.navstudio-venv/bin/pip install -U pip setuptools    # Ubuntu 22.04 기본 pip 는 패키지 정보를 못 읽음
~/.navstudio-venv/bin/pip install ".[tune]"
ln -s ~/.navstudio-venv/bin/navstudio ~/.local/bin/    # 어디서나 navstudio 로 실행
navstudio build-plugins                                # Everybot 플래너·BT 플러그인 빌드 (1분, 처음 한 번)
navstudio                                              # 서버를 띄우고 브라우저로 http://localhost:8765 를 엽니다
```

`navstudio doctor` 는 ROS 2, Nav2 패키지, 플러그인, Python 패키지를 점검합니다.
플러그인을 빌드하지 않으면 Everybot 플래너 대신 표준 Nav2 플래너(NavFn)로 바꿔 실행하고 화면에 알려 줍니다.

### B. Docker (ROS 2 설치 없이)

```bash
cd nav2_simulator_app
docker compose -f docker/compose.yml up -d --build   # 처음 빌드 10분 안팎 (인터넷 필요)
# http://localhost:8765
```

로봇·맵·실행 기록은 `navstudio-data` 볼륨(`/data`)에 남습니다.

`localhost` 는 Nav Studio 를 실행한 그 PC 를 뜻합니다. 기본 설정은 그 PC 에서만 접속되게 되어 있습니다.
같은 네트워크의 다른 PC 에서 쓰려면 `docker/compose.yml` 의 `ports` 를 `"8765:8765"` 로 바꾸고(직접 설치는 `navstudio --host 0.0.0.0`)
`http://<실행한 PC 의 IP>:8765` 로 접속합니다. 로그인 기능이 없으니 사내망에서만 여세요.

### 실행 환경 격리

Nav Studio 는 사용자 셸의 ROS 오버레이와 DDS 프로파일을 쓰지 않습니다. `/opt/ros/humble` 과 자체 플러그인 오버레이만 소싱하고,
`ROS_LOCALHOST_ONLY=1` 과 전용 `ROS_DOMAIN_ID`(실시간 세션 91, 벤치마크 150~, 튜닝 170~)를 씁니다. 같은 네트워크의 실제 로봇과 섞이지 않습니다.
도메인은 `navstudio --domain N` 으로 바꿀 수 있습니다.

## 사용법

1. **맵** 탭에서 맵을 고르고 상단 **시뮬레이션 시작** 을 누릅니다 (Nav2 기동 약 4초, 차량형 플래너는 약 12초).
2. 왼쪽 도구에서 **목표**(G)를 고르고 맵을 누른 채 끌어 도착 방향을 정하면 바로 출발합니다.
3. 박스(B)·기둥(P)·의자(C)·보행자(W)를 놓으면 실행 중인 시뮬레이션에 즉시 반영됩니다. 맵에는 없고 라이다에만 보이는 장애물입니다.
4. **파라미터** 탭에서 값을 바꾸면 상단 버튼이 **변경 적용 (재시작)** 으로 바뀝니다. 누르면 같은 장면으로 Nav2 를 다시 띄웁니다.
5. 같은 설정을 여러 시나리오로 비교하려면 **벤치마크**, 좋은 값을 찾으려면 **자동 튜닝** 을 씁니다.

단축키: `V` 선택 · `H` 이동 · `S` 출발점 · `G` 목표 · `B` 박스 · `P` 기둥 · `C` 의자 · `W` 보행자 · `E` 지우개 · `Delete` 선택 삭제 · `Esc` 취소 · 휠 확대.
URL 끝에 `#sim`, `#robot`, `#bench`, `#tune` 을 붙이면 해당 작업 공간이 열립니다.

## 측정 방법

- **실시간 1배속.** Nav2 Humble 의 controller/behavior 루프가 wall-clock 주기로 돌기 때문에 시뮬레이션을 빨리 감을 수 없습니다. 대신 벤치마크는 여러 인스턴스를 병렬로 돌립니다 (인스턴스당 CPU 약 0.5~1코어).
- **시나리오.** 정상 / 맵에 없는 장애물(박스·의자 다리·기둥) / 보행자(횡단·마주 오기, 로봇 앞에서 양보). ‘생성’ 을 고르면 로봇 크기에 맞춰 출발·목표·장애물을 새로 뽑습니다.
- **통과 불가 제외.** 출발-목표 사이 가장 넓은 통로가 `2 × (내접원 + padding) + 12 cm` 보다 좁은 에피소드는 성공률 계산에서 빼고 따로 표시합니다.
- **지표.** 성공 = Nav2 성공 + 충돌 없음. 이격 = footprint 외곽에서 가장 가까운 장애물까지 거리. 근접 시간 = 5 cm 이내 주행 시간. 각 저크 = 각가속도 변화율 RMS.
- **통계.** 성공률 95% Wilson 신뢰구간, 기준 설정 대비 짝비교(McNemar) p 값. 튜닝 점수는 튜닝에 쓴 시나리오에서만 잰 값이라 반드시 다른 맵으로 검증하세요.

## 패키지 구성

```
navstudio/
  cli.py            navstudio [run|doctor|build-plugins]
  env.py            ROS 환경 격리
  server.py         FastAPI REST + WebSocket(상태 20Hz, costmap 압축 전송)
  bridge.py         rclpy 브리지 (상태·경로·costmap·로그 수신, 목표·월드 명령)
  stack.py          세션 프로세스 관리 (서버가 죽으면 함께 종료, 남은 세션 정리)
  paramgen.py       운영 YAML → 스택 프리셋 → 로봇 → 사용자 변경 순서로 Nav2 params 생성
  schema.py         UI 파라미터 스키마 (data/param_schema.yaml)
  robot.py          로봇 프로파일 검증·변환
  sim/sim2d.py      2D 시뮬레이터 (차동/전방향/차량형, 다각형 footprint, 다중 라이다, 보행자)
  bench/            시나리오 생성, 벤치마크 워커, 실행 관리, 통계, Optuna 튜닝
  data/             맵, 시나리오, 운영 params·BT, 스택·로봇·튜닝 프리셋, 플러그인 소스
  web/              UI (빌드 도구 없는 ES 모듈 + Canvas, three.js)
```

사용자 데이터는 `~/.navstudio` (`NAVSTUDIO_HOME` 로 변경)에 저장됩니다: `robots/`, `maps/`, `runs/`, `sessions/`, `overlay/`.

### 확장

- **스택 프리셋**: `data/stacks/<id>.yaml` — `drives`(지원 구동 방식), `requires`(필요한 플러그인), `controller`/`planner`(UI 파라미터 필터), `nav`(운영 params 에 덮어쓸 값; 노드 이름 뒤 `!` 는 하위 트리 교체).
- **로봇**: UI 의 로봇 설계에서 저장하면 `~/.navstudio/robots/<id>.yaml`.
- **파라미터 패널 항목**: `data/param_schema.yaml` 에 경로·범위·설명 추가. `{sensor}` 는 로봇의 모든 라이다로 펼쳐집니다.
- **기본 params 교체**: `~/.navstudio/base/navigation_params.yaml` 이 있으면 내장 운영 params 대신 씁니다.

## 한계

- 2D 시뮬레이션입니다. 3D 센서(ToF·카메라), 높이가 있는 장애물, 바닥 상태, 배터리는 다루지 않습니다.
- 위치 추정은 정답 위치를 씁니다 (오도메트리 슬립은 있지만 AMCL/SLAM 오차는 없음).
- 보행자는 정해진 경로를 왕복하는 단순 모델입니다.
- 실제 로봇의 안전 계층(예: 저수준 비상 정지·탈출 로직)은 포함하지 않습니다. 결과는 설정 간 상대 비교로 읽으세요.

## 개발

```bash
PYTHONPATH=$PWD python3 -m navstudio run --no-browser     # 소스에서 실행
python3 tests/e2e_flow.py                                 # Playwright: 맵 선택→시작→목표→파라미터 변경→재시작
python3 tests/ui_probe.py --url "http://localhost:8765/?debug#bench" --out /tmp/shot.png
```
