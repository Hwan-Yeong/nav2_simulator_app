# 릴리스 절차

새 기능이 모이면 버전을 올려 배포합니다. 번호는 [Semantic Versioning](https://semver.org/lang/ko/) 을 따릅니다.

| 올리는 자리 | 언제 |
|---|---|
| MAJOR (`1.0.0`) | 저장된 로봇·설정 세트·맵·실행 기록이나 REST API 를 예전 버전과 함께 쓸 수 없게 될 때 |
| MINOR (`0.3.0`) | 새 기능 |
| PATCH (`0.2.1`) | 버그 수정, 문서 수정 |

## 순서

1. **변경 이력 확인** — `CHANGELOG.md` 의 `[Unreleased]` 에 이번 변경이 다 적혀 있는지 봅니다.
2. **버전 올리기**
   ```bash
   python3 scripts/release.py 0.3.0
   ```
   `[Unreleased]` 내용을 `## [0.3.0] - 오늘 날짜` 로 옮기고, `navstudio/__init__.py` 와 `docker/compose.yml` 의 버전을 바꿉니다.
3. **화면이 바뀌었으면 스크린샷과 데모 다시 찍기** (서버 실행 중, 새 버전 번호가 화면에 찍힙니다)
   ```bash
   python3 scripts/capture_guide.py all     # 가이드 스크린샷 + README 이미지
   python3 scripts/capture_demo.py          # README 데모 GIF
   ```
4. **사용 가이드 다시 만들기**
   ```bash
   python3 docs/guide/build_guide.py        # PDF, 쪽 이미지, guide.stamp.json
   ```
5. **검사와 테스트**
   ```bash
   python3 scripts/check.py --release --tag v0.3.0
   python3 -m pytest
   python3 tests/e2e/single_flow.py && python3 tests/e2e/compare_flow.py && python3 tests/e2e/manage_flow.py && python3 tests/e2e/sensor_flow.py
   docker compose -f docker/compose.yml build   # 이미지가 만들어지는지
   ```
6. **커밋, 태그, 올리기**
   ```bash
   git commit -am "Release 0.3.0"
   git tag -a v0.3.0 -m "Nav Studio 0.3.0"
   git push origin main --follow-tags
   ```
   태그가 올라가면 GitHub Actions 가 같은 검사(`--release`)와 Docker 빌드를 다시 돌립니다.
7. **GitHub Release** (선택) — 저장소의 *Releases → Draft a new release* 에서 태그를 고르고, `CHANGELOG.md` 의 해당 절을 붙여 넣습니다.

## 검사가 막는 것

`scripts/check.py --release` 는 다음 중 하나라도 맞지 않으면 실패합니다.

- `navstudio/__init__.py`, `docker/compose.yml` 이미지 태그, `CHANGELOG.md` 최신 절의 버전이 서로 다름
- `[Unreleased]` 에 아직 옮기지 않은 내용이 남음, 태그가 버전과 다름
- 사용 가이드 PDF 가 지금 버전·스크린샷·원본으로 만들어지지 않음 (`docs/guide/guide.stamp.json`), 넘치는 쪽이 있음
- 금지된 이름, YAML 중복 키, 문법 오류, 깨진 문서 링크, 기본 데이터 불일치

## 배포 이미지

완성 이미지 파일(`docker save`)이나 레지스트리 배포는 아직 하지 않습니다. 기능이 안정되면 이 절차에 추가합니다.
