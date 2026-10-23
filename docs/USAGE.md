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
`ROS_LOCALHOST_ONLY=1` 과 전용 `ROS_DOMAIN_ID`(실시간 슬롯 91~94, 벤치마크 150~, 튜닝 170~)를 씁니다. 같은 네트워크의 실제 로봇과 섞이지 않습니다.
실시간 슬롯의 시작 도메인은 `navstudio --domain N` 으로 바꿀 수 있습니다 (N~N+3 을 씁니다. 0~146 또는 200~229).

## 사용법

1. **맵** 탭에서 맵을 고르고 상단 **시뮬레이션 시작** 을 누릅니다 (Nav2 기동 약 4초, 차량형 플래너는 약 12초).
2. 왼쪽 도구에서 **목표**(G)를 고르고 맵을 누른 채 끌어 도착 방향을 정하면 바로 출발합니다.
3. 박스(B)·기둥(P)·단차(D)·의자(C)·보행자(W)를 놓으면 실행 중인 시뮬레이션에 즉시 반영됩니다. 맵에는 없는 장애물입니다.
   박스·기둥은 높이(일반 / 낮은 턱 / 문턱 / 공중, 또는 아래·위 높이 직접 입력)를, 단차는 깊이를 정합니다. 선택 도구로 고른 장애물의 높이·깊이도 바꿀 수 있습니다.
4. **파라미터** 탭에서 값을 바꾸면 상단 버튼이 **변경 적용 (재시작)** 으로 바뀝니다. 누르면 같은 장면으로 Nav2 를 다시 띄웁니다.
5. 같은 설정을 여러 시나리오로 비교하려면 **벤치마크**, 좋은 값을 찾으려면 **자동 튜닝** 을 씁니다.

### 동시 실행 비교

서로 다른 설정의 거동을 한 화면에서 비교합니다. 맵·장면(출발점, 목표, 장애물, 보행자)은 모든 슬롯이 같이 쓰고, 로봇은 기본으로 같이 쓰되 슬롯마다 바꿀 수 있습니다.

1. 화면 아래 막대의 **1 · 2 · 3 · 4** 로 동시에 띄울 개수를 고릅니다. 슬롯 A–D 가 색으로 구분됩니다.
2. 각 화면 머리글의 설정 이름을 눌러 **설정 세트** 나 **스택 기본값** 을 고릅니다. 같은 메뉴 아래쪽 **슬롯 로봇** 에서 그 슬롯만 다른 로봇(예: 센서 배치가 다른 로봇)을 고를 수 있습니다. 화면을 누르거나 `1`~`4` 키로 슬롯을 고르면 왼쪽 패널(스택·파라미터)이 그 슬롯을 편집합니다.
3. 상단 **모두 시작** — 꺼져 있거나 설정이 바뀐 슬롯을 2초 간격으로 띄웁니다. 슬롯 하나만 시작·재시작·끄기는 머리글 버튼으로 합니다.
4. 목표를 찍거나 **동시 출발** 을 누르면 모든 로봇이 출발점으로 돌아가고, 보행자도 처음 자리에서 다시 움직이고, 같은 순간에 출발합니다. 머리글의 깃발 버튼은 그 슬롯만 다시 주행합니다.
5. 오른쪽 **이번 주행 비교** 표에서 시간·거리·속도·이격·복구를 비교합니다. 모두 도착하면 항목마다 가장 좋은 값이 굵게 표시됩니다. 한 번의 주행에는 우연이 섞이므로 **이 설정들로 벤치마크** 로 넘겨 여러 시나리오에서 확인하세요.

슬롯 하나가 CPU 약 1코어를 씁니다. 코어 수의 절반보다 많이 띄우면 Nav2 제어 주기가 밀려 결과가 달라질 수 있습니다.

### 센서와 낮은 장애물·단차

2D 라이다는 자기 높이의 물체만 봅니다. 낮은 턱, 공중 장애물, 단차는 ToF·Depth 같은 센서와 인식 처리가 있어야 피합니다.

1. **로봇 설계** 에서 **센서 추가** 로 라이브러리의 센서를 달고 위치·높이·각도를 맞춥니다 (**옆에서** 보기로 pitch 와 바닥에 닿는 거리를 확인). **인식 처리** 는 ‘규칙 기반 인식’ 을 권장합니다. 예: 기본 로봇 `Everybot 홈 로봇`.
2. 시뮬레이션에서 박스 높이를 ‘낮은 턱’ 이나 ‘공중’ 으로 놓거나 **단차** 도구로 바닥이 꺼진 곳을 그립니다.
3. 주행하면 **센서 측정** · **인식 결과** 레이어와 오른쪽 **센서 · 인식** 패널(ToF 존 히트맵, Depth 영상, 확정 개수)로 무엇을 보고 무엇을 장애물로 확정했는지 봅니다.
4. 임계값은 **파라미터 → 센서 인식** 에서 바꿉니다. 센서 배치를 비교하려면 동시 실행 슬롯마다 다른 로봇을 고르세요.

센서 라이브러리, 인식 규칙, 새 센서 종류(파이썬 플러그인) 만드는 법은 [SENSORS.md](SENSORS.md) 에 있습니다.

### 설정 세트

**설정 세트** 는 주행 스택(제어기 + 경로 계획기)과 바꾼 파라미터를 묶어 이름 붙인 것입니다.

- 저장: 파라미터 탭 위 **저장**, 또는 로봇·스택 탭의 **현재 설정 저장**. 같은 이름이 있으면 덮어쓸지 묻습니다. 자동 튜닝 결과에서도 **설정 세트로 저장** 할 수 있습니다.
- 사용: 로봇·스택 탭의 설정 세트 목록, 동시 실행 슬롯의 머리글, 벤치마크의 **설정 세트·스택** 추가 버튼.
- 지우기: 목록의 휴지통 버튼. 기본 세트(튜닝안 A·B)는 지울 수 없습니다.
- 저장 위치: `~/.navstudio/presets/<id>.yaml` (다른 PC 로 복사해도 됩니다).

### 맵 추가와 관리

- **추가**: 맵 탭의 **맵 추가**, 또는 맵 파일을 맵 탭에 끌어다 놓습니다. ROS map_server 형식의 YAML(resolution, origin, image) + 이미지(PGM·PNG), 또는 맵 zip 을 받습니다. zip 하나에 맵 여러 개가 들어 있어도 됩니다.
- **맵 zip 형식**: 맵마다 폴더 하나 — `<id>/map.yaml`, 이미지, 선택으로 `info.json`(`name`, `group`, `description`)과 `scenarios.json`(준비된 시나리오). 맵 카드 ⋯ 메뉴의 **내보내기** 가 이 형식으로 저장하므로, 한 PC 에서 내보낸 맵을 다른 PC 에서 그대로 가져올 수 있습니다.
- **이름 바꾸기·지우기**: 맵 카드 ⋯ 메뉴. 기본 맵은 바꾸거나 지울 수 없습니다.
- **명령줄**: `navstudio maps list`, `navstudio maps import <zip | YAML 이미지 | 폴더>... [--name 이름]`, `navstudio maps export <id> [-o 파일]`, `navstudio maps rename <id> <이름>`, `navstudio maps remove <id>`.

단축키: `V` 선택 · `H` 이동 · `S` 출발점 · `G` 목표 · `B` 박스 · `P` 기둥 · `D` 단차 · `C` 의자 · `W` 보행자 · `E` 지우개 · `Delete` 선택 삭제 · `Esc` 취소 · 휠 확대 · `1`~`4` 슬롯 선택.
URL 끝에 `#sim`, `#robot`, `#bench`, `#tune` 을 붙이면 해당 작업 공간이 열립니다.

## 측정 방법

- **실시간 1배속.** Nav2 Humble 의 controller/behavior 루프가 wall-clock 주기로 돌기 때문에 시뮬레이션을 빨리 감을 수 없습니다. 대신 벤치마크는 여러 인스턴스를 병렬로 돌립니다 (인스턴스당 CPU 약 0.5~1코어).
- **시나리오.** 정상 / 맵에 없는 장애물(박스·의자 다리·기둥) / 보행자(횡단·마주 오기, 로봇 앞에서 양보) / 낮은·공중 장애물(3~8 cm 턱, 바닥 위 20~45 cm 에 떠 있는 선반) / 단차(경로를 파고드는 0.1~0.5 m 깊이). ‘생성’ 을 고르면 로봇 크기에 맞춰 출발·목표·장애물을 새로 뽑습니다. 준비된 시나리오에 없는 종류를 고르면 그 종류만 생성합니다.
- **통과 불가 제외.** 출발-목표 사이 가장 넓은 통로가 `2 × (내접원 + padding) + 12 cm` 보다 좁은 에피소드는 성공률 계산에서 빼고 따로 표시합니다.
- **지표.** 성공 = Nav2 성공 + 충돌 없음 + 낙하 없음. 이격 = footprint 외곽에서 가장 가까운 장애물까지 거리. 근접 시간 = 5 cm 이내 주행 시간. 각 저크 = 각가속도 변화율 RMS.
- **통계.** 성공률 95% Wilson 신뢰구간, 기준 설정 대비 짝비교(McNemar) p 값. 튜닝 점수는 튜닝에 쓴 시나리오에서만 잰 값이라 반드시 다른 맵으로 검증하세요.

## 패키지 구성

```
navstudio/
  cli.py            navstudio [run|doctor|build-plugins|maps]
  env.py            ROS 환경 격리
  server.py         FastAPI REST + WebSocket(상태 20Hz, costmap 압축 전송), 실시간 슬롯 4개
  bridge.py         rclpy 브리지, 슬롯마다 하나 (자기 Context·도메인. 상태·경로·costmap·로그 수신, 목표·월드 명령)
  configsets.py     설정 세트 (스택 + 파라미터 변경) 저장소
  maps.py           맵 목록·메타·가져오기·내보내기
  stack.py          세션 프로세스 관리 (서버가 죽으면 함께 종료, 남은 세션 정리)
  paramgen.py       운영 YAML → 스택 프리셋 → 로봇 → 사용자 변경 순서로 Nav2 params 생성
  schema.py         UI 파라미터 스키마 (data/param_schema.yaml)
  robot.py          로봇 프로파일 검증·변환 (센서 장착, 라이다 병합, 인식 방식)
  sensors.py        센서 모델 라이브러리와 장착 검증
  sensortypes/      센서 종류 플러그인 (lidar2d, tof, ultrasonic, depth + 사용자 파일)
  sim/sim2d.py      시뮬레이터 (차동/전방향/차량형, 다각형 footprint, 2.5D 월드, 다중 라이다·병합, 3D 센서, 보행자)
  sim/raycast.py    3D 광선 계산 (바닥·단차·박스·원기둥·벽)
  sim/perception.py 낮은 장애물·단차 인식 노드
  bench/            시나리오 생성, 벤치마크 워커, 실행 관리, 통계, Optuna 튜닝
  data/             기본 맵 4종과 시나리오, 운영 params·BT, 스택·로봇 프리셋, 기본 설정 세트, 플러그인 소스
  web/              UI (빌드 도구 없는 ES 모듈 + Canvas, three.js)
```

사용자 데이터는 `~/.navstudio` (`NAVSTUDIO_HOME` 로 변경)에 저장됩니다: `robots/`, `sensors/`(센서 모델), `sensor_types/`(센서 종류 플러그인), `maps/`, `presets/`(설정 세트), `runs/`, `sessions/`(슬롯별), `overlay/`.

### 확장

- **스택 프리셋**: `data/stacks/<id>.yaml` — `drives`(지원 구동 방식), `requires`(필요한 플러그인), `controller`/`planner`(UI 파라미터 필터), `nav`(운영 params 에 덮어쓸 값; 노드 이름 뒤 `!` 는 하위 트리 교체).
- **로봇**: UI 의 로봇 설계에서 저장하면 `~/.navstudio/robots/<id>.yaml`.
- **센서 모델**: 센서 라이브러리에서 저장하면 `~/.navstudio/sensors/<id>.yaml`.
- **센서 종류**: `~/.navstudio/sensor_types/<id>.py` — 광선, 측정, 발행, 인식 규칙을 정의하는 파이썬 파일 하나 ([SENSORS.md](SENSORS.md)).
- **파라미터 패널 항목**: `data/param_schema.yaml` 에 경로·범위·설명 추가. `{sensor}` 는 로봇의 모든 라이다로 펼쳐집니다.
- **기본 params 교체**: `~/.navstudio/base/navigation_params.yaml` 이 있으면 내장 운영 params 대신 씁니다.

## 한계

- 2.5D 시뮬레이션입니다. 장애물은 바닥 모양 + 높이 구간이고 단차는 수직으로 꺼진 사각형입니다. 경사로, 바닥 재질, RGB 영상, 배터리는 다루지 않습니다.
- 위치 추정은 정답 위치를 씁니다 (오도메트리 슬립은 있지만 AMCL/SLAM 오차는 없음).
- 보행자는 정해진 경로를 왕복하는 단순 모델입니다.
- 실제 로봇의 안전 계층(예: 저수준 비상 정지·탈출 로직)은 포함하지 않습니다. 결과는 설정 간 상대 비교로 읽으세요.

## 개발

개발 환경, 테스트, 변경할 때 같이 고칠 문서는 [DEVELOPMENT.md](DEVELOPMENT.md), 배포 절차는 [RELEASE.md](RELEASE.md) 를 보세요.
