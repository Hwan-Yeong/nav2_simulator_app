# 개발 가이드

Nav Studio 를 고치거나 기능을 더할 때의 작업 방법입니다. 사용법은 [USAGE.md](USAGE.md), 배포 절차는 [RELEASE.md](RELEASE.md) 를 보세요.

## 준비

```bash
git clone https://github.com/Hwan-Yeong/nav2_simulator_app.git && cd nav2_simulator_app
git config core.hooksPath scripts/hooks          # 커밋 전 검사 (한 번만)
python3 -m venv ~/.navstudio-dev && ~/.navstudio-dev/bin/pip install -U pip setuptools
~/.navstudio-dev/bin/pip install -e ".[tune,dev]" && ~/.navstudio-dev/bin/playwright install chromium
navstudio build-plugins                          # Everybot 플래너·BT 플러그인 (처음 한 번)
PYTHONPATH=$PWD python3 -m navstudio run --no-browser   # 소스에서 실행, http://localhost:8765
```

## 구조

| 위치 | 내용 |
|---|---|
| `navstudio/server.py` | REST + WebSocket. 실시간 슬롯(최대 4개) 관리 |
| `navstudio/bridge.py` | 슬롯 하나와 통신하는 rclpy 노드 (슬롯마다 자기 Context·ROS 도메인) |
| `navstudio/stack.py` | 세션 프로세스(`ros2 launch`) 시작·정지, 남은 프로세스 정리 |
| `navstudio/paramgen.py` · `schema.py` | Nav2 파라미터 합성, UI 파라미터 스키마 |
| `navstudio/configsets.py` | 설정 세트 저장소 |
| `navstudio/maps.py` | 맵 목록·메타·가져오기·내보내기 |
| `navstudio/sim/sim2d.py` | 시뮬레이터 (2.5D 월드, 라이다·3D 센서, 보행자) |
| `navstudio/sim/raycast.py` · `perception.py` | 3D 광선 계산, 낮은 장애물·단차 인식 노드 |
| `navstudio/sensortypes/` · `sensors.py` | 센서 종류 플러그인, 센서 모델 라이브러리 ([SENSORS.md](SENSORS.md)) |
| `navstudio/coverage.py` · `web/js/coverage.js` | 감지 범위(사각지대) 계산과 로봇 설계 화면 표시 |
| `navstudio/bench/` | 시나리오, 벤치마크 워커, 병렬 실행, 통계, 튜닝 |
| `navstudio/web/` | UI. 빌드 도구 없는 ES 모듈 (`js/state.js` 상태, `sim.js` 시뮬레이션 화면, `robot.js` 로봇 설계, `sensors.js` 센서 폼·라이브러리, `main.js` 상단·연결) |
| `scripts/` | `check.py` 검사, `release.py` 릴리스, `capture_guide.py` · `capture_demo.py` 스크린샷·데모 |
| `tests/unit/` | ROS 없이 도는 단위 테스트 (pytest) |
| `tests/e2e/` | 실행 중인 서버를 브라우저로 조작하는 흐름 테스트 (Playwright) |
| `docs/guide/` | 사용 가이드 PDF 원본 (`build_guide.py`) |

## 테스트

```bash
python3 -m pytest                       # 단위 테스트 (ROS 필요 없음, 1~2초)
python3 scripts/check.py                # 버전 일치, 금지 이름, YAML 중복 키, 문법, 문서 링크, 기본 데이터
# 아래는 서버가 떠 있어야 합니다 (위의 navstudio run)
python3 tests/e2e/single_flow.py        # 맵 → 시작 → 목표 → 파라미터 변경 → 재시작
python3 tests/e2e/compare_flow.py       # 슬롯 3개 → 모두 시작 → 동시 출발 → 비교표 → 슬롯별 정지·시작·주행
python3 tests/e2e/manage_flow.py        # 설정 세트 저장·불러오기·삭제, 맵 추가·이름 바꾸기·삭제
python3 tests/e2e/sensor_flow.py        # 센서 모델 저장·삭제, 센서 달기·대칭 복제, 낮은 턱 인식·회피, 단차 그리기
```

ROS 를 소싱한 셸에서는 ROS 의 pytest 플러그인이 끼어들 수 있습니다. 그때는 깨끗한 환경에서 돌립니다:
`env -i HOME=$HOME PATH=/usr/bin:/bin ~/.navstudio-dev/bin/python -m pytest`

## 변경할 때 같이 고칠 것

기능을 바꾸면 코드만이 아니라 아래를 **같은 커밋 또는 같은 PR** 에서 맞춥니다. `scripts/check.py --release` 가 빠진 것을 일부 잡아 주지만, 내용이 맞는지는 사람이 봐야 합니다.

| 바꾼 것 | 같이 고칠 것 |
|---|---|
| 사용자에게 보이는 동작 | `CHANGELOG.md` 의 `[Unreleased]` (추가 / 변경 / 수정 / 제거) |
| 화면 (UI) | 사용 가이드 본문(`docs/guide/build_guide.py`), 스크린샷(`scripts/capture_guide.py`), 필요하면 README 데모(`scripts/capture_demo.py`) |
| 설치·실행 방법, CLI | `README.md` 빠른 시작, `docs/USAGE.md`, 가이드 ‘설치와 실행’ 쪽 |
| REST API | `tests/unit/test_server.py`, 흐름 테스트 |
| 저장 데이터 형식 (로봇·설정 세트·맵·실행 기록) | 예전 형식을 읽을 수 있게 하거나, 못 하면 MAJOR 버전 |
| 기본 데이터 (`navstudio/data`) | `scripts/check.py` 가 맵·시나리오·스택 일관성을 검사 |
| 센서 종류·인식 규칙 | `docs/SENSORS.md`, `tests/unit/test_sensors.py` |
| 설계 결정 | `docs/DESIGN.md` |

## 규칙

- **버전**: `navstudio/__init__.py` 의 `__version__` 하나만 고칩니다. `pyproject.toml` 은 거기서 읽고, `docker/compose.yml` 태그는 `scripts/release.py` 가 맞춥니다.
- **커밋**: 한 커밋에 한 가지 이유. 제목은 무엇이 달라졌는지 (예: `Slot headers keep clicks while selecting a slot`).
- **브랜치**: `main` 은 언제나 동작하는 상태. 큰 기능은 브랜치에서 만들고 테스트를 통과한 뒤 합칩니다.
- **이름**: 이 저장소는 공개 저장소입니다. 외부 업체·이전 프로젝트 이름, 현장 맵, 사내 IP 는 넣지 않습니다 (`scripts/check.py` 의 `BANNED`). 현장 맵은 ‘맵 추가’ 로 각자 PC 에 넣습니다.
- **ROS 격리**: 서버와 세션은 `/opt/ros/humble` + 자체 오버레이만 쓰는 깨끗한 환경에서 돕니다 (`env.py`). 개발자 셸의 오버레이나 DDS 설정에 기대지 않습니다.
- **ROS 도메인**: 실시간 슬롯 91~94, 벤치마크 150~, 튜닝 170~.
- **UI 다시 그리기**: 클릭할 버튼을 mousedown 과 mouseup 사이에 다시 만들면 클릭이 사라집니다. 주기적으로 그리는 부분은 내용이 바뀔 때만 다시 그립니다 (`renderTop`, `renderSlotHeads` 참고).
