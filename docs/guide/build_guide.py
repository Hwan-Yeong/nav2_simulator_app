#!/usr/bin/env python3
"""Build the Nav Studio user guide: guide.html -> Nav_Studio_User_Guide.pdf + page PNGs (pages/).

Screenshots come from scripts/capture_guide.py (img/, with element boxes in img/boxes.json for the callouts).
The version comes from navstudio/__init__.py, the date from its CHANGELOG section. guide.stamp.json records what the
PDF was built from, so scripts/check.py --release can tell when it is out of date.
python3 docs/guide/build_guide.py
"""
import datetime
import html
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
IMG = os.path.join(HERE, 'img')
BOXES = json.load(open(os.path.join(IMG, 'boxes.json')))
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', open(os.path.join(ROOT, 'navstudio', '__init__.py')).read()).group(1)
_rel = re.search(rf'^## \[{re.escape(VERSION)}\] - (\S+)', open(os.path.join(ROOT, 'CHANGELOG.md')).read(), re.M)
DATE = _rel.group(1) if _rel else datetime.date.today().isoformat() + ' (미출시)'


def shot(name, callouts=(), caption='', cls='shot'):
    """Screenshot with numbered callouts. callouts: (box_key, number, anchor, outline?)
    anchor: vertical t / m / b (T / B: just above / below the box), horizontal l / c / r (L / R: just outside)"""
    boxes = BOXES.get(name.replace('.png', ''), {})
    marks = []
    for key, num, anchor, *rest in callouts:
        b = boxes.get(key)
        if not b:
            continue
        x = {'l': b['x'], 'c': b['x'] + b['width'] / 2, 'r': b['x'] + b['width'], 'L': b['x'] - 0.022, 'R': b['x'] + b['width'] + 0.022}[anchor[1]]
        y = {'t': b['y'], 'm': b['y'] + b['height'] / 2, 'b': b['y'] + b['height'], 'T': b['y'] - 0.03, 'B': b['y'] + b['height'] + 0.03}[anchor[0]]
        if rest and rest[0]:
            marks.append(f'<span class="ring" style="left:{100 * b["x"]:.2f}%;top:{100 * b["y"]:.2f}%;'
                         f'width:{100 * b["width"]:.2f}%;height:{100 * b["height"]:.2f}%"></span>')
        x, y = min(max(x, 0.025), 0.975), min(max(y, 0.035), 0.965)
        marks.append(f'<span class="num" style="left:{100 * x:.2f}%;top:{100 * y:.2f}%">{num}</span>')
    cap = f'<figcaption>{caption}</figcaption>' if caption else ''
    return f'<figure class="{cls}"><div class="frame"><img src="img/{name}" alt="">{"".join(marks)}</div>{cap}</figure>'


def legend(items):
    cls = 'legend two' if len(items) > 4 else 'legend'
    return f'<ol class="{cls}">' + ''.join(f'<li><span><b>{t}</b>{" — " + d if d else ""}</span></li>' for t, d in items) + '</ol>'


def code(s):
    return f'<pre>{html.escape(s.strip())}</pre>'


PAGES = []

# ---------------------------------------------------------------- 1. cover
PAGES.append(f'''
<section class="page cover">
  <div class="cover-top">
    <div class="brand"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M16 16 L26 11" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.8" fill="currentColor"/></svg>Everybot</div>
    <h1>Nav Studio<br><span>사용 가이드</span></h1>
    <p class="lead">브라우저에서 실제 Nav2 스택으로 로봇 주행을 시뮬레이션하고, 로봇과 센서를 설계하고,<br>설정 여러 개를 나란히 띄워 비교하고, 벤치마크와 자동 튜닝으로 검증합니다.</p>
    <div class="meta">버전 {VERSION} · {DATE}</div>
  </div>
  {shot('sim_compare.png', cls='hero')}
  <div class="cover-grid">
    <div><b>시뮬레이션</b><span>맵·장애물·보행자를 놓고 실시간 주행</span></div>
    <div><b>동시 실행 비교</b><span>설정 2~4개를 나란히, 같은 순간에 출발</span></div>
    <div><b>로봇 · 센서 설계</b><span>센서를 끌어서 배치하고 사각지대 확인</span></div>
    <div><b>벤치마크 · 튜닝</b><span>통계로 비교하고 Optuna 로 탐색</span></div>
  </div>
</section>''')

# ---------------------------------------------------------------- 2. overview
PAGES.append('''
<section class="page">
  <header class="ph"><span>01</span>개요</header>
  <h2>Nav Studio 는 무엇인가</h2>
  <p>Nav Studio 는 Everybot 로봇의 주행 설정(Nav2 Humble)을 PC 에서 바로 시험하는 앱입니다. 브라우저 화면의 로봇은 실제 Nav2 노드
  (controller · planner · behavior tree · costmap · velocity smoother)가 움직이고, 로봇과 센서는 2.5D 시뮬레이터가 대신합니다.
  실제 로봇 없이 파라미터를 바꿔 보고, 바꾼 효과를 숫자로 비교하고, 더 나은 값을 찾을 수 있습니다.</p>
  <div class="arch">
    <div class="box">브라우저<small>화면 · 조작</small></div><div class="arrow">⇄<small>HTTP · WebSocket</small></div>
    <div class="box">Nav Studio 서버<small>설정 생성 · 세션 · 벤치마크 · 튜닝</small></div><div class="arrow">⇄<small>ROS 2 (전용 도메인)</small></div>
    <div class="box accent">Nav2 Humble<small>controller · planner · BT</small></div><div class="arrow">⇄</div>
    <div class="box">2.5D 시뮬레이터<small>로봇 · 라이다 · ToF · Depth · 보행자</small></div>
  </div>
  <h3>작업 공간</h3>
  <table class="tbl">
    <tr><th>시뮬레이션</th><td>맵을 고르고 목표를 찍으면 로봇이 주행합니다. 박스·기둥·의자·보행자를 실행 중에 놓을 수 있고, costmap·경로·라이다·속도·장애물 이격거리를 실시간으로 봅니다. 파라미터를 바꾸면 Nav2 를 다시 띄워 적용합니다. <b>동시 실행</b> 으로 설정이 다른 시뮬레이션을 최대 4개 나란히 띄워 비교하고, 스택과 파라미터 묶음은 <b>설정 세트</b> 로 저장합니다.</td></tr>
    <tr><th>로봇 설계</th><td>구동 방식(차동 · 전방향 · 차량형), 외곽(footprint), 물리 한계, 센서(라이다 · ToF · 초음파 · Depth)의 종류·위치·각도와 인식 방식을 정합니다. 여기서 정한 값으로 시뮬레이터와 Nav2 설정이 자동으로 만들어집니다.</td></tr>
    <tr><th>벤치마크</th><td>최대 4개 설정을 같은 시나리오(정상 · 맵에 없는 장애물 · 보행자 · 낮은·공중 장애물 · 단차)로 반복 주행해 성공률, 충돌, 낙하, 속도, 이격, 복구 횟수를 비교합니다.</td></tr>
    <tr><th>자동 튜닝</th><td>고른 파라미터의 범위 안에서 점수가 가장 높은 조합을 찾습니다. 찾은 값은 바로 적용하거나 다른 맵에서 검증합니다.</td></tr>
  </table>
  <h3>필요한 환경</h3>
  <table class="tbl two">
    <tr><th></th><th>Docker 로 실행 (권장)</th><th>직접 설치</th></tr>
    <tr><th>운영체제</th><td>Windows 10/11, macOS, Linux</td><td>Ubuntu 22.04 (WSL2 포함)</td></tr>
    <tr><th>필요 소프트웨어</th><td>Docker Desktop</td><td>ROS 2 Humble + navigation2, Python 3.10</td></tr>
    <tr><th>함께 받을 것</th><td colspan="2">Nav Studio 소스 — <code>github.com/Hwan-Yeong/nav2_simulator_app</code> (Git 또는 ZIP 다운로드). 이 PDF 는 설명서일 뿐이라 이것만으로는 실행할 수 없습니다.</td></tr>
    <tr><th>권장 사양</th><td colspan="2">CPU 4코어 이상 · 메모리 8 GB 이상 · 디스크 4 GB. 벤치마크·튜닝은 동시 주행 1개당 CPU 약 0.5~1코어를 씁니다.</td></tr>
    <tr><th>브라우저</th><td colspan="2">Chrome, Edge, Firefox 최신 버전</td></tr>
  </table>
  <p class="note">시뮬레이션은 실제 시간과 같은 속도(1배속)로 돌아갑니다. Nav2 의 제어 루프가 실제 시계 기준으로 동작하기 때문입니다. 많은 주행이 필요할 때는 벤치마크가 여러 시뮬레이션을 동시에 돌립니다.</p>
</section>''')

# ---------------------------------------------------------------- 3. install
PAGES.append('''
<section class="page">
  <header class="ph"><span>02</span>설치와 실행</header>
  <h2>A. Docker 로 실행하기 <em>권장</em></h2>
  <ol class="steps">
    <li><b>Nav Studio 소스를 내려받습니다.</b> Git 이 없으면 저장소 페이지의 <i>Code → Download ZIP</i> 으로 받아 풀어도 됩니다.''' + code('''
git clone https://github.com/Hwan-Yeong/nav2_simulator_app.git''') + '''</li>
    <li><b>Docker Desktop 을 설치하고 실행합니다.</b> 작업 표시줄의 고래 아이콘이 “Engine running” 이 될 때까지 기다립니다.</li>
    <li><b>내려받은 폴더에서 이미지를 만들고 실행합니다.</b> 인터넷이 필요하고, 처음 한 번은 ROS 2·Nav2 를 내려받아 빌드하느라 10분 안팎 걸립니다. 그다음부터는 몇 초면 켜집니다.''' + code('''
cd nav2_simulator_app
docker compose -f docker/compose.yml up -d --build''') + '''</li>
    <li><b>같은 PC 의 브라우저에서 <code>http://localhost:8765</code> 를 엽니다.</b> <code>localhost</code> 는 “지금 이 PC” 라는 뜻이라, Nav Studio 를 실행한 PC 에서만 열립니다. 다른 PC 에서 접속하려면 아래 <i>다른 PC 에서 접속</i> 을 보세요.</li>
    <li><b>끄기·다시 켜기</b>''' + code('''
docker compose -f docker/compose.yml stop     # 끄기
docker compose -f docker/compose.yml start    # 다시 켜기
docker compose -f docker/compose.yml logs -f  # 서버 로그 보기''') + '''</li>
  </ol>
  <p class="note">저장한 로봇, 올린 맵, 벤치마크·튜닝 기록은 <code>navstudio-data</code> 볼륨에 남아 컨테이너를 지워도 유지됩니다.
  <b>다른 PC 에서 접속:</b> 기본값은 이 PC 에서만 열리게 되어 있습니다. compose.yml 의 <code>ports</code> 를 <code>"8765:8765"</code> 로 바꿔 다시 올리면(직접 설치는 <code>--host 0.0.0.0</code>) 같은 네트워크의 PC 에서 <code>http://&lt;실행한 PC 의 IP&gt;:8765</code> 로 접속할 수 있습니다. 로그인 기능이 없으므로 사내망에서만 여세요.</p>
  <h2>B. Ubuntu 22.04 + ROS 2 Humble 에 직접 설치하기</h2>
  ''' + code('''
sudo apt install ros-humble-navigation2 python3-venv
git clone https://github.com/Hwan-Yeong/nav2_simulator_app.git && cd nav2_simulator_app
python3 -m venv ~/.navstudio-venv
~/.navstudio-venv/bin/pip install -U pip setuptools
~/.navstudio-venv/bin/pip install ".[tune]"
ln -s ~/.navstudio-venv/bin/navstudio ~/.local/bin/
navstudio build-plugins      # Everybot 플래너·BT 플러그인 빌드 (처음 한 번, 약 1분)
navstudio                    # 서버를 띄우고 브라우저를 엽니다''') + '''
  <table class="tbl">
    <tr><th><code>navstudio doctor</code></th><td>ROS 2, Nav2, 플러그인, Python 패키지 설치 상태를 점검합니다.</td></tr>
    <tr><th><code>--port 8765</code></th><td>웹 주소의 포트. 이미 쓰는 포트면 바꿉니다.</td></tr>
    <tr><th><code>--host 0.0.0.0</code></th><td>다른 PC 의 브라우저에서도 접속할 때.</td></tr>
    <tr><th><code>--domain 91</code></th><td>시뮬레이션이 쓰는 ROS_DOMAIN_ID. 같은 PC 에서 여러 명이 쓸 때 서로 다르게 정합니다.</td></tr>
    <tr><th><code>--no-browser</code></th><td>브라우저를 자동으로 열지 않습니다.</td></tr>
  </table>
  <p class="note">Nav Studio 는 사용자 셸에 설정된 다른 ROS 작업공간이나 DDS 설정을 쓰지 않습니다. 모든 통신은 이 PC 안(localhost)에서만 오가므로 같은 네트워크의 실제 로봇에 영향을 주지 않습니다.</p>
</section>''')

# ---------------------------------------------------------------- 4. screen layout
PAGES.append('''
<section class="page">
  <header class="ph"><span>03</span>화면 구성</header>
  <h2>시뮬레이션 화면</h2>
  ''' + shot('sim_overview.png', [('tabs', 1, 'bl'), ('chips', 2, 'bl'), ('start', 3, 'bl'), ('left', 4, 'bl'), ('tools', 5, 'tr'),
                                  ('layers', 6, 'bl'), ('runbar', 7, 'tl'), ('nav', 8, 'tl'), ('logs', 9, 'tl')]) + legend([
    ('작업 공간 전환', '시뮬레이션 · 로봇 설계 · 벤치마크 · 자동 튜닝'),
    ('현재 설정과 상태', '맵 · 로봇 · 스택(변경 개수), 실행 상태(정지됨 / 시작 중 / 실행 중 / 오류)'),
    ('시작 · 변경 적용', '정지 상태면 “시뮬레이션 시작”, 설정을 바꾸면 “변경 적용 (재시작)” 으로 바뀝니다'),
    ('왼쪽 패널', '맵 고르기·추가·시나리오 불러오기 / 로봇·스택·설정 세트 / 파라미터 조정'),
    ('편집 도구', '선택 · 화면 이동 · 출발점 · 목표 · 박스 · 기둥 · 단차 · 의자 · 보행자 · 지우개'),
    ('레이어', '전역·지역 costmap, 라이다 점, 센서 측정, 인식 결과, 경로, 지나온 궤적, 격자. 오른쪽 끝 버튼은 맵 전체 보기'),
    ('주행 막대', '동시 실행 개수(1~4) · 주행(현재 목표로 다시 보내기) · 정지 · 출발점으로 · 로봇 따라가기 · 장애물 모두 지우기'),
    ('주행 상태', '대기 / 주행 중 / 도착 / 실패, 남은 거리, 복구 동작 횟수, 아래에 속도·이격 그래프와 이번 주행 기록'),
    ('Nav2 메시지', 'Nav2 노드의 경고·오류를 실시간으로 보여 줍니다. “실행 로그” 는 전체 출력'),
  ]) + '''
  <p class="note">지도 조작: 휠로 확대·축소, 빈 곳을 끌면 이동합니다. 출발점 <b>S</b> 는 초록 원, 목표는 분홍 깃발, 파란 선은 계획 경로, 청록 선은 실제로 지나온 궤적입니다.</p>
</section>''')

# ---------------------------------------------------------------- 5. quick start + tools
PAGES.append('''
<section class="page">
  <header class="ph"><span>04</span>시뮬레이션 따라하기</header>
  <ol class="steps compact">
    <li><b>맵 고르기</b> — 왼쪽 <b>맵</b> 탭에서 맵 카드를 누릅니다 (내 맵은 <b>맵 추가</b> 로, 13장). 아래 시나리오 목록에서 미리 만든 상황(정상 · 미등록 장애물 · 보행자 · 낮은·공중 장애물 · 단차)을 불러올 수도 있습니다.</li>
    <li><b>시작</b> — 오른쪽 위 <b>시뮬레이션 시작</b>. 약 4초 뒤 “실행 중” 이 됩니다. 차량형 로봇은 약 12초 걸립니다.</li>
    <li><b>출발점</b> — 출발점 도구(<kbd>S</kbd>)로 지도를 누른 채 끌면 로봇이 그 자리·방향으로 옮겨집니다.</li>
    <li><b>목표</b> — 목표 도구(<kbd>G</kbd>)로 누른 채 끌어 도착 방향을 정하면 바로 출발합니다.</li>
    <li><b>장애물 놓기</b> — 아래 도구로 주행 중에도 놓을 수 있습니다. 맵에 없는 물체라서, 지도에 없는 짐이나 사람·턱·단차를 만난 상황을 재현합니다.</li>
    <li><b>지켜보기</b> — 오른쪽 패널의 상태가 “도착” 이 되면 성공입니다. 실패하면 Nav2 메시지에서 이유를 확인합니다.</li>
  </ol>
  ''' + shot('sim_tools.png', [('opts', 1, 'tr', True)], '박스(주황), 의자 다리 4개, 왕복하는 보행자(보라)를 놓은 장면. 보행자 도구를 고르면 속도·크기 옵션이 나타납니다 ①.') + '''
  <table class="tbl tools">
    <tr><th>도구</th><th>키</th><th>사용법</th></tr>
    <tr><td>선택</td><td><kbd>V</kbd></td><td>장애물을 끌어 옮기고 <kbd>Delete</kbd> 로 지웁니다. 빈 곳을 끌면 화면 이동</td></tr>
    <tr><td>박스</td><td><kbd>B</kbd></td><td>끌어서 사각형 장애물을 그립니다. 옵션에서 높이(일반 · 낮은 턱 · 문턱 · 공중, 10장)</td></tr>
    <tr><td>기둥</td><td><kbd>P</kbd></td><td>누르는 곳에 원기둥. 반지름·높이는 옵션에서</td></tr>
    <tr><td>단차</td><td><kbd>D</kbd></td><td>끌어서 바닥이 꺼진 곳(계단·낭떠러지)을 그립니다. 깊이는 옵션에서</td></tr>
    <tr><td>의자</td><td><kbd>C</kbd></td><td>지름 5 cm 다리 4개. 2D 라이다로는 잘 안 보이는 대표적인 장애물</td></tr>
    <tr><td>보행자</td><td><kbd>W</kbd></td><td>시작점·끝점을 누르면 그 사이를 왕복합니다. 로봇 앞에서는 멈춰 양보합니다</td></tr>
    <tr><td>지우개</td><td><kbd>E</kbd></td><td>장애물이나 보행자 경로를 눌러 지웁니다. <kbd>Esc</kbd> 는 그리던 것 취소</td></tr>
  </table>
</section>''')

# ---------------------------------------------------------------- 6. parameters + config sets
PAGES.append('''
<section class="page">
  <header class="ph"><span>05</span>파라미터와 설정 세트</header>
  ''' + shot('params.png', [('setbar', 1, 'tc', True), ('changed', 2, 'tl', True), ('start', 3, 'bl')]) + legend([
    ('설정 세트', '지금 쓰는 세트 이름. 값을 바꾸면 “(수정됨)” 이 붙습니다. 저장 버튼으로 이름 붙여 저장합니다'),
    ('바꾼 항목', '파란 배경과 점으로 표시됩니다. 오른쪽 되돌리기 버튼으로 기본값 복원. 아래 회색 글씨는 실제 Nav2 파라미터 경로'),
    ('변경 적용 (재시작)', '누르면 같은 장면으로 Nav2 를 다시 띄웁니다 (약 4초)'),
  ]) + '''
  <div class="cols">
    <div>
      <h3>항목 구성</h3>
      <p>선택한 스택(제어기·경로 계획기)에 맞는 항목만 보입니다: 속도·가속, DWB 평가 가중치, MPPI, Pure Pursuit, Costmap, 경로 계획, 목표·진행 판정. 검색창과 <b>변경만</b> 버튼으로 찾습니다.</p>
      <h3>설정 세트</h3>
      <p><b>설정 세트</b> 는 주행 스택과 바꾼 파라미터를 묶은 것입니다. <b>저장</b> 을 누르고 이름을 적으면 <b>로봇·스택</b> 탭 목록에 들어가고, 동시 실행 슬롯과 벤치마크에서 이름으로 고를 수 있습니다. 같은 이름이면 덮어쓸지 묻습니다. 기본 세트 <i>튜닝안 A·B</i> 는 검증 분석에서 나온 값이고 지울 수 없습니다.</p>
      <h3>고급 오버라이드 · YAML</h3>
      <p>목록에 없는 Nav2 파라미터는 <b>고급 오버라이드</b> 에 YAML 로 적습니다. 예: <code>controller_server: {FollowPath.max_vel_x: 0.3}</code>. <b>YAML 미리보기</b> 는 운영 기본값 대비 바뀐 줄과 최종 Nav2 params 를 보여 주고, 실제 로봇에 쓸 파일로 저장할 수 있습니다.</p>
    </div>
    <div>
      ''' + shot('setup_sets.png', [], '로봇·스택 탭: 로봇, 주행 스택, 설정 세트 목록. 세트를 누르면 그 스택과 값이 들어오고, 내 세트는 휴지통으로 지웁니다.', 'shot small') + '''
    </div>
  </div>
</section>''')

# ---------------------------------------------------------------- 7. comparison
PAGES.append('''
<section class="page">
  <header class="ph"><span>06</span>동시 실행 비교</header>
  <p>설정 여러 개를 한 화면에서 나란히 돌려 봅니다. 맵과 장면은 모든 슬롯이 같이 쓰고, 슬롯마다 스택과 파라미터가 다릅니다. 센서 배치를 비교하려면 슬롯마다 로봇도 바꿀 수 있습니다.</p>
  ''' + shot('sim_compare.png', [('slots', 1, 'tc'), ('head', 2, 'bl', True), ('slotctl', 3, 'bc'), ('slotgo', 4, 'bc'), ('startall', 5, 'bl'),
                                  ('go', 6, 'tc'), ('compare', 7, 'ml', True), ('editing', 8, 'br')]) + legend([
    ('동시 실행 개수', '1~4. 슬롯 A–D 는 색으로 구분됩니다. 슬롯 하나가 CPU 약 1코어를 씁니다'),
    ('슬롯 머리글', '설정 이름을 누르면 설정 세트·스택 기본값·슬롯 로봇을 고르는 메뉴. 옆은 상태(꺼짐 / 시작 중 / 실행 중 / 변경됨 / 오류)'),
    ('슬롯 시작 · 끄기', '그 슬롯만 시작·재시작(설정을 바꿨으면 변경 적용)·끄기'),
    ('슬롯 주행', '깃발: 그 슬롯만 출발점에서 다시 주행 · 네모: 그 슬롯 주행 멈춤'),
    ('모두 시작', '꺼져 있거나 설정이 바뀐 슬롯을 2초 간격으로 띄웁니다. 모두 실행 중이면 모두 재시작'),
    ('동시 출발', '로봇을 모두 출발점에, 보행자를 처음 자리에 되돌린 뒤 같은 순간에 출발. 목표를 찍어도 같습니다'),
    ('비교 패널', '슬롯별 상태, 속도·이격 그래프, 이번 주행 비교표. 모두 도착하면 항목마다 가장 좋은 값이 초록'),
    ('편집 중인 슬롯', '화면을 누르거나 1~4 키로 고릅니다. 왼쪽 스택·파라미터 탭이 이 슬롯을 바꿉니다'),
  ]) + '''
  <div class="cols">
    <div>
      <h3>따라하기</h3>
      <ol class="steps compact">
        <li>맵과 시나리오를 고르고 아래 막대에서 <b>3</b> 을 누릅니다.</li>
        <li>슬롯 머리글의 이름을 눌러 비교할 설정을 고릅니다. 예: A 운영 설정, B MPPI, C Regulated Pure Pursuit.</li>
        <li>상단 <b>모두 시작</b>. 세 슬롯이 ‘실행 중’ 이 되면 목표를 찍거나 <b>동시 출발</b>.</li>
        <li>다른 슬롯의 궤적이 흐린 색으로 겹쳐 보입니다. 한 번의 주행에는 우연이 섞이므로, 차이가 작으면 <b>이 설정들로 벤치마크</b> 로 여러 시나리오에서 확인합니다.</li>
      </ol>
    </div>
    <div>''' + shot('slot_menu.png', [], '슬롯 머리글 메뉴: 설정 세트, 스택 기본값, 다른 슬롯 설정 복사, 파라미터 직접 편집, 이 슬롯만 쓸 로봇.', 'shot small') + '''</div>
  </div>
</section>''')

# ---------------------------------------------------------------- 7. robot design
PAGES.append('''
<section class="page">
  <header class="ph"><span>07</span>로봇 설계</header>
  ''' + shot('robot.png', [('form', 1, 'mr'), ('drive', 2, 'tr'), ('cadtools', 3, 'bl'), ('cad', 4, 'mc'), ('three', 5, 'ml'), ('derived', 6, 'ml')]) + legend([
    ('제원 입력', '이름, 차체 색·높이, 바퀴, 물리 한계(최대 속도·가속), 구동계 지연·슬립, 라이다 목록'),
    ('구동 방식', '차동 구동 · 전방향(메카넘) · 차량형(Ackermann). 차량형은 축거와 최대 조향각으로 최소 회전반경이 정해집니다'),
    ('편집 옵션', '5 mm 스냅, 좌우 대칭 편집(꼭짓점 하나를 옮기면 반대쪽도 같이), 치수 표시, 맞춤 보기'),
    ('상면도 편집기', '네모 핸들(꼭짓점)을 끌어 외곽을 바꾸고, 변을 더블클릭하면 꼭짓점 추가, 우클릭하면 삭제. 라이다는 점을 끌어 옮기고 부채꼴 끝의 원을 끌어 방향을 돌립니다'),
    ('3D 미리보기', '끌어서 회전, 휠로 확대. 바퀴·라이다·시야 범위를 입체로 확인'),
    ('계산값', '내접·외접원, Nav2 footprint, 최소 회전반경, 통과 가능한 최소 폭'),
  ]) + '''
  <div class="cols">
    <div>
      <h3>구동 방식과 주행 스택</h3>
      <table class="tbl">
        <tr><th>차동 구동</th><td>운영 설정(DWB), 표준 Nav2, MPPI, Pure Pursuit</td></tr>
        <tr><th>전방향</th><td>운영 설정(DWB, 횡이동 포함), 표준 Nav2, MPPI(Omni)</td></tr>
        <tr><th>차량형</th><td>Smac Hybrid-A* + MPPI(Ackermann). 최소 회전반경은 로봇 제원에서 자동 설정</td></tr>
      </table>
      <p class="note"><b>저장</b> 하면 내 로봇 목록에 추가되고, <b>시뮬레이션에 사용</b> 을 누르면 바로 시뮬레이션 화면으로 넘어갑니다. 로봇을 바꾸면 그 구동 방식을 지원하는 스택으로 자동으로 바뀝니다. 다각형 로봇은 Nav2 의 inflation 이 외곽을 덮도록 자동으로 맞춰집니다.</p>
    </div>
    <div>''' + shot('robot_ackermann.png', [], '차량형 카트 예: 뒷바퀴 축이 원점, 앞바퀴 조향과 최소 회전반경 원(파란 점선)이 표시됩니다.', 'shot small') + '''</div>
  </div>
</section>''')

# ---------------------------------------------------------------- 8. sensors on the robot
PAGES.append('''
<section class="page">
  <header class="ph"><span>08</span>센서 설계</header>
  <p>로봇에 2D 라이다 말고도 ToF(단일 · 멀티존), 초음파, Depth 카메라를 달 수 있습니다. 센서는 <b>센서 라이브러리</b> 의 모델(종류 + 사양)을 골라 달고, 로봇 위의 위치와 각도를 정합니다.</p>
  ''' + shot('robot_sensors.png', [('add', 1, 'bc'), ('card', 2, 'tr', True), ('specs', 3, 'mr'), ('view', 4, 'bc'), ('cad', 5, 'mc'), ('three', 6, 'ml')]) + legend([
    ('라이브러리 · 센서 추가', '라이브러리에서 센서 모델을 만들고 고칩니다. 센서 추가로 모델을 골라 로봇에 답니다'),
    ('센서 카드', '이름, 모델, 켜기/끄기, 위치 x·y·높이 z, 방향 roll·pitch(+ 가 아래)·yaw. ⋯ 메뉴: 복제, 좌우 대칭 복제, 라이브러리 값으로 되돌리기'),
    ('센서 사양', '주기·거리·잡음·시야·해상도. 멀티존 ToF 는 존 마스크(쓰는 존만 켜기)'),
    ('위에서 / 옆에서', '옆에서 보면 높이와 pitch 를 끌어 맞추고, 아래 광선이 바닥에 닿는 거리가 나옵니다'),
    ('편집기', '라이다는 부채꼴, 3D 센서는 시야가 바닥에 닿는 범위(점선)와 존마다 보는 곳(점). 센서를 끌어 옮기고 끝의 원으로 방향을 돌립니다'),
    ('3D 미리보기', '센서 상자와 시야 범위, 멀티존 ToF 의 존 광선'),
  ]) + '''
  <div class="cols">
    <div>''' + shot('robot_side.png', [], '옆에서 본 모습: 좌우 멀티존 ToF(아래쪽 광선이 0.25 m 앞 바닥), Depth 카메라, 위쪽 1D ToF, 앞뒤 라이다(가로선).', 'shot small') + '''</div>
    <div>
      <table class="tbl">
        <tr><th>라이다 병합</th><td>라이다가 둘 이상이면 고른 라이다를 360° <code>/scan</code> 하나로 합칩니다 (각 라이다는 <code>/scan_이름</code> 으로도 나감)</td></tr>
        <tr><th>인식 처리</th><td><b>규칙 기반 인식</b>(권장): 높이·단차 규칙으로 걸러 여러 프레임 확인 후 costmap 에 올림 · <b>원시 점</b>: 점구름을 그대로 · <b>끔</b>: 발행만</td></tr>
        <tr><th>등반 높이</th><td>이보다 낮은 턱은 넘어갑니다. 차체 높이보다 높이 뜬 장애물은 아래로 지나갑니다</td></tr>
      </table>
      <p class="note">기본 로봇 <b>Everybot 홈 로봇</b> 에 앞뒤 240° 라이다(병합), 좌우 멀티존 ToF 8×8, 위쪽 1D ToF, Depth 카메라가 달려 있습니다. 새 센서 <b>종류</b> 는 파이썬 파일 하나로 추가합니다 (라이브러리의 <b>템플릿 만들기</b>, 저장소의 <code>docs/SENSORS.md</code>).</p>
    </div>
  </div>
</section>''')

# ---------------------------------------------------------------- 9. detection coverage (blind spots)
PAGES.append('''
<section class="page">
  <header class="ph"><span>09</span>감지 범위 (사각지대 지도)</header>
  <p>센서를 달았으면 “이 물체를 로봇 주변 어디서부터 감지하나, 멈출 수 있나” 를 확인합니다. 로봇이 서 있을 때 물체를 주변 칸마다 놓고, 각 센서의 광선 · 측정 · 인식 규칙을 시뮬레이션과 똑같이 돌려 감지되는 칸을 칠합니다.</p>
  ''' + shot('robot_coverage.png', [('btn', 1, 'Bc'), ('probe', 2, 'mL'), ('summary', 3, 'mL'), ('corr', 4, 'mL'), ('legend', 5, 'mL'), ('hint', 6, 'tl')]) + legend([
    ('감지 범위', '편집기 도구 막대에서 켜고 끕니다. 센서를 옮기거나 사양을 바꾸면 다시 계산합니다 (1~3초)'),
    ('물체', '낮은 턱 · 문턱 · 공중 · 의자 다리 · 박스 · 단차. ‘물체 크기·높이’ 에서 크기·높이·깊이를 바꿉니다'),
    ('요약', '정지 거리(최대 속도, 가속 한계, 반응 시간), 정면에서 처음 감지하는 거리, 로봇 주변 0.5 m 의 방향별 감지 비율'),
    ('앞 통로', '로봇이 지나갈 폭을 줄마다: 정지 거리 밖에서 보임(초록) · 안에서만(노랑) · 못 봄(빨강). 지도 위 굵은 선이 정지 거리'),
    ('범례', '센서별로 맡은 칸 수. 누르면 그 센서가 보는 칸만 보입니다'),
    ('칸 색', '그 칸의 물체를 감지하는 센서 색. 빨간 빗금은 로봇 바로 옆 사각. 칸에 마우스를 올리면 감지하는 센서 이름이 나옵니다'),
  ]) + '''
  <div class="cols">
    <div>''' + shot('coverage_lidar.png', [], '라이다만 있는 기본 로봇의 낮은 턱: 라이다가 5 cm 보다 높이 있어 어디서도 못 봅니다 (앞 통로 못 봄 100%, 둘레 전체가 빗금).', 'shot small') + '''</div>
    <div>
      <h3>읽는 법</h3>
      <ul class="dots">
        <li>앞 통로에 <b>못 봄</b> 이 있으면 그 폭의 물체에 부딪힙니다. 그쪽을 보는 센서를 더하거나 돌립니다.</li>
        <li><b>늦음</b> 만 있으면 너무 늦게 봅니다. 센서를 더 멀리 보게 하거나(pitch 줄이기), 최대 속도를 낮추거나 감속을 키웁니다.</li>
        <li>둘레 빗금이 넓으면 제자리 회전 · 후진 때 위험합니다.</li>
        <li>문턱처럼 넘을 수 있는 높이(등반 높이 이하)는 감지할 필요가 없고, 인식 최소 높이(2 cm)보다 낮은 물체는 규칙에서 걸러집니다. 패널 아래 안내를 보세요.</li>
      </ul>
      <p class="note">서 있는 로봇의 한 장면이며, 인식 파라미터는 기본값입니다. 주행 중의 실제 결과는 시뮬레이션과 벤치마크(낮은·공중 장애물, 단차 시나리오)로 확인합니다.</p>
    </div>
  </div>
</section>''')

# ---------------------------------------------------------------- 9. low obstacles, drops, perception
PAGES.append('''
<section class="page">
  <header class="ph"><span>10</span>낮은 장애물과 단차</header>
  <p>2D 라이다는 자기 높이에 걸리는 것만 봅니다. 5 cm 턱, 테이블 상판, 계단 같은 단차는 바닥을 보는 센서와 인식 처리가 있어야 피합니다.</p>
  ''' + shot('sim_sensors.png', [('cliff', 1, 'mr'), ('opts', 2, 'tr', True), ('layers', 3, 'bl'), ('lowbox', 4, 'tl'), ('dropbox', 4, 'tr'), ('panel', 5, 'tl', True)]) + legend([
    ('단차 도구', '끌어서 바닥이 꺼진 곳을 그립니다 (빗금). 깊이는 옵션에서. 로봇 중심이 들어가면 떨어져 멈춥니다(낙하)'),
    ('박스 높이', '일반(0~1 m) · 낮은 턱(5 cm) · 문턱(1.5 cm) · 공중(0.65~0.75 m) 또는 아래·위 높이 직접 입력. 선택 도구로 고른 장애물도 바꿉니다'),
    ('레이어', '센서 측정(센서 색 점, 바닥에 맞은 점은 흐리게) · 인식 결과(확정 장애물 노란 사각형, 단차 ×)'),
    ('지도', '5 cm 턱(노란 사각형 = 확정된 인식 결과)이 costmap 에 올라 로봇이 돌아가고, 단차 가장자리에는 × 가 찍힙니다. 아래쪽 공중 장애물(0.70~0.75 m)은 차체보다 높아 그 아래로 지나갑니다'),
    ('센서 · 인식', 'ToF 존 히트맵(센서 뒤에서 본 모습, 빨강 = 가까움), Depth 축소 영상, 1D 거리 막대, 확정 개수, 인식 지우기'),
  ]) + '''
  <div class="cols">
    <div>
      <h3>인식 규칙 (요약)</h3>
      <ul class="dots">
        <li><b>장애물</b>: 바닥 위 2 cm ~ 차체+5 cm 에 맞은 점, 위아래 존이 같은 면을 맞힘</li>
        <li><b>단차</b>: 바닥이 보여야 할 존의 거리가 8 cm 이상 길거나 반사가 없음, 바닥보다 3 cm 이상 낮은 점</li>
        <li>라이다가 이미 본 곳은 빼고, 2 프레임 연속이면 확정. 바닥이 다시 보이면 지움</li>
      </ul>
    </div>
    <div>
      <h3>비교와 조정</h3>
      <ul class="dots">
        <li>임계값: <b>파라미터 → 센서 인식</b> (센서가 있는 로봇에서만 보임)</li>
        <li>센서 배치 비교: 동시 실행 슬롯 머리글 메뉴의 <b>슬롯 로봇</b></li>
        <li>벤치마크 시나리오 <b>낮은·공중 장애물</b>, <b>단차</b> · 낙하는 실패로 셉니다</li>
      </ul>
    </div>
  </div>
</section>''')

# ---------------------------------------------------------------- 8. benchmark
PAGES.append('''
<section class="page">
  <header class="ph"><span>11</span>벤치마크</header>
  <p>설정 여러 개를 같은 시나리오로 반복 주행해 어느 쪽이 나은지 숫자로 비교합니다. 파라미터를 바꾼 효과가 우연인지 확인할 때 씁니다.</p>
  <ol class="steps compact">
    <li><b>새 벤치마크</b> → 비교할 설정을 추가합니다 (현재 설정, <b>설정 세트·스택</b>, 동시 실행 중인 슬롯 전체). 첫 번째가 비교 기준입니다.</li>
    <li>맵, 시나리오 종류, 맵당 에피소드 수, 동시 실행 수를 정합니다. 화면 아래에 예상 시간이 나옵니다.</li>
    <li><b>벤치마크 시작</b>. 창을 닫아도 서버에서 계속 돌고, 왼쪽 목록에서 다시 열 수 있습니다.</li>
  </ol>
  ''' + shot('bench_result.png', [('summary', 1, 'tl', True), ('matrix', 2, 'tl', True)]) + legend([
    ('결과 요약', '설정별 성공률(괄호는 95% 신뢰구간), 충돌, 평균 속도, 소요 시간, 장애물 이격(하위 10%·중앙값), 근접 시간, 복구 횟수, 각 저크, CPU, 점수. 각 열의 가장 좋은 값이 파란색'),
    ('에피소드별 결과', '칸을 누르면 그 주행을 재생합니다'),
  ]) + '''
  <div class="cols">
    <div>
      <h3>결과 읽는 법</h3>
      <ul class="dots">
        <li>성공 = Nav2 가 도착을 보고하고 충돌이 없는 주행.</li>
        <li><b>기준 대비</b> 열의 “개선 / 악화” 는 같은 에피소드에서 한쪽만 성공한 수, p 값이 0.05 보다 작아야 의미 있는 차이입니다.</li>
        <li>남은 틈이 로봇 폭 + 12 cm 보다 좁은 에피소드는 통과할 수 없으므로 성공률에서 뺍니다.</li>
        <li>“준비된 시나리오” 는 지름 0.35 m 원형 로봇 기준입니다. 큰 로봇은 “로봇 크기에 맞춰 생성” 을 고르세요.</li>
      </ul>
    </div>
    <div>''' + shot('replay.png', [], '에피소드 재생: 계획 경로, 지나온 궤적, 장애물과 보행자를 시간 순서대로 봅니다.', 'shot small') + '''</div>
  </div>
</section>''')

# ---------------------------------------------------------------- 9. tuning
PAGES.append('''
<section class="page">
  <header class="ph"><span>12</span>자동 튜닝</header>
  <p>고른 파라미터들의 범위 안에서 Optuna(TPE)가 조합을 바꿔 가며 시나리오를 주행하고, 점수가 높은 조합을 찾습니다.</p>
  <div class="cols">
    <div>
      <h3>설정 방법</h3>
      <ol class="steps compact">
        <li><b>기준 설정</b>: 지금 시뮬레이션의 로봇·스택·파라미터가 출발점입니다.</li>
        <li><b>튜닝할 파라미터</b>를 3~8개 체크하고 최소·최대를 정합니다. 첫 trial 은 현재 값으로 시작합니다.</li>
        <li><b>점수 가중치</b>로 무엇을 우선할지 정합니다: 성공률, 속도, 안전 여유, 부드러움.</li>
        <li>맵과 시나리오, trial 수, 동시 trial 수를 정하고 <b>튜닝 시작</b>.</li>
      </ol>
      <p class="note">점수 = 성공률(충돌 감점) + 평균 속도 + 장애물 이격(하위 10%) − 복구 횟수 − 각 저크. 예상 시간은 trial 하나에 시나리오 수 × 약 45초 ÷ 동시 주행 수입니다.</p>
    </div>
    <div>''' + shot('tune_form.png', [], '새 튜닝 화면: 파라미터 체크와 범위, 점수 가중치, 시나리오, trial 수.', 'shot small') + '''</div>
  </div>
  ''' + shot('tune_result.png', [], '튜닝 결과: 최고 trial 의 점수와 지표를 기준과 비교하고, 파라미터 값과 점수 추이를 보여 줍니다.') + '''
  <p class="warn"><b>적용 전에 검증하세요.</b> 튜닝 점수는 튜닝에 쓴 시나리오에서만 잰 값이라 우연히 좋게 나올 수 있습니다. <b>검증 벤치마크</b> 를 누르면 기준과 최고 설정을 튜닝에 쓰지 않은 맵에서 비교합니다. 결과가 좋으면 <b>시뮬레이션에 적용</b> 으로 값을 옮기거나 <b>설정 세트로 저장</b> 해 동시 실행·벤치마크에서 씁니다.</p>
</section>''')

# ---------------------------------------------------------------- 11. maps
PAGES.append('''
<section class="page">
  <header class="ph"><span>13</span>맵 추가와 관리</header>
  <p>기본 맵 4종 외에 ROS map_server 형식의 맵을 추가해 씁니다. 현장 맵처럼 저장소에 넣지 않는 맵도 각자 PC 에 추가하면 됩니다.</p>
  <div class="cols">
    <div>''' + shot('map_add.png', [], '맵 추가 창: 파일을 끌어다 놓거나 눌러서 고릅니다. 맵이 하나면 표시 이름을 정할 수 있습니다.', 'shot small') + '''</div>
    <div>
      <h3>추가하기</h3>
      <ol class="steps compact">
        <li>맵 탭의 <b>맵 추가</b>. 또는 파일을 맵 탭에 바로 끌어다 놓습니다.</li>
        <li>둘 중 하나를 고릅니다: <b>YAML + 이미지</b> (resolution · origin · image 가 있는 YAML 과 PGM/PNG), 또는 <b>맵 zip</b> (맵 여러 개 가능).</li>
        <li><b>추가</b> — ‘내 맵’ 에 나타나고 바로 선택됩니다. 같은 이름이 있으면 뒤에 (2) 가 붙습니다.</li>
      </ol>
      <h3>맵 zip 형식</h3>
      ''' + code('''
site_a/map.yaml         # ROS map_server YAML
site_a/map.pgm
site_a/info.json        # 선택: 이름·그룹
site_a/scenarios.json   # 선택: 시나리오
site_b/...''') + '''
    </div>
  </div>
  <div class="cols">
    <div>''' + shot('map_menu.png', [], '맵 카드의 ⋯ 메뉴: 내보내기(zip), 이름 바꾸기, 지우기. 기본 맵은 내보내기만 됩니다.', 'shot small') + '''</div>
    <div>
      <h3>내보내기 · 이름 바꾸기 · 지우기</h3>
      <p>맵 카드에 마우스를 올리면 ⋯ 버튼이 나타납니다. <b>내보내기</b> 는 위 형식의 zip 을 받아 다른 PC 의 Nav Studio 에서 그대로 추가할 수 있게 합니다. 지운 맵은 되돌릴 수 없습니다.</p>
      <h3>명령줄</h3>
      ''' + code('''
navstudio maps list
navstudio maps import site_maps.zip
navstudio maps import office.yaml office.pgm \
          --name "3층 사무실"
navstudio maps export site_a -o site_a.zip
navstudio maps remove site_a''') + '''
    </div>
  </div>
  <h3>저장 위치</h3>
  <table class="tbl">
    <tr><th>직접 설치</th><td><code>~/.navstudio/</code> — maps(추가한 맵), presets(설정 세트), robots(내 로봇), runs(벤치마크·튜닝 기록), sessions(슬롯별 마지막 세션), overlay(빌드한 플러그인). <code>NAVSTUDIO_HOME</code> 으로 위치 변경</td></tr>
    <tr><th>Docker</th><td><code>navstudio-data</code> 볼륨의 <code>/data</code> (위와 같은 폴더 구성)</td></tr>
  </table>
</section>''')

# ---------------------------------------------------------------- 12. troubleshooting
PAGES.append('''
<section class="page">
  <header class="ph"><span>14</span>문제 해결</header>
  <h3>자주 묻는 것</h3>
  <table class="tbl faq">
    <tr><th>시작을 눌렀는데 “오류” 가 뜬다</th><td>오류 상자의 <b>로그 보기</b> 나 오른쪽 아래 <b>실행 로그</b> 에서 첫 ERROR 줄을 확인합니다. 고급 오버라이드에 잘못된 값을 넣었을 때 흔합니다. <b>모두 초기화</b> 후 다시 시작해 보세요.</td></tr>
    <tr><th>“플러그인 없음 → 표준 플래너로 대체” 경고</th><td>Everybot 플래너가 빌드되지 않은 상태입니다. <code>navstudio build-plugins</code> 를 실행하세요. Docker 이미지는 이미 포함되어 있습니다.</td></tr>
    <tr><th>“출발점에서 로봇이 벽과 겹칩니다”</th><td>큰 로봇일 때 나옵니다. 출발점 도구로 넓은 곳을 고르세요. 겹친 채로는 경로를 만들지 못합니다.</td></tr>
    <tr><th>로봇이 제자리에서 멈춰 복구만 반복한다</th><td>좁은 틈 근처에서 장애물 비용이 높은 영역에 들어간 경우입니다. 경로 계획의 통과 비용 가중치를 높이거나 inflation 을 조정해 보세요. 실제 로봇에는 이 상황을 푸는 별도 탈출 동작이 있을 수 있습니다.</td></tr>
    <tr><th>동시 실행에서 한 슬롯만 “오류”</th><td>그 화면의 <b>로그 보기</b> 에서 첫 ERROR 줄을 확인하고 <b>다시 시작</b> 합니다. 다른 슬롯은 영향을 받지 않습니다. 기동이 30초 안에 끝나지 않으면 한 번은 자동으로 다시 띄웁니다.</td></tr>
    <tr><th>슬롯을 여러 개 띄우니 움직임이 이상하다</th><td>슬롯 하나가 CPU 약 1코어를 씁니다. 코어가 부족하면 Nav2 제어 주기가 밀려 결과가 달라집니다. 개수를 줄이거나 벤치마크를 같이 돌리지 마세요.</td></tr>
    <tr><th>벤치마크가 느리다</th><td>Nav2 는 실시간으로만 돌아서 에피소드당 20~60초가 걸립니다. 동시 실행 수를 CPU 코어 수의 절반 정도까지 올리세요.</td></tr>
    <tr><th>낮은 장애물에 부딪히거나 단차에 떨어진다</th><td>로봇에 바닥 가까이를 보는 센서(ToF·Depth)가 있고 <b>인식 처리</b> 가 ‘규칙 기반 인식’ 인지 확인합니다. 센서를 <b>옆에서</b> 보기로 맞춰 아래 광선이 로봇 앞 0.2~0.4 m 바닥에 닿게 하고, 인식 결과 레이어에 점이 찍히는지 봅니다.</td></tr>
    <tr><th>포트 8765 를 이미 쓴다</th><td><code>navstudio --port 8780</code>, Docker 는 compose.yml 의 <code>ports</code> 를 <code>"127.0.0.1:8780:8765"</code> 로 바꾸고 <code>http://localhost:8780</code> 으로 엽니다.</td></tr>
  </table>
  <h3>알아 둘 한계</h3>
  <ul class="dots">
    <li>2.5D 시뮬레이션입니다. 장애물은 바닥 모양 + 높이 구간, 단차는 수직으로 꺼진 사각형입니다. 경사로·바닥 재질·RGB 영상·배터리는 다루지 않습니다.</li>
    <li>위치 추정은 정확하다고 가정합니다. 오도메트리 미끄러짐은 넣었지만 위치 추정 오차는 없습니다.</li>
    <li>보행자는 정해진 경로를 왕복하는 단순 모델입니다.</li>
    <li>실제 로봇의 저수준 안전 동작은 포함하지 않습니다. 결과는 설정 간 비교로 읽고, 최종 판단은 실제 로봇 시험으로 합니다.</li>
  </ul>
  <div class="end">Nav Studio · Everybot · 버전 ''' + VERSION + '''</div>
</section>''')

CSS = '''
@page { size: A4; margin: 0; }
:root { --accent: #0d7ea6; --accent-soft: #e2f1f7; --ink: #17212b; --muted: #5d6a76; --line: #dbe1e7; --panel: #f5f7f9; --warn: #a8700f; --warn-soft: #fbf0d9; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #e7ebef; }
body { font-family: "Malgun Gothic", "맑은 고딕", sans-serif; color: var(--ink); font-size: 9.6pt; line-height: 1.55; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; padding: 16mm 15mm 14mm; background: #fff; margin: 0 auto 8mm; position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 3.2mm; page-break-after: always; break-after: page; }
@media print { body { background: #fff; } .page { margin: 0; } }
.page::after { content: "Nav Studio 사용 가이드  ·  " attr(data-n); position: absolute; bottom: 7mm; left: 15mm; font-size: 7.5pt; color: #9aa5af; white-space: pre; }
.ph { display: flex; align-items: baseline; gap: 3mm; font-size: 8.5pt; font-weight: 700; color: var(--accent); letter-spacing: 0.06em; border-bottom: 1.2pt solid var(--accent); padding-bottom: 1.5mm; }
.ph span { font-family: "DejaVu Sans Mono", monospace; }
h1, h2, h3 { margin: 0; line-height: 1.3; }
h2 { font-size: 14pt; }
h2 em { font-style: normal; font-size: 8pt; color: #fff; background: var(--accent); border-radius: 3pt; padding: 0.5pt 5pt; vertical-align: middle; margin-left: 2mm; }
h3 { font-size: 10.5pt; margin-top: 1mm; }
p { margin: 0; }
code, kbd, pre { font-family: "DejaVu Sans Mono", monospace; }
code { font-size: 8.4pt; background: var(--panel); border: 0.5pt solid var(--line); border-radius: 2pt; padding: 0 2pt; }
kbd { font-size: 8pt; border: 0.6pt solid #b9c2ca; border-bottom-width: 1.4pt; border-radius: 2pt; padding: 0 3pt; background: #fff; }
pre { margin: 1.5mm 0 0; background: #111a21; color: #e4ebf0; font-size: 8.2pt; line-height: 1.5; border-radius: 4pt; padding: 3mm 3.5mm; white-space: pre-wrap; }
figure { margin: 0; }
.frame { position: relative; border: 0.6pt solid var(--line); border-radius: 4pt; overflow: hidden; }
.frame img { display: block; width: 100%; }
figcaption { font-size: 8pt; color: var(--muted); margin-top: 1.2mm; }
.num { position: absolute; width: 6mm; height: 6mm; margin: -3mm 0 0 -3mm; border-radius: 50%; background: #e2462f; color: #fff; font-weight: 700; font-size: 8.5pt; display: grid; place-items: center; box-shadow: 0 0 0 1.4pt #fff, 0 1pt 3pt rgba(0,0,0,.35); font-family: "DejaVu Sans", sans-serif; }
.ring { position: absolute; border: 1.6pt solid #e2462f; border-radius: 3pt; box-shadow: 0 0 0 1pt rgba(255,255,255,.7); }
.legend { margin: 0; padding: 0; list-style: none; counter-reset: n; display: grid; gap: 1.2mm; }
.legend li { counter-increment: n; display: grid; grid-template-columns: 6mm 1fr; gap: 2mm; align-items: start; }
.legend li::before { content: counter(n); width: 5mm; height: 5mm; border-radius: 50%; background: #e2462f; color: #fff; font-weight: 700; font-size: 7.5pt; display: grid; place-items: center; margin-top: 0.4mm; font-family: "DejaVu Sans", sans-serif; }
.legend b { margin-right: 1mm; }
.legend.two { grid-template-columns: 1fr 1fr; column-gap: 5mm; }
.legend span { font-size: 8.8pt; }
.steps { margin: 0; padding-left: 5mm; display: grid; gap: 2mm; }
.steps.compact { gap: 1.2mm; }
.steps li::marker { color: var(--accent); font-weight: 700; }
.dots { margin: 0; padding-left: 4.5mm; display: grid; gap: 1mm; }
.tbl { border-collapse: collapse; width: 100%; font-size: 8.8pt; }
.tbl th, .tbl td { border-bottom: 0.5pt solid var(--line); padding: 1.6mm 2mm; text-align: left; vertical-align: top; }
.tbl th { white-space: nowrap; color: var(--ink); width: 1%; font-weight: 700; }
.tbl.two th { width: auto; background: var(--panel); }
.tbl.tools td:first-child { white-space: nowrap; font-weight: 700; }
.tbl.tools th:last-child { width: auto; }
.tbl.faq th { white-space: normal; width: 34%; }
.note { background: var(--panel); border-left: 2pt solid var(--accent); padding: 2mm 3mm; font-size: 8.6pt; color: #34414c; border-radius: 0 3pt 3pt 0; }
.warn { background: var(--warn-soft); border-left: 2pt solid var(--warn); padding: 2mm 3mm; font-size: 8.8pt; border-radius: 0 3pt 3pt 0; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; align-items: start; }
.cols > div { display: grid; gap: 2mm; }
.arch { display: flex; align-items: center; gap: 1.5mm; margin: 1mm 0; }
.arch .box { flex: 1; border: 0.8pt solid var(--line); border-radius: 4pt; padding: 2.5mm 2mm; text-align: center; font-weight: 700; font-size: 9pt; background: var(--panel); }
.arch .box.accent { background: var(--accent-soft); border-color: var(--accent); }
.arch .box small, .arch .arrow small { display: block; font-weight: 400; font-size: 7pt; color: var(--muted); }
.arch .arrow { color: var(--accent); font-size: 13pt; text-align: center; line-height: 1; }
.end { margin-top: auto; text-align: right; font-size: 8pt; color: var(--muted); }
/* cover */
.cover { padding: 0; gap: 0; background: #fff; }
.cover::after { content: none; }
.cover-top { background: linear-gradient(160deg, #0b2a36 0%, #0d5a76 65%, #0d7ea6 100%); color: #fff; padding: 22mm 18mm 30mm; display: grid; gap: 5mm; }
.brand { display: flex; align-items: center; gap: 2.5mm; font-weight: 700; letter-spacing: 0.04em; font-size: 10pt; opacity: 0.9; }
.brand svg { width: 7mm; height: 7mm; color: #7fd6ef; }
.cover h1 { font-size: 34pt; letter-spacing: -0.01em; }
.cover h1 span { font-size: 20pt; font-weight: 400; opacity: 0.85; }
.lead { font-size: 11.5pt; line-height: 1.6; opacity: 0.92; }
.meta { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; opacity: 0.75; }
.hero { margin: -18mm 14mm 0; }
.hero .frame { border: 0; border-radius: 5pt; box-shadow: 0 6pt 22pt rgba(10, 30, 40, .35); }
.cover-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; padding: 9mm 14mm 0; }
.cover-grid div { border-top: 1.4pt solid var(--accent); padding-top: 2.5mm; display: grid; gap: 1mm; }
.cover-grid b { font-size: 10.5pt; }
.cover-grid span { font-size: 8.3pt; color: var(--muted); }
.shot.small .frame { border-radius: 3pt; }
.cols .shot.small .frame { max-height: 64mm; }
.cols .shot.small .frame img { max-height: 64mm; width: auto; max-width: 100%; display: block; margin: 0 auto; }
'''


def build():
    pages = [pg.replace('<section class="page', f'<section data-n="{i} / {len(PAGES)}" class="page', 1) for i, pg in enumerate(PAGES, 1)]
    doc = f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Nav Studio 사용 가이드</title><style>{CSS}</style></head><body>{"".join(pages)}</body></html>'
    src = os.path.join(HERE, 'guide.html')
    open(src, 'w', encoding='utf-8').write(doc)
    pdf = os.path.join(HERE, 'Nav_Studio_User_Guide.pdf')
    pages_dir = os.path.join(HERE, 'pages')
    os.makedirs(pages_dir, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={'width': 900, 'height': 1200}, device_scale_factor=2)
        pg.goto('file://' + src)
        pg.wait_for_timeout(1500)
        overflow = pg.evaluate("[...document.querySelectorAll('.page')].map((p, i) => p.scrollHeight > p.clientHeight + 1 ? i + 1 : 0).filter(Boolean)")
        pg.emulate_media(media='print')
        pg.pdf(path=pdf, format='A4', print_background=True, margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'})
        pg.emulate_media(media='screen')
        for i, el in enumerate(pg.query_selector_all('.page'), 1):
            el.screenshot(path=os.path.join(pages_dir, f'page_{i:02d}.png'))
        br.close()
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from check import guide_inputs_hash
    json.dump(dict(version=VERSION, date=DATE, pages=len(PAGES), overflow=overflow, inputs=guide_inputs_hash()),
              open(os.path.join(HERE, 'guide.stamp.json'), 'w'), indent=1)
    print('pdf:', pdf, '| pages:', len(PAGES), '| overflowing pages:', overflow or 'none')
    return 1 if overflow else 0


if __name__ == '__main__':
    sys.exit(build())
