# Slidecast Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** html-slide로 만든 self-contained HTML 슬라이드 덱을 누적/수정(버전)/삭제하고 갤러리에서 풀스크린 재생하는 개인용 서버리스 웹 뷰어를 AWS에 배포한다.

**Architecture:** CloudFront 단일 배포가 S3(정적 뷰어 SPA + 덱 파일)와 API Gateway(HTTP API, Cognito JWT authorizer 뒤 Lambda)를 same-origin으로 서빙한다. 메타데이터는 DynamoDB, 파일은 S3(OAC 프라이빗)에 버전 키(`v{n}`)로 보관하며, 업로드 시 Chromium Lambda가 첫 화면을 썸네일로 캡처한다. ALB/퍼블릭 인바운드 없음.

**Tech Stack:** AWS CDK (Python), Lambda (Python 3.12), API Gateway HTTP API, Cognito User Pool, DynamoDB, S3, CloudFront + OAC, React + Vite + TypeScript (다크 시네마틱), boto3 로컬 스킬.

## Global Constraints

- AWS 계정 `123456789012`, 자격증명 프로파일 `profile2`, 리전 `us-east-1` (모든 배포/스킬 명령에 `--profile profile2--region us-east-1` 또는 CDK env 명시).
- 퍼블릭 인바운드/ALB 금지. S3는 완전 프라이빗, CloudFront OAC로만 접근.
- Cognito: self sign-up 비활성화, 관리자가 사용자 1개 수동 생성.
- 모든 `/api`는 Cognito JWT authorizer 뒤에 위치.
- 코드/문서에 이모지 사용 금지. git 커밋 메시지에 AI attribution 금지.
- S3 버전 파일 키: `slides/{deckId}/v{n}/index.html`, 썸네일: `thumbnails/{deckId}/v{n}.png`.
- 버전 파일은 불변 → `Cache-Control: public, max-age=31536000, immutable`.
- deckId = 파일명 기반 슬러그(소문자, 영숫자와 하이픈).
- DynamoDB 테이블 `SlideDecks`: PK `deckId`, GSI `byUpdatedAt`(PK `status`, SK `updatedAt`).
- presigned PUT URL 만료 5분, content-type `text/html` 제한.

---

## File Structure

```
/Workshop/html-viewer
├── infra/                      # AWS CDK (Python)
│   ├── app.py                  # CDK 앱 엔트리
│   ├── cdk.json
│   ├── requirements.txt
│   └── slidecast/
│       ├── __init__.py
│       └── slidecast_stack.py  # 전체 스택 (S3, DDB, Cognito, API, Lambda, CloudFront)
├── lambdas/
│   ├── api/
│   │   ├── handler.py          # /api 라우팅 + 핸들러
│   │   ├── ddb.py              # DynamoDB 액세스 (deck repo)
│   │   ├── slug.py             # deckId 슬러그 생성
│   │   └── requirements.txt
│   └── thumbnail/
│       ├── handler.py          # S3 이벤트 → Chromium 캡처
│       └── requirements.txt
├── shared/
│   └── deck_model.py           # 공용 덱/버전 데이터 모델 (api + skill 재사용)
├── viewer/                     # React + Vite + TS SPA
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── auth.ts             # Cognito Hosted UI OIDC
│       ├── api.ts              # /api 클라이언트 (JWT 첨부)
│       ├── types.ts            # Deck, Version 타입
│       ├── App.tsx
│       ├── theme.css           # 다크 시네마틱 토큰
│       └── components/
│           ├── Gallery.tsx     # 카드 그리드 + 검색/필터 + 보관함 토글
│           ├── DeckCard.tsx    # 썸네일 카드 + 액션
│           ├── Player.tsx      # 풀스크린 iframe 재생
│           ├── VersionMenu.tsx # 버전 목록/롤백
│           └── UploadZone.tsx  # 드래그앤드롭 업로드
├── skill/
│   └── slidecast-append/
│       ├── SKILL.md
│       └── slidecast_append.py # boto3 직접 업로드/버전/삭제
├── tests/
│   ├── lambdas/
│   │   ├── test_slug.py
│   │   ├── test_ddb.py
│   │   └── test_api_handler.py
│   ├── shared/
│   │   └── test_deck_model.py
│   └── skill/
│       └── test_slidecast_append.py
└── docs/superpowers/{specs,plans}/
```

**Decomposition rationale:** 슬러그·데이터 모델·DDB 액세스는 순수 로직이라 moto/단위 테스트로 먼저 고정한다(Phase 1). 그 위에 API 핸들러(Phase 2), 썸네일 Lambda(Phase 3)를 올린다. CDK 스택은 이 아티팩트들을 배포하고 실제 리소스로 검증한다(Phase 4). SPA는 배포된 API를 소비한다(Phase 5). 로컬 스킬은 shared 모델을 재사용한다(Phase 6).

---

## Phase 1 — 코어 로직 (순수 함수 + 데이터 모델)

### Task 1: deckId 슬러그 생성기

**Files:**
- Create: `lambdas/api/slug.py`
- Test: `tests/lambdas/test_slug.py`

**Interfaces:**
- Produces: `slugify(filename: str) -> str` — 파일명에서 확장자 제거, 소문자화, 영숫자 외 문자를 하이픈으로, 연속 하이픈 축약, 양끝 하이픈 제거. 결과가 빈 문자열이면 `deck` 반환.

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_slug.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
from slug import slugify

def test_basic_filename():
    assert slugify("2026 Roadmap.html") == "2026-roadmap"

def test_strips_extension_and_path():
    assert slugify("/tmp/My Deck.HTML") == "my-deck"

def test_collapses_and_trims_hyphens():
    assert slugify("--Hello___World!!--.html") == "hello-world"

def test_empty_fallback():
    assert slugify("!!!.html") == "deck"

def test_unicode_dropped_to_hyphen():
    assert slugify("한글 deck.html") == "deck"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_slug.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'slug'`

- [ ] **Step 3: Write minimal implementation**

```python
# lambdas/api/slug.py
import os
import re


def slugify(filename: str) -> str:
    base = os.path.basename(filename)
    stem = os.path.splitext(base)[0]
    lowered = stem.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = hyphenated.strip("-")
    return trimmed or "deck"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_slug.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/slug.py tests/lambdas/test_slug.py
git commit -m "feat: add deckId slugify helper"
```

---

### Task 2: 공용 덱 데이터 모델

**Files:**
- Create: `shared/deck_model.py`
- Test: `tests/shared/test_deck_model.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `slide_key(deck_id: str, n: int) -> str` → `"slides/{deck_id}/v{n}/index.html"`
  - `thumb_key(deck_id: str, n: int) -> str` → `"thumbnails/{deck_id}/v{n}.png"`
  - `new_deck_item(deck_id, title, tags, now_iso) -> dict` — v0 아직 없음, `currentVersion=0`, `versions=[]`, `status="active"`, `createdAt=updatedAt=now_iso`
  - `add_version(item: dict, thumbnail_key, size_bytes, now_iso, slide_count=None) -> dict` — 불변식으로 새 dict 반환: `n = currentVersion + 1`, `versions`에 `{n, createdAt, thumbnailKey, sizeBytes, slideCount}` append, `currentVersion=n`, `updatedAt=now_iso`
  - `set_current(item: dict, n: int, now_iso) -> dict` — n이 존재하는 버전이면 `currentVersion=n`, `updatedAt` 갱신한 새 dict; 없으면 `ValueError`
  - `set_status(item: dict, status: str, now_iso) -> dict` — `status`("active"|"archived") + `updatedAt` 갱신한 새 dict

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_deck_model.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    slide_key, thumb_key, new_deck_item, add_version, set_current, set_status,
)

def test_keys():
    assert slide_key("roadmap", 2) == "slides/roadmap/v2/index.html"
    assert thumb_key("roadmap", 2) == "thumbnails/roadmap/v2.png"

def test_new_deck_item():
    item = new_deck_item("roadmap", "Roadmap", ["biz"], "2026-07-21T00:00:00Z")
    assert item["deckId"] == "roadmap"
    assert item["currentVersion"] == 0
    assert item["versions"] == []
    assert item["status"] == "active"
    assert item["title"] == "Roadmap"
    assert item["tags"] == ["biz"]

def test_add_version_is_immutable_and_increments():
    item = new_deck_item("roadmap", "Roadmap", [], "2026-07-21T00:00:00Z")
    v1 = add_version(item, "thumbnails/roadmap/v1.png", 1234, "2026-07-21T01:00:00Z")
    assert item["currentVersion"] == 0  # original untouched
    assert v1["currentVersion"] == 1
    assert v1["versions"][0]["n"] == 1
    assert v1["versions"][0]["thumbnailKey"] == "thumbnails/roadmap/v1.png"
    assert v1["versions"][0]["sizeBytes"] == 1234
    assert v1["updatedAt"] == "2026-07-21T01:00:00Z"
    v2 = add_version(v1, "thumbnails/roadmap/v2.png", 5678, "2026-07-21T02:00:00Z")
    assert v2["currentVersion"] == 2
    assert [v["n"] for v in v2["versions"]] == [1, 2]

def test_set_current_valid_and_invalid():
    item = add_version(new_deck_item("r", "R", [], "t0"), "k1", 1, "t1")
    item = add_version(item, "k2", 2, "t2")
    rolled = set_current(item, 1, "t3")
    assert rolled["currentVersion"] == 1
    assert rolled["updatedAt"] == "t3"
    try:
        set_current(item, 9, "t4")
        assert False, "expected ValueError"
    except ValueError:
        pass

def test_set_status():
    item = new_deck_item("r", "R", [], "t0")
    archived = set_status(item, "archived", "t1")
    assert archived["status"] == "archived"
    assert item["status"] == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deck_model'`

- [ ] **Step 3: Write minimal implementation**

```python
# shared/deck_model.py
"""Pure, immutable helpers for the SlideDecks data model.

Every mutator returns a NEW dict and never mutates its input, matching the
project immutability rule.
"""
from copy import deepcopy
from typing import Optional


def slide_key(deck_id: str, n: int) -> str:
    return f"slides/{deck_id}/v{n}/index.html"


def thumb_key(deck_id: str, n: int) -> str:
    return f"thumbnails/{deck_id}/v{n}.png"


def new_deck_item(deck_id: str, title: str, tags: list, now_iso: str) -> dict:
    return {
        "deckId": deck_id,
        "title": title,
        "tags": list(tags),
        "status": "active",
        "currentVersion": 0,
        "versions": [],
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


def add_version(
    item: dict,
    thumbnail_key: str,
    size_bytes: int,
    now_iso: str,
    slide_count: Optional[int] = None,
) -> dict:
    new_item = deepcopy(item)
    n = new_item["currentVersion"] + 1
    new_item["versions"].append({
        "n": n,
        "createdAt": now_iso,
        "thumbnailKey": thumbnail_key,
        "sizeBytes": size_bytes,
        "slideCount": slide_count,
    })
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def set_current(item: dict, n: int, now_iso: str) -> dict:
    if not any(v["n"] == n for v in item["versions"]):
        raise ValueError(f"version {n} does not exist")
    new_item = deepcopy(item)
    new_item["currentVersion"] = n
    new_item["updatedAt"] = now_iso
    return new_item


def set_status(item: dict, status: str, now_iso: str) -> dict:
    if status not in ("active", "archived"):
        raise ValueError(f"invalid status: {status}")
    new_item = deepcopy(item)
    new_item["status"] = status
    new_item["updatedAt"] = now_iso
    return new_item
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add shared/deck_model.py tests/shared/test_deck_model.py
git commit -m "feat: add immutable SlideDecks data model helpers"
```

---

### Task 3: DynamoDB 덱 리포지토리 (moto)

**Files:**
- Create: `lambdas/api/ddb.py`
- Test: `tests/lambdas/test_ddb.py`

**Interfaces:**
- Consumes: `shared/deck_model.py` (add_version, set_current, set_status, new_deck_item)
- Produces: class `DeckRepo(table_name: str, dynamodb_resource=None)` with:
  - `put(item: dict) -> None`
  - `get(deck_id: str) -> Optional[dict]`
  - `list_by_status(status: str) -> list[dict]` — GSI `byUpdatedAt` 쿼리, `updatedAt` 내림차순
  - `delete(deck_id: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_ddb.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3
import pytest
from moto import mock_aws
from deck_model import new_deck_item, add_version
from ddb import DeckRepo

TABLE = "SlideDecks"


def _make_table(res):
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "byUpdatedAt",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_put_get_roundtrip():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make_table(res)
    repo = DeckRepo(TABLE, res)
    item = new_deck_item("roadmap", "Roadmap", [], "2026-07-21T00:00:00Z")
    repo.put(item)
    assert repo.get("roadmap")["title"] == "Roadmap"
    assert repo.get("missing") is None


@mock_aws
def test_list_by_status_sorted_desc():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make_table(res)
    repo = DeckRepo(TABLE, res)
    a = add_version(new_deck_item("a", "A", [], "t"), "k", 1, "2026-07-21T01:00:00Z")
    b = add_version(new_deck_item("b", "B", [], "t"), "k", 1, "2026-07-21T03:00:00Z")
    c = add_version(new_deck_item("c", "C", [], "t"), "k", 1, "2026-07-21T02:00:00Z")
    for it in (a, b, c):
        repo.put(it)
    ids = [d["deckId"] for d in repo.list_by_status("active")]
    assert ids == ["b", "c", "a"]


@mock_aws
def test_delete():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make_table(res)
    repo = DeckRepo(TABLE, res)
    repo.put(new_deck_item("x", "X", [], "t"))
    repo.delete("x")
    assert repo.get("x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pip install moto boto3 pytest -q && python3 -m pytest tests/lambdas/test_ddb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ddb'`

- [ ] **Step 3: Write minimal implementation**

```python
# lambdas/api/ddb.py
from typing import Optional
import boto3
from boto3.dynamodb.conditions import Key


class DeckRepo:
    def __init__(self, table_name: str, dynamodb_resource=None):
        res = dynamodb_resource or boto3.resource("dynamodb")
        self._table = res.Table(table_name)

    def put(self, item: dict) -> None:
        self._table.put_item(Item=item)

    def get(self, deck_id: str) -> Optional[dict]:
        resp = self._table.get_item(Key={"deckId": deck_id})
        return resp.get("Item")

    def list_by_status(self, status: str) -> list:
        resp = self._table.query(
            IndexName="byUpdatedAt",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,
        )
        return resp.get("Items", [])

    def delete(self, deck_id: str) -> None:
        self._table.delete_item(Key={"deckId": deck_id})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_ddb.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/ddb.py tests/lambdas/test_ddb.py
git commit -m "feat: add DynamoDB deck repository"
```

---

## Phase 2 — API Lambda 핸들러

### Task 4: API 핸들러 (라우팅 + presign + 버전/삭제)

**Files:**
- Create: `lambdas/api/handler.py`
- Create: `lambdas/api/requirements.txt`
- Test: `tests/lambdas/test_api_handler.py`

**Interfaces:**
- Consumes: `DeckRepo` (ddb.py), `deck_model` helpers, `slugify` (slug.py)
- Produces: `handler(event: dict, context=None) -> dict` — API Gateway HTTP API (payload v2) proxy 응답 `{statusCode, headers, body}`. 환경변수 `TABLE_NAME`, `BUCKET_NAME` 사용. 라우팅:
  - `GET /api/decks?status=active|archived` → `{decks: [...]}` (기본 active)
  - `GET /api/decks/{id}` → 덱 item + `versions`에 `url`(각 버전 CloudFront 상대경로 `/slides/{id}/v{n}/index.html`) 부여
  - `POST /api/decks` body `{filename, title?, tags?}` → deckId 슬러그, 없으면 v0 item 생성/저장, `{deckId, version: n+1, uploadUrl}` (presigned PUT, `slide_key(deckId, n+1)`, ct=text/html, 300s)
  - `PUT /api/decks/{id}` → 기존 item 필요, `{deckId, version: currentVersion+1, uploadUrl}` (presigned PUT)
  - `PUT /api/decks/{id}/current` body `{version}` → `set_current` 저장, `{ok: true}`
  - `DELETE /api/decks/{id}` → `set_status archived` 저장, `{ok: true}`
  - `POST /api/decks/{id}/restore` → `set_status active`, `{ok: true}`
  - `DELETE /api/decks/{id}?hard=true` → S3 `slides/{id}/`·`thumbnails/{id}/` 프리픽스 삭제 + `repo.delete`, `{ok: true}`
- presigned URL 생성은 주입 가능한 `s3_client` 인자로 테스트에서 대체. `now_iso()`도 주입 가능(기본 `datetime.now(timezone.utc)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_api_handler.py
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3
import pytest
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def _setup(res_ddb, s3):
    res_ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "byUpdatedAt",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    s3.create_bucket(Bucket=BUCKET)


def _evt(method, path, body=None, path_params=None, qs=None):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
    }


@mock_aws
def test_post_creates_deck_and_returns_upload_url(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h
    resp = h.handler(_evt("POST", "/api/decks", {"filename": "My Deck.html", "title": "My Deck"}))
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["deckId"] == "my-deck"
    assert body["version"] == 1
    assert "uploadUrl" in body


@mock_aws
def test_get_list_defaults_to_active(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import importlib, handler as h
    importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version, set_status
    repo = DeckRepo(TABLE, res)
    active = add_version(new_deck_item("a", "A", [], "t"), "k", 1, "2026-07-21T01:00:00Z")
    arch = set_status(add_version(new_deck_item("b", "B", [], "t"), "k", 1, "2026-07-21T02:00:00Z"), "archived", "t2")
    repo.put(active); repo.put(arch)
    resp = h.handler(_evt("GET", "/api/decks", qs={}))
    ids = [d["deckId"] for d in json.loads(resp["body"])["decks"]]
    assert ids == ["a"]


@mock_aws
def test_delete_soft_then_restore(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import importlib, handler as h
    importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    h.handler(_evt("DELETE", "/api/decks/a", path_params={"id": "a"}))
    assert repo.get("a")["status"] == "archived"
    h.handler(_evt("POST", "/api/decks/a/restore", path_params={"id": "a"}))
    assert repo.get("a")["status"] == "active"


@mock_aws
def test_hard_delete_removes_item_and_objects(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import importlib, handler as h
    importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    s3.put_object(Bucket=BUCKET, Key="slides/a/v1/index.html", Body=b"<html></html>")
    h.handler(_evt("DELETE", "/api/decks/a", path_params={"id": "a"}, qs={"hard": "true"}))
    assert repo.get("a") is None
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix="slides/a/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handler'`

- [ ] **Step 3: Write minimal implementation**

```python
# lambdas/api/handler.py
import json
import os
from datetime import datetime, timezone

import boto3

from ddb import DeckRepo
from slug import slugify
import deck_model as dm

CORS = {"Content-Type": "application/json"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resp(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body)}


def _repo() -> DeckRepo:
    return DeckRepo(os.environ["TABLE_NAME"])


def _s3():
    return boto3.client("s3")


def _bucket() -> str:
    return os.environ["BUCKET_NAME"]


def _upload_url(deck_id: str, n: int) -> str:
    return _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": _bucket(),
            "Key": dm.slide_key(deck_id, n),
            "ContentType": "text/html",
        },
        ExpiresIn=300,
    )


def _method(event):
    return event["requestContext"]["http"]["method"]


def _path(event):
    return event.get("rawPath") or event["requestContext"]["http"]["path"]


def _body(event):
    raw = event.get("body")
    return json.loads(raw) if raw else {}


def _pid(event):
    return (event.get("pathParameters") or {}).get("id")


def handler(event, context=None):
    method = _method(event)
    path = _path(event)
    qs = event.get("queryStringParameters") or {}
    repo = _repo()

    if method == "GET" and path == "/api/decks":
        status = qs.get("status") or "active"
        return _resp(200, {"decks": repo.list_by_status(status)})

    if method == "GET" and _pid(event) and path.endswith(_pid(event)):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        for v in item["versions"]:
            v["url"] = "/" + dm.slide_key(item["deckId"], v["n"])
        return _resp(200, item)

    if method == "POST" and path == "/api/decks":
        body = _body(event)
        deck_id = slugify(body["filename"])
        item = repo.get(deck_id)
        if item is None:
            item = dm.new_deck_item(deck_id, body.get("title", deck_id), body.get("tags", []), now_iso())
            repo.put(item)
        n = item["currentVersion"] + 1
        return _resp(200, {"deckId": deck_id, "version": n, "uploadUrl": _upload_url(deck_id, n)})

    if method == "PUT" and path.endswith("/current"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        try:
            updated = dm.set_current(item, int(_body(event)["version"]), now_iso())
        except ValueError as e:
            return _resp(400, {"error": str(e)})
        repo.put(updated)
        return _resp(200, {"ok": True})

    if method == "PUT" and _pid(event):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        n = item["currentVersion"] + 1
        return _resp(200, {"deckId": item["deckId"], "version": n, "uploadUrl": _upload_url(item["deckId"], n)})

    if method == "POST" and path.endswith("/restore"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        repo.put(dm.set_status(item, "active", now_iso()))
        return _resp(200, {"ok": True})

    if method == "DELETE" and _pid(event):
        deck_id = _pid(event)
        item = repo.get(deck_id)
        if not item:
            return _resp(404, {"error": "not found"})
        if qs.get("hard") == "true":
            s3 = _s3()
            for prefix in (f"slides/{deck_id}/", f"thumbnails/{deck_id}/"):
                listed = s3.list_objects_v2(Bucket=_bucket(), Prefix=prefix)
                keys = [{"Key": o["Key"]} for o in listed.get("Contents", [])]
                if keys:
                    s3.delete_objects(Bucket=_bucket(), Delete={"Objects": keys})
            repo.delete(deck_id)
        else:
            repo.put(dm.set_status(item, "archived", now_iso()))
        return _resp(200, {"ok": True})

    return _resp(404, {"error": "no route"})
```

```
# lambdas/api/requirements.txt
boto3
```

Note: `deck_model.py`는 배포 시 `lambdas/api/`로 복사되거나 공용 레이어로 포함된다(Task 8 CDK에서 처리). 테스트는 `sys.path`로 `shared/`를 로드한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/handler.py lambdas/api/requirements.txt tests/lambdas/test_api_handler.py
git commit -m "feat: add API Lambda handler with versioning and soft/hard delete"
```

---

## Phase 3 — 썸네일 Lambda

### Task 5: 썸네일 캡처 Lambda (키 파싱 + DDB 반영)

**Files:**
- Create: `lambdas/thumbnail/handler.py`
- Create: `lambdas/thumbnail/requirements.txt`
- Test: `tests/lambdas/test_thumbnail.py`

**Interfaces:**
- Consumes: `deck_model` (thumb_key, add_version 규약), `DeckRepo`
- Produces:
  - `parse_key(key: str) -> tuple[str, int]` — `"slides/{deckId}/v{n}/index.html"` → `(deckId, n)`; 형식 불일치 시 `ValueError`
  - `handler(event, context=None)` — S3 Put 이벤트에서 각 record의 key를 파싱, `capture_png(html_bytes) -> bytes`로 썸네일 생성, `thumb_key`에 업로드, DDB item에 해당 버전 append(idempotent: 이미 있으면 갱신). `capture_png`는 모듈 함수로 분리해 테스트에서 monkeypatch.
- 실제 Chromium 캡처는 `capture_png`에 격리 — 단위 테스트는 이 함수를 stub으로 대체하고 키 파싱·S3·DDB 상호작용만 검증한다.

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_thumbnail.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "thumbnail"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3
import pytest
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def test_parse_key():
    import handler as t
    assert t.parse_key("slides/roadmap/v3/index.html") == ("roadmap", 3)
    with pytest.raises(ValueError):
        t.parse_key("slides/bad/index.html")


@mock_aws
def test_handler_appends_version(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "byUpdatedAt",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key="slides/roadmap/v1/index.html", Body=b"<html>deck</html>")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import importlib, handler as t
    importlib.reload(t)
    monkeypatch.setattr(t, "capture_png", lambda html: b"\x89PNG_fake")
    from ddb import DeckRepo
    from deck_model import new_deck_item
    repo = DeckRepo(TABLE, res)
    repo.put(new_deck_item("roadmap", "Roadmap", [], "t0"))
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": "slides/roadmap/v1/index.html"}}}]}
    t.handler(event)
    item = repo.get("roadmap")
    assert item["currentVersion"] == 1
    assert item["versions"][0]["thumbnailKey"] == "thumbnails/roadmap/v1.png"
    assert s3.get_object(Bucket=BUCKET, Key="thumbnails/roadmap/v1.png")["Body"].read() == b"\x89PNG_fake"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_thumbnail.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handler'` (thumbnail)

- [ ] **Step 3: Write minimal implementation**

```python
# lambdas/thumbnail/handler.py
import os
import re
from datetime import datetime, timezone

import boto3

from ddb import DeckRepo
import deck_model as dm

_KEY_RE = re.compile(r"^slides/(?P<deck>[^/]+)/v(?P<n>\d+)/index\.html$")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_key(key: str):
    m = _KEY_RE.match(key)
    if not m:
        raise ValueError(f"unexpected key: {key}")
    return m.group("deck"), int(m.group("n"))


def capture_png(html_bytes: bytes) -> bytes:
    """Render the deck's first frame to a 1920x1080 PNG using headless Chromium.

    Uses the Chromium binary bundled via a Lambda layer at /opt/chromium.
    Isolated here so unit tests can stub it.
    """
    import tempfile
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html_bytes)
        html_path = f.name
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH", "/opt/chromium/chrome"),
            args=["--no-sandbox", "--disable-gpu", "--single-process"],
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"file://{html_path}")
        page.wait_for_timeout(1200)
        png = page.screenshot(type="png")
        browser.close()
    return png


def handler(event, context=None):
    s3 = boto3.client("s3")
    repo = DeckRepo(os.environ["TABLE_NAME"])
    bucket = os.environ["BUCKET_NAME"]
    for record in event.get("Records", []):
        key = record["s3"]["object"]["key"]
        deck_id, n = parse_key(key)
        html = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        png = capture_png(html)
        tkey = dm.thumb_key(deck_id, n)
        s3.put_object(
            Bucket=bucket, Key=tkey, Body=png, ContentType="image/png",
            CacheControl="public, max-age=31536000, immutable",
        )
        item = repo.get(deck_id)
        if item is None:
            item = dm.new_deck_item(deck_id, deck_id, [], now_iso())
        existing = next((v for v in item["versions"] if v["n"] == n), None)
        if existing is None:
            item = dm.add_version(item, tkey, len(html), now_iso())
        else:
            existing["thumbnailKey"] = tkey
            item["updatedAt"] = now_iso()
            item["currentVersion"] = max(item["currentVersion"], n)
        repo.put(item)
```

```
# lambdas/thumbnail/requirements.txt
boto3
playwright
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_thumbnail.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add lambdas/thumbnail/ tests/lambdas/test_thumbnail.py
git commit -m "feat: add thumbnail capture Lambda"
```

---

## Phase 4 — CDK 인프라

### Task 6: CDK 스택 스캐폴딩 + synth 검증

**Files:**
- Create: `infra/app.py`, `infra/cdk.json`, `infra/requirements.txt`, `infra/slidecast/__init__.py`, `infra/slidecast/slidecast_stack.py`
- Test: `tests/infra/test_synth.py`

**Interfaces:**
- Produces: `SlidecastStack(scope, id, **kwargs)` — S3 버킷(프라이빗, 퍼블릭차단), DynamoDB 테이블+GSI, Cognito User Pool(self sign-up off)+client(Hosted UI), API Lambda, Thumbnail Lambda, HTTP API + Cognito JWT authorizer, CloudFront(OAC, `/api/*`→API, `/slides/*`·`/`→S3), S3 이벤트→Thumbnail Lambda. `deck_model.py`는 두 Lambda 자산에 공용 레이어로 포함.

- [ ] **Step 1: Write the failing test**

```python
# tests/infra/test_synth.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template
from slidecast.slidecast_stack import SlidecastStack


def _template():
    app = App()
    stack = SlidecastStack(app, "TestStack", env={"account": "123456789012", "region": "us-east-1"})
    return Template.from_stack(stack)


def test_has_private_bucket():
    t = _template()
    t.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        }
    })


def test_dynamodb_has_gsi():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "GlobalSecondaryIndexes": [{"IndexName": "byUpdatedAt"}],
    })


def test_cognito_self_signup_disabled():
    t = _template()
    t.has_resource_properties("AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
    })


def test_no_public_ingress_alb():
    t = _template()
    # 이 아키텍처엔 ALB/SecurityGroup 자체가 없어야 한다
    assert t.find_resources("AWS::ElasticLoadBalancingV2::LoadBalancer") == {}
    assert t.find_resources("AWS::EC2::SecurityGroup") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pip install aws-cdk-lib constructs -q && python3 -m pytest tests/infra/test_synth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'slidecast'`

- [ ] **Step 3: Write minimal implementation**

```python
# infra/cdk.json
{
  "app": "python3 app.py"
}
```

```
# infra/requirements.txt
aws-cdk-lib>=2.140.0
constructs>=10.0.0
```

```python
# infra/slidecast/__init__.py
```

```python
# infra/app.py
import os
import aws_cdk as cdk
from slidecast.slidecast_stack import SlidecastStack

app = cdk.App()
SlidecastStack(
    app, "SlidecastStack",
    env=cdk.Environment(account="123456789012", region="us-east-1"),
)
app.synth()
```

```python
# infra/slidecast/slidecast_stack.py
from aws_cdk import (
    Stack, RemovalPolicy, Duration, CfnOutput,
    aws_s3 as s3,
    aws_dynamodb as ddb,
    aws_cognito as cognito,
    aws_lambda as lambda_,
    aws_s3_notifications as s3n,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_apigatewayv2_authorizers as authorizers,
    aws_cloudfront as cf,
    aws_cloudfront_origins as origins,
)
from constructs import Construct


class SlidecastStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        bucket = s3.Bucket(
            self, "AssetsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table = ddb.Table(
            self, "SlideDecks",
            partition_key=ddb.Attribute(name="deckId", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="byUpdatedAt",
            partition_key=ddb.Attribute(name="status", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="updatedAt", type=ddb.AttributeType.STRING),
        )

        user_pool = cognito.UserPool(
            self, "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        user_pool_client = user_pool.add_client(
            "WebClient",
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            ),
            generate_secret=False,
        )

        shared_layer = lambda_.LayerVersion(
            self, "SharedLayer",
            code=lambda_.Code.from_asset("../shared_layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
        )

        api_fn = lambda_.Function(
            self, "ApiFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("../lambdas/api"),
            layers=[shared_layer],
            timeout=Duration.seconds(15),
            environment={"TABLE_NAME": table.table_name, "BUCKET_NAME": bucket.bucket_name},
        )
        table.grant_read_write_data(api_fn)
        bucket.grant_read_write(api_fn)

        thumb_fn = lambda_.Function(
            self, "ThumbFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("../lambdas/thumbnail"),
            layers=[shared_layer],
            memory_size=2048,
            timeout=Duration.seconds(60),
            environment={"TABLE_NAME": table.table_name, "BUCKET_NAME": bucket.bucket_name},
        )
        table.grant_read_write_data(thumb_fn)
        bucket.grant_read_write(thumb_fn)
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(thumb_fn),
            s3.NotificationKeyFilter(prefix="slides/", suffix="index.html"),
        )

        authorizer = authorizers.HttpJwtAuthorizer(
            "JwtAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            identity_source=["$request.header.Authorization"],
            jwt_audience=[user_pool_client.user_pool_client_id],
        )
        http_api = apigw.HttpApi(self, "HttpApi", default_authorizer=authorizer)
        http_api.add_routes(
            path="/api/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=integrations.HttpLambdaIntegration("ApiInt", api_fn),
        )

        oac = cf.S3OriginAccessControl(self, "Oac")
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(bucket, origin_access_control=oac)
        api_domain = f"{http_api.api_id}.execute-api.{self.region}.amazonaws.com"
        distribution = cf.Distribution(
            self, "Cdn",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=origins.HttpOrigin(api_domain),
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
        )

        CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
```

Note: `shared_layer`는 `shared_layer/python/deck_model.py` 구조로 빌드해야 한다 — Task 6 Step 3.5에서 준비 스크립트를 추가한다.

- [ ] **Step 3.5: shared layer 준비 스크립트**

```bash
# 배포 전 실행: shared/deck_model.py를 레이어 구조로 복사
mkdir -p shared_layer/python
cp shared/deck_model.py shared_layer/python/deck_model.py
```

또한 `deck_model`을 import하는 `ddb.py`도 레이어에서 로드되므로, `ddb.py`와 `slug.py`는 각 Lambda 자산 디렉터리(`lambdas/api`)에 이미 있고 `deck_model`만 레이어로 공유된다. Thumbnail Lambda는 `ddb.py`가 필요하므로 배포 준비 시 `cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py` 한다(빌드 스크립트에 포함).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && mkdir -p shared_layer/python && cp shared/deck_model.py shared_layer/python/ && cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py && python3 -m pytest tests/infra/test_synth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add infra/ tests/infra/test_synth.py
echo "shared_layer/" >> .gitignore
git add .gitignore
git commit -m "feat: add CDK stack for serverless slide viewer"
```

---

### Task 7: 첫 배포 + Cognito 사용자 생성 + 스모크 테스트

**Files:**
- Create: `scripts/deploy.sh`, `scripts/create-user.sh`
- Modify: none

**Interfaces:**
- Produces: 배포 스크립트 (build shared layer → cdk bootstrap(최초) → cdk deploy), 사용자 생성 스크립트.

- [ ] **Step 1: 배포 스크립트 작성**

```bash
# scripts/deploy.sh
#!/usr/bin/env bash
set -euo pipefail
export AWS_PROFILE=profile2
export AWS_REGION=us-east-1
cd "$(dirname "$0")/.."

# 1) shared layer + thumbnail ddb 준비
mkdir -p shared_layer/python
cp shared/deck_model.py shared_layer/python/deck_model.py
cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py
cp lambdas/api/slug.py lambdas/thumbnail/slug.py 2>/dev/null || true

# 2) CDK
cd infra
python3 -m pip install -r requirements.txt -q
npx cdk bootstrap aws://123456789012/us-east-1 || true
npx cdk deploy --require-approval never --outputs-file ../cdk-outputs.json
```

- [ ] **Step 2: 실행 (사람이 실행, 로그 확인)**

Run: `cd /Workshop/html-viewer && chmod +x scripts/*.sh && ./scripts/deploy.sh 2>&1 | tail -40`
Expected: `SlidecastStack` 배포 완료, `cdk-outputs.json`에 `DistributionDomain`, `UserPoolId`, `UserPoolClientId`, `BucketName` 출력. 진행 상황은 `nohup ... &` 후 30-60초 폴링 방식 권장(5분+ 블로킹 금지).

- [ ] **Step 3: Cognito 사용자 생성 스크립트**

```bash
# scripts/create-user.sh
#!/usr/bin/env bash
set -euo pipefail
export AWS_PROFILE=profile2
export AWS_REGION=us-east-1
POOL_ID=$(python3 -c "import json;print(json.load(open('$(dirname "$0")/../cdk-outputs.json'))['SlidecastStack']['UserPoolId'])")
EMAIL="${1:?usage: create-user.sh <email>}"
aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true
echo "사용자 생성됨. 임시 비밀번호가 이메일로 전송됩니다."
```

- [ ] **Step 4: 스모크 테스트 (배포 검증)**

Run:
```bash
cd /Workshop/html-viewer
DOMAIN=$(python3 -c "import json;print(json.load(open('cdk-outputs.json'))['SlidecastStack']['DistributionDomain'])")
curl -s -o /dev/null -w "%{http_code}\n" "https://$DOMAIN/api/decks"
```
Expected: `401` (authorizer가 인증 없는 요청 차단 — 인프라가 올바르게 보호되고 있음을 확인).

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy.sh scripts/create-user.sh
git commit -m "chore: add deploy and user creation scripts"
```

---

## Phase 5 — React 뷰어 SPA (다크 시네마틱)

> 참고: 이 페이즈 시작 시 `frontend-design` 또는 `ui-ux-pro-max` 스킬을 활성화해 다크 시네마틱 방향(딥 배경, 글래스모피즘 카드, 부드러운 모션, 대형 타이포)을 구체화한다.

### Task 8: Vite 스캐폴딩 + 타입 + API 클라이언트

**Files:**
- Create: `viewer/package.json`, `viewer/vite.config.ts`, `viewer/index.html`, `viewer/src/main.tsx`, `viewer/src/types.ts`, `viewer/src/api.ts`
- Test: `viewer/src/api.test.ts` (vitest)

**Interfaces:**
- Produces:
  - `types.ts`: `Version {n, createdAt, thumbnailKey, sizeBytes, slideCount?, url?}`, `Deck {deckId, title, tags, status, currentVersion, versions: Version[], createdAt, updatedAt}`
  - `api.ts`: `createApi(baseUrl, getToken: () => string)` → `{ listDecks(status?), getDeck(id), createUpload(filename,title,tags), updateUpload(id), setCurrent(id,n), softDelete(id), restore(id), hardDelete(id), uploadFile(url, file) }`. 모든 `/api` 호출은 `Authorization: Bearer {token}` 첨부.

- [ ] **Step 1: Write the failing test**

```ts
// viewer/src/api.test.ts
import { describe, it, expect, vi } from "vitest";
import { createApi } from "./api";

describe("api client", () => {
  it("attaches bearer token and parses decks", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ decks: [{ deckId: "a" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "TOKEN");
    const decks = await api.listDecks();
    expect(decks[0].deckId).toBe("a");
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer TOKEN");
  });

  it("uploadFile PUTs with text/html content-type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi("", () => "T");
    await api.uploadFile("https://s3/put", new Blob(["<html>"], { type: "text/html" }));
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("https://s3/put");
    expect(opts.method).toBe("PUT");
    expect(opts.headers["Content-Type"]).toBe("text/html");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npm install && npx vitest run src/api.test.ts`
Expected: FAIL — cannot find `./api`

- [ ] **Step 3: Write minimal implementation**

```json
// viewer/package.json
{
  "name": "slidecast-viewer",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "oidc-client-ts": "^3.1.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

```ts
// viewer/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], build: { outDir: "dist" } });
```

```ts
// viewer/src/types.ts
export interface Version {
  n: number;
  createdAt: string;
  thumbnailKey: string;
  sizeBytes: number;
  slideCount?: number;
  url?: string;
}
export interface Deck {
  deckId: string;
  title: string;
  tags: string[];
  status: "active" | "archived";
  currentVersion: number;
  versions: Version[];
  createdAt: string;
  updatedAt: string;
}
```

```ts
// viewer/src/api.ts
import type { Deck } from "./types";

export function createApi(baseUrl: string, getToken: () => string) {
  const auth = () => ({ Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" });
  const j = async (r: Response) => {
    if (!r.ok) throw new Error(`api ${r.status}`);
    return r.json();
  };
  return {
    async listDecks(status = "active"): Promise<Deck[]> {
      const r = await fetch(`${baseUrl}/api/decks?status=${status}`, { headers: auth() });
      return (await j(r)).decks;
    },
    async getDeck(id: string): Promise<Deck> {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { headers: auth() }));
    },
    async createUpload(filename: string, title?: string, tags: string[] = []) {
      return j(await fetch(`${baseUrl}/api/decks`, {
        method: "POST", headers: auth(), body: JSON.stringify({ filename, title, tags }),
      }));
    },
    async updateUpload(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { method: "PUT", headers: auth() }));
    },
    async setCurrent(id: string, n: number) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/current`, {
        method: "PUT", headers: auth(), body: JSON.stringify({ version: n }),
      }));
    },
    async softDelete(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}`, { method: "DELETE", headers: auth() }));
    },
    async restore(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/restore`, { method: "POST", headers: auth() }));
    },
    async hardDelete(id: string) {
      return j(await fetch(`${baseUrl}/api/decks/${id}?hard=true`, { method: "DELETE", headers: auth() }));
    },
    async uploadFile(url: string, file: Blob) {
      const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "text/html" }, body: file });
      if (!r.ok) throw new Error(`upload ${r.status}`);
    },
  };
}
```

```html
<!-- viewer/index.html -->
<!doctype html>
<html lang="ko">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>Slidecast</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

```tsx
// viewer/src/main.tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme.css";
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/api.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add viewer/package.json viewer/vite.config.ts viewer/index.html viewer/src/main.tsx viewer/src/types.ts viewer/src/api.ts viewer/src/api.test.ts
echo "node_modules/" >> .gitignore && echo "viewer/dist/" >> .gitignore && git add .gitignore
git commit -m "feat: scaffold viewer SPA with typed API client"
```

---

### Task 9: 인증 + 앱 셸 + 다크 시네마틱 테마

**Files:**
- Create: `viewer/src/auth.ts`, `viewer/src/App.tsx`, `viewer/src/theme.css`
- Test: `viewer/src/auth.test.ts`

**Interfaces:**
- Consumes: oidc-client-ts, `createApi`
- Produces:
  - `auth.ts`: `makeAuth(config)` → `{ login(), logout(), getToken(): string, isAuthenticated(): boolean, handleCallback() }` (Cognito Hosted UI, authorization code + PKCE). config는 `viewer/src/config.ts`(빌드 시 CDK outputs로 주입) 또는 `import.meta.env`.
  - `App.tsx`: 미인증 시 로그인 화면, 인증 시 `<Gallery/>` 렌더.
  - `theme.css`: 다크 시네마틱 디자인 토큰(CSS 변수: `--bg`, `--surface`, `--accent`, 그라디언트, 그림자, 폰트 스케일).

- [ ] **Step 1: Write the failing test**

```ts
// viewer/src/auth.test.ts
import { describe, it, expect } from "vitest";
import { buildAuthConfig } from "./auth";

describe("auth config", () => {
  it("builds cognito authority and redirect", () => {
    const c = buildAuthConfig({
      region: "us-east-1", userPoolId: "us-east-1_ABC",
      clientId: "cid", domain: "d.example.com",
    });
    expect(c.authority).toContain("cognito-idp.us-east-1.amazonaws.com/us-east-1_ABC");
    expect(c.client_id).toBe("cid");
    expect(c.redirect_uri).toContain(window.location.origin);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/auth.test.ts`
Expected: FAIL — cannot find `buildAuthConfig`

- [ ] **Step 3: Write minimal implementation**

```ts
// viewer/src/auth.ts
import { UserManager, WebStorageStateStore } from "oidc-client-ts";

export interface CognitoConfig {
  region: string; userPoolId: string; clientId: string; domain: string;
}

export function buildAuthConfig(c: CognitoConfig) {
  return {
    authority: `https://cognito-idp.${c.region}.amazonaws.com/${c.userPoolId}`,
    client_id: c.clientId,
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: "code",
    scope: "openid email",
    userStore: new WebStorageStateStore({ store: window.localStorage }),
  };
}

export function makeAuth(c: CognitoConfig) {
  const mgr = new UserManager(buildAuthConfig(c));
  let user: any = null;
  return {
    async init() { user = await mgr.getUser(); },
    async handleCallback() {
      if (window.location.search.includes("code=")) {
        user = await mgr.signinRedirectCallback();
        window.history.replaceState({}, "", "/");
      }
    },
    login: () => mgr.signinRedirect(),
    logout: () => mgr.signoutRedirect(),
    getToken: () => user?.id_token ?? "",
    isAuthenticated: () => !!user && !user.expired,
  };
}
```

```css
/* viewer/src/theme.css */
:root {
  --bg: #07070b;
  --bg-2: #0d0e15;
  --surface: rgba(255,255,255,0.04);
  --surface-hover: rgba(255,255,255,0.08);
  --border: rgba(255,255,255,0.10);
  --text: #f4f5fb;
  --text-dim: #9aa0b4;
  --accent: #6d7dff;
  --accent-2: #b06dff;
  --grad: linear-gradient(135deg, var(--accent), var(--accent-2));
  --shadow: 0 20px 60px rgba(0,0,0,0.55);
  --font: "Inter", system-ui, -apple-system, "Pretendard", sans-serif;
}
* { box-sizing: border-box; }
html, body, #root { height: 100%; margin: 0; }
body {
  background: radial-gradient(1200px 800px at 70% -10%, #1a1440 0%, var(--bg) 60%), var(--bg);
  color: var(--text); font-family: var(--font);
  -webkit-font-smoothing: antialiased;
}
.h1 { font-size: 56px; font-weight: 800; letter-spacing: -0.03em; }
button { font-family: var(--font); cursor: pointer; }
```

```tsx
// viewer/src/App.tsx
import { useEffect, useState } from "react";
import { makeAuth, type CognitoConfig } from "./auth";
import { createApi } from "./api";
import { Gallery } from "./components/Gallery";

// config.ts는 배포 빌드 시 CDK outputs로 생성. 개발 중엔 env 사용.
const cfg: CognitoConfig = {
  region: import.meta.env.VITE_REGION ?? "us-east-1",
  userPoolId: import.meta.env.VITE_USER_POOL_ID ?? "",
  clientId: import.meta.env.VITE_CLIENT_ID ?? "",
  domain: import.meta.env.VITE_COGNITO_DOMAIN ?? "",
};
const auth = makeAuth(cfg);

export function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    (async () => {
      await auth.init();
      await auth.handleCallback();
      setAuthed(auth.isAuthenticated());
      setReady(true);
    })();
  }, []);
  if (!ready) return <div style={{ padding: 48 }}>로딩 중...</div>;
  if (!authed)
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
        <div style={{ textAlign: "center" }}>
          <div className="h1" style={{ backgroundImage: "var(--grad)", WebkitBackgroundClip: "text", color: "transparent" }}>Slidecast</div>
          <p style={{ color: "var(--text-dim)" }}>HTML 슬라이드 시네마</p>
          <button onClick={() => auth.login()} style={{ marginTop: 24, padding: "14px 28px", borderRadius: 12, border: "none", background: "var(--grad)", color: "#fff", fontSize: 16 }}>로그인</button>
        </div>
      </div>
    );
  const api = createApi("", () => auth.getToken());
  return <Gallery api={api} onLogout={() => auth.logout()} />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/auth.test.ts`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add viewer/src/auth.ts viewer/src/auth.test.ts viewer/src/App.tsx viewer/src/theme.css
git commit -m "feat: add Cognito auth and dark cinematic app shell"
```

---

### Task 10: 갤러리 + 카드 + 업로드 + 재생 + 버전 메뉴

**Files:**
- Create: `viewer/src/components/Gallery.tsx`, `DeckCard.tsx`, `Player.tsx`, `VersionMenu.tsx`, `UploadZone.tsx`
- Test: `viewer/src/components/Gallery.test.tsx`

**Interfaces:**
- Consumes: `createApi` 반환 객체, `Deck`/`Version` 타입
- Produces: `<Gallery api onLogout />` — 마운트 시 `listDecks()` 로드, 검색/태그 필터, 활성/보관함 토글. `<DeckCard deck onPlay onEdit onDelete onVersions />`. `<Player src onClose />` (풀스크린 iframe). `<VersionMenu deck onRollback onPlayVersion />`. `<UploadZone onUpload(file) />` (드래그앤드롭 → createUpload/updateUpload → uploadFile). 썸네일 URL은 `/{version.thumbnailKey}` (CloudFront 상대경로).

- [ ] **Step 1: Write the failing test**

```tsx
// viewer/src/components/Gallery.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Gallery } from "./Gallery";

const fakeApi = {
  listDecks: vi.fn().mockResolvedValue([
    { deckId: "a", title: "Alpha", tags: [], status: "active", currentVersion: 1,
      versions: [{ n: 1, createdAt: "t", thumbnailKey: "thumbnails/a/v1.png", sizeBytes: 1 }],
      createdAt: "t", updatedAt: "t" },
  ]),
} as any;

describe("Gallery", () => {
  it("renders deck cards from api", async () => {
    render(<Gallery api={fakeApi} onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeTruthy());
    expect(fakeApi.listDecks).toHaveBeenCalledWith("active");
  });
});
```

Add devDeps: `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`; set `vitest` env to jsdom in `vite.config.ts` (`test: { environment: "jsdom" }`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npm i -D @testing-library/react @testing-library/jest-dom jsdom && npx vitest run src/components/Gallery.test.tsx`
Expected: FAIL — cannot find `./Gallery`

- [ ] **Step 3: Write minimal implementation**

```tsx
// viewer/src/components/Player.tsx
export function Player({ src, onClose }: { src: string; onClose: () => void }) {
  return (
    <div onKeyDown={(e) => e.key === "Escape" && onClose()} tabIndex={0}
      style={{ position: "fixed", inset: 0, background: "#000", zIndex: 100 }}>
      <button onClick={onClose}
        style={{ position: "absolute", top: 16, right: 16, zIndex: 101, padding: "8px 16px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}>
        닫기 (ESC)
      </button>
      <iframe title="deck" src={src} style={{ width: "100%", height: "100%", border: "none" }} />
    </div>
  );
}
```

```tsx
// viewer/src/components/VersionMenu.tsx
import type { Deck } from "../types";
export function VersionMenu({ deck, onRollback, onPlayVersion }: {
  deck: Deck; onRollback: (n: number) => void; onPlayVersion: (n: number) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {deck.versions.slice().reverse().map((v) => (
        <div key={v.n} style={{ display: "flex", alignItems: "center", gap: 12, padding: 8, border: "1px solid var(--border)", borderRadius: 8 }}>
          <img src={`/${v.thumbnailKey}`} alt="" width={96} style={{ borderRadius: 4 }} />
          <span>v{v.n}{v.n === deck.currentVersion ? " (현재)" : ""}</span>
          <span style={{ color: "var(--text-dim)", fontSize: 13 }}>{v.createdAt}</span>
          <button onClick={() => onPlayVersion(v.n)}>재생</button>
          {v.n !== deck.currentVersion && <button onClick={() => onRollback(v.n)}>이 버전으로</button>}
        </div>
      ))}
    </div>
  );
}
```

```tsx
// viewer/src/components/UploadZone.tsx
import { useState } from "react";
export function UploadZone({ onUpload }: { onUpload: (file: File) => void }) {
  const [over, setOver] = useState(false);
  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onUpload(f); }}
      style={{ display: "grid", placeItems: "center", padding: 32, borderRadius: 16,
        border: `2px dashed ${over ? "var(--accent)" : "var(--border)"}`, background: over ? "var(--surface-hover)" : "var(--surface)", cursor: "pointer" }}>
      <input type="file" accept=".html" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
      <span style={{ color: "var(--text-dim)" }}>HTML 덱을 드래그하거나 클릭해 업로드</span>
    </label>
  );
}
```

```tsx
// viewer/src/components/DeckCard.tsx
import type { Deck } from "../types";
export function DeckCard({ deck, onPlay, onVersions, onDelete }: {
  deck: Deck; onPlay: () => void; onVersions: () => void; onDelete: () => void;
}) {
  const cur = deck.versions.find((v) => v.n === deck.currentVersion);
  return (
    <div style={{ borderRadius: 16, overflow: "hidden", background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}>
      <div onClick={onPlay} style={{ cursor: "pointer", aspectRatio: "16/9", background: "#000" }}>
        {cur && <img src={`/${cur.thumbnailKey}`} alt={deck.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
      </div>
      <div style={{ padding: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>{deck.title}</div>
        <div style={{ color: "var(--text-dim)", fontSize: 13, marginTop: 4 }}>v{deck.currentVersion} · {deck.updatedAt}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={onPlay}>재생</button>
          <button onClick={onVersions}>버전</button>
          <button onClick={onDelete}>삭제</button>
        </div>
      </div>
    </div>
  );
}
```

```tsx
// viewer/src/components/Gallery.tsx
import { useEffect, useState } from "react";
import type { Deck } from "../types";
import { DeckCard } from "./DeckCard";
import { Player } from "./Player";
import { VersionMenu } from "./VersionMenu";
import { UploadZone } from "./UploadZone";

export function Gallery({ api, onLogout }: { api: any; onLogout: () => void }) {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [query, setQuery] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [versionsOf, setVersionsOf] = useState<Deck | null>(null);

  const reload = async (s = status) => setDecks(await api.listDecks(s));
  useEffect(() => { reload(status); }, [status]);

  const upload = async (file: File) => {
    const { deckId, uploadUrl } = await api.createUpload(file.name, file.name.replace(/\.html$/i, ""));
    await api.uploadFile(uploadUrl, file);
    setTimeout(() => reload(), 2500); // 썸네일 생성 대기
    return deckId;
  };

  const play = (d: Deck) => setPlaying(`/slides/${d.deckId}/v${d.currentVersion}/index.html`);
  const shown = decks.filter((d) => d.title.toLowerCase().includes(query.toLowerCase()));

  return (
    <div style={{ padding: 32, maxWidth: 1400, margin: "0 auto" }}>
      <header style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div className="h1" style={{ fontSize: 32 }}>Slidecast</div>
        <input placeholder="검색" value={query} onChange={(e) => setQuery(e.target.value)}
          style={{ marginLeft: "auto", padding: "8px 14px", borderRadius: 10, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }} />
        <button onClick={() => setStatus(status === "active" ? "archived" : "active")}>{status === "active" ? "보관함" : "활성"}</button>
        <button onClick={onLogout}>로그아웃</button>
      </header>
      <div style={{ marginBottom: 24 }}><UploadZone onUpload={upload} /></div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 24 }}>
        {shown.map((d) => (
          <DeckCard key={d.deckId} deck={d}
            onPlay={() => play(d)}
            onVersions={() => setVersionsOf(d)}
            onDelete={async () => {
              if (status === "active") { await api.softDelete(d.deckId); } else { await api.hardDelete(d.deckId); }
              reload();
            }} />
        ))}
      </div>
      {versionsOf && (
        <div onClick={() => setVersionsOf(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: "var(--bg-2)", padding: 24, borderRadius: 16, minWidth: 480 }}>
            <VersionMenu deck={versionsOf}
              onRollback={async (n) => { await api.setCurrent(versionsOf.deckId, n); setVersionsOf(null); reload(); }}
              onPlayVersion={(n) => { setPlaying(`/slides/${versionsOf.deckId}/v${n}/index.html`); setVersionsOf(null); }} />
          </div>
        </div>
      )}
      {playing && <Player src={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/components/Gallery.test.tsx`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add viewer/src/components/ viewer/vite.config.ts
git commit -m "feat: add gallery, player, version menu, and upload UI"
```

---

### Task 11: 뷰어 빌드 + S3 배포 + CloudFront에 SPA 연결

**Files:**
- Create: `scripts/deploy-viewer.sh`
- Modify: `infra/slidecast/slidecast_stack.py` (BucketDeployment로 `viewer/dist` → `web/`, 단 SPA는 루트 서빙이므로 배포 전략은 스크립트 방식 채택)

**Interfaces:**
- Produces: 뷰어를 빌드해 S3 루트(`index.html` 등)에 업로드하고 CloudFront 캐시 무효화하는 스크립트. config는 CDK outputs에서 env로 주입.

- [ ] **Step 1: 배포 스크립트 작성**

```bash
# scripts/deploy-viewer.sh
#!/usr/bin/env bash
set -euo pipefail
export AWS_PROFILE=profile2
export AWS_REGION=us-east-1
cd "$(dirname "$0")/.."
O=cdk-outputs.json
BUCKET=$(python3 -c "import json;print(json.load(open('$O'))['SlidecastStack']['BucketName'])")
POOL=$(python3 -c "import json;print(json.load(open('$O'))['SlidecastStack']['UserPoolId'])")
CLIENT=$(python3 -c "import json;print(json.load(open('$O'))['SlidecastStack']['UserPoolClientId'])")
DOMAIN=$(python3 -c "import json;print(json.load(open('$O'))['SlidecastStack']['DistributionDomain'])")

cd viewer
VITE_REGION=us-east-1 VITE_USER_POOL_ID="$POOL" VITE_CLIENT_ID="$CLIENT" npm run build
aws s3 sync dist/ "s3://$BUCKET/" --delete
# 덱/썸네일 프리픽스는 sync --delete 대상에서 보호됨 (dist엔 slides/·thumbnails/ 없음, 루트만 sync)
echo "배포 완료: https://$DOMAIN"
```

Note: `--delete`가 `slides/`·`thumbnails/`를 지우지 않도록, 뷰어 자산은 별도 프리픽스 없이 루트에 두되 sync는 `dist/` 내용만 대상으로 한다. 안전을 위해 `--exclude "slides/*" --exclude "thumbnails/*"`를 추가한다.

- [ ] **Step 2: 스크립트에 프리픽스 보호 반영**

```bash
# deploy-viewer.sh의 sync 라인을 다음으로 교체
aws s3 sync dist/ "s3://$BUCKET/" --delete --exclude "slides/*" --exclude "thumbnails/*" --exclude "web/*"
```

- [ ] **Step 3: 실행 및 검증**

Run: `cd /Workshop/html-viewer && chmod +x scripts/deploy-viewer.sh && ./scripts/deploy-viewer.sh`
Expected: 빌드 성공, S3 sync 완료, `https://<domain>` 출력.

- [ ] **Step 4: 브라우저 스모크 (수동/agent-browser)**

CloudFront 도메인 접속 → 로그인 화면 표시 확인. Cognito Hosted UI 로그인 후 갤러리 표시. (agent-browser는 CDP 방식으로 headless 서버에서 구동 — rules/agent-browser.md 참조.)
Expected: 로그인 → 빈 갤러리 + 업로드 존 표시.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy-viewer.sh
git commit -m "chore: add viewer build and deploy script"
```

---

## Phase 6 — 로컬 스킬

### Task 12: slidecast-append 스킬 (업로드/버전/삭제)

**Files:**
- Create: `skill/slidecast-append/slidecast_append.py`, `skill/slidecast-append/SKILL.md`
- Test: `tests/skill/test_slidecast_append.py`

**Interfaces:**
- Consumes: `deck_model`, boto3 (profile2)
- Produces:
  - `resolve_target(repo, deck_id) -> int` — 기존 item 있으면 `currentVersion+1`, 없으면 1
  - `append(html_path, table, bucket, dynamodb=None, s3=None, capture=None, title=None, tags=None)` — 슬러그 계산 → 대상 버전 → S3 PUT(`slide_key`) → 썸네일 캡처+PUT(`thumb_key`) → DDB upsert(add_version). `capture`는 주입 가능(테스트 stub).
  - `rollback(deck_id, n, table, dynamodb=None)`, `soft_delete(...)`, `hard_delete(...)`
  - CLI: `python slidecast_append.py <file.html> [--title T] [--tags a,b]`, `--rollback <id> <n>`, `--delete <id> [--hard]`

- [ ] **Step 1: Write the failing test**

```python
# tests/skill/test_slidecast_append.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill", "slidecast-append"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, tempfile
import pytest
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def _mk(res, s3):
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "byUpdatedAt",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    s3.create_bucket(Bucket=BUCKET)


@mock_aws
def test_append_then_update_increments_version():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    with tempfile.NamedTemporaryFile(suffix="=roadmap.html", delete=False) as f:
        f.write(b"<html>deck</html>"); path = f.name
    # 파일명 슬러그가 안정적이도록 명시적 이름 사용
    import shutil
    named = os.path.join(tempfile.gettempdir(), "roadmap.html")
    shutil.copy(path, named)
    stub = lambda html: b"PNG"
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    repo = DeckRepo(TABLE, res)
    assert repo.get("roadmap")["currentVersion"] == 1
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    assert repo.get("roadmap")["currentVersion"] == 2
    assert s3.get_object(Bucket=BUCKET, Key="slides/roadmap/v2/index.html")


@mock_aws
def test_soft_and_hard_delete():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import shutil, tempfile
    named = os.path.join(tempfile.gettempdir(), "gamma.html")
    open(named, "wb").write(b"<html>g</html>")
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=lambda h: b"P")
    repo = DeckRepo(TABLE, res)
    sa.soft_delete("gamma", TABLE, dynamodb=res)
    assert repo.get("gamma")["status"] == "archived"
    sa.hard_delete("gamma", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert repo.get("gamma") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'slidecast_append'`

- [ ] **Step 3: Write minimal implementation**

```python
# skill/slidecast-append/slidecast_append.py
"""Append/update/delete a self-contained HTML deck into Slidecast using
profile2 credentials directly (no API auth needed)."""
import argparse
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
import deck_model as dm
from ddb import DeckRepo
from slug import slugify

DEFAULT_TABLE = "SlideDecks"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _capture_local(html: bytes) -> bytes:
    from playwright.sync_api import sync_playwright
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html); p = f.name
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"file://{p}"); page.wait_for_timeout(1200)
        png = page.screenshot(type="png"); b.close()
    return png


def resolve_target(repo: DeckRepo, deck_id: str) -> int:
    item = repo.get(deck_id)
    return (item["currentVersion"] + 1) if item else 1


def append(html_path, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None,
           capture=None, title=None, tags=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    res = dynamodb or boto3.resource("dynamodb")
    capture = capture or _capture_local
    repo = DeckRepo(table, res)

    deck_id = slugify(html_path)
    n = resolve_target(repo, deck_id)
    html = open(html_path, "rb").read()

    s3.put_object(Bucket=bucket, Key=dm.slide_key(deck_id, n), Body=html,
                  ContentType="text/html",
                  CacheControl="public, max-age=31536000, immutable")
    png = capture(html)
    tkey = dm.thumb_key(deck_id, n)
    s3.put_object(Bucket=bucket, Key=tkey, Body=png, ContentType="image/png",
                  CacheControl="public, max-age=31536000, immutable")

    item = repo.get(deck_id)
    if item is None:
        item = dm.new_deck_item(deck_id, title or deck_id, tags or [], now_iso())
    item = dm.add_version(item, tkey, len(html), now_iso())
    repo.put(item)
    return deck_id, n


def rollback(deck_id, n, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    repo.put(dm.set_current(item, n, now_iso()))


def soft_delete(deck_id, table=DEFAULT_TABLE, dynamodb=None):
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    item = repo.get(deck_id)
    if not item:
        raise SystemExit(f"deck not found: {deck_id}")
    repo.put(dm.set_status(item, "archived", now_iso()))


def hard_delete(deck_id, table=DEFAULT_TABLE, bucket=None, dynamodb=None, s3=None):
    bucket = bucket or os.environ["BUCKET_NAME"]
    s3 = s3 or boto3.client("s3")
    repo = DeckRepo(table, dynamodb or boto3.resource("dynamodb"))
    for prefix in (f"slides/{deck_id}/", f"thumbnails/{deck_id}/"):
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        keys = [{"Key": o["Key"]} for o in listed.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
    repo.delete(deck_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="?")
    ap.add_argument("--title")
    ap.add_argument("--tags")
    ap.add_argument("--rollback", nargs=2, metavar=("DECK", "N"))
    ap.add_argument("--delete", metavar="DECK")
    ap.add_argument("--hard", action="store_true")
    a = ap.parse_args()
    table = os.environ.get("SLIDECAST_TABLE", DEFAULT_TABLE)
    if a.rollback:
        rollback(a.rollback[0], int(a.rollback[1]), table); return
    if a.delete:
        (hard_delete if a.hard else soft_delete)(a.delete, table) if a.hard else soft_delete(a.delete, table)
        return
    if a.html:
        tags = a.tags.split(",") if a.tags else []
        deck_id, n = append(a.html, table, title=a.title, tags=tags)
        print(f"업로드 완료: {deck_id} v{n}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
```

```markdown
<!-- skill/slidecast-append/SKILL.md -->
---
name: slidecast-append
description: Slidecast 뷰어에 html-slide로 만든 HTML 덱을 업로드/수정(버전)/삭제한다. profile2 자격증명으로 S3+DynamoDB에 직접 반영한다. "슬라이드 뷰어에 올려", "slidecast append", "덱 배포"에 트리거.
---

# slidecast-append

방금 만든 self-contained HTML 슬라이드 덱을 Slidecast 갤러리에 반영한다.

## 사전 요구
- `export AWS_PROFILE=profile2 AWS_REGION=us-east-1`
- `export BUCKET_NAME=<cdk-outputs의 BucketName>`
- (선택) `export SLIDECAST_TABLE=SlideDecks`
- playwright chromium: `python3 -m playwright install chromium`

## 사용
- 신규/수정 업로드: `python3 slidecast_append.py deck.html --title "제목" --tags biz,2026`
  - 파일명 슬러그가 기존 덱과 같으면 새 버전으로 추가된다.
- 롤백: `python3 slidecast_append.py --rollback <deckId> <n>`
- 소프트 삭제: `python3 slidecast_append.py --delete <deckId>`
- 영구 삭제: `python3 slidecast_append.py --delete <deckId> --hard`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add skill/ tests/skill/test_slidecast_append.py
git commit -m "feat: add slidecast-append local skill"
```

---

### Task 13: 전체 통합 검증 + codex review 게이트

**Files:**
- Create: `README.md`

**Interfaces:** none (검증 태스크)

- [ ] **Step 1: 전체 유닛 테스트**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/ -v && (cd viewer && npx vitest run)`
Expected: 모든 Python + TS 테스트 통과.

- [ ] **Step 2: 엔드투엔드 수동 검증 (배포된 환경)**

1. 로컬 스킬로 덱 업로드 → 갤러리에 나타나는지
2. 웹에서 같은 파일명 덱 재업로드 → v2 생성, 버전 메뉴에 v1/v2
3. v1으로 롤백 → 재생 시 v1 표시
4. 소프트 삭제 → 보관함 이동, 복원 → 활성 복귀
5. 하드 삭제 → S3/DDB에서 제거 확인

각 단계 결과를 tool result로 확인 후에만 "통과" 보고 (progress claims를 실제 증거에 대조).

- [ ] **Step 3: README 작성**

프로젝트 개요, 아키텍처 다이어그램(텍스트), 배포 순서(`deploy.sh` → `create-user.sh` → `deploy-viewer.sh`), 로컬 스킬 사용법 기록.

- [ ] **Step 4: codex review 게이트 (필수)**

Run: codex review 스킬로 전체 diff 리뷰 (서버 룰: 코드 작업 후 자기 리뷰 함정 방지, 통과 후에만 최종 커밋/배포).
Expected: CRITICAL/HIGH 이슈 0, 또는 발견 시 수정 후 재리뷰.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add README with architecture and deploy guide"
```

---

## Self-Review (계획 검토)

- **Spec coverage:** 서버리스 아키텍처(Task 6), S3 버전 레이아웃+DDB 모델(Task 2,3,6), API 6종 엔드포인트+소프트/하드 삭제+롤백(Task 4), 썸네일 헤드리스 캡처(Task 5), Cognito self sign-up off(Task 6,7), 다크 시네마틱 SPA+갤러리+재생+버전+업로드(Task 8-11), 로컬 스킬 append/update/rollback/delete(Task 12), 버전 히스토리(Task 2,4,5,10,12) — 스펙 전 항목 커버.
- **Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. TBD/TODO 없음. (Player의 ESC 핸들링은 iframe 포커스 이슈가 있을 수 있어 Task 10에서 컨테이너 keydown + tabIndex로 처리; 실행 중 미흡하면 document 레벨 리스너로 보강.)
- **Type consistency:** `slide_key`/`thumb_key`/`add_version`/`set_current`/`set_status` 시그니처가 Task 2 정의와 Task 4·5·12 사용처에서 일치. `DeckRepo` 메서드(`put/get/list_by_status/delete`)가 Task 3 정의와 이후 사용처 일치. API 응답 필드(`deckId, version, uploadUrl`)가 handler와 api.ts에서 일치.
- **주의:** shared layer 준비(`shared_layer/python/deck_model.py`)와 `ddb.py`/`slug.py`를 thumbnail Lambda 자산으로 복사하는 단계가 배포 스크립트(Task 7,6)에 포함됨 — 이 복사 없이는 Lambda import 실패하므로 실행 시 필수.
