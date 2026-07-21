# Slidecast v2 (Groups / Alias / Date) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 배포된 Slidecast에 그룹 관리, 짧은 URL alias(`/s/{alias}`), 날짜 가독성, alias 검색을 추가한다.

**Architecture:** 기존 v1(서버리스: CloudFront+Cognito+HTTP API+Lambda+DynamoDB+S3) 위에 최소 변경으로 얹는다. 그룹은 같은 `SlideDecks` 테이블에 `GROUP#{groupId}` 메타 아이템으로 저장하고, 덱에 `group`/`alias` 필드를 추가한다. alias 유일성·리졸브는 sparse GSI `byAlias`로 처리한다.

**Tech Stack:** Python 3.12 Lambda, aws-cdk-lib(Python) 2.241, React+Vite+TS, boto3/moto, pytest, vitest.

## Global Constraints

- AWS 계정 `123456789012`, 프로파일 `profile2`, 리전 `us-east-1`.
- 덱 1개 = 최대 1개 그룹. 계층 그룹 없음. 서버측 검색 API 없음(클라이언트 필터).
- alias는 전역 유일, 예약어 금지: `api, slides, thumbnails, s, assets, web`.
- alias/group 접근은 로그인 사용자 전제(기존 Cognito JWT 흐름 재사용).
- 기존 v1 덱(신규 필드 없음)도 정상 동작해야 한다: `type` 부재→"deck", `group`/`alias` 부재→`null`.
- 슬라이드 HTML 원본 미변경(날짜는 뷰어 표시 계층에서만).
- 코드/문서에 이모지 금지. git 커밋에 AI attribution 금지.
- DDB 키: 덱 PK `deckId`; 그룹 메타 PK `GROUP#{groupId}`. GSI `byAlias`(PK `alias`, sparse), 기존 `byUpdatedAt`(PK `status`, SK `updatedAt`) 유지.

---

## File Structure

```
shared/deck_model.py            # + group/alias 헬퍼, 예약어, 그룹 메타 팩토리
lambdas/api/ddb.py              # + query_by_alias, list_groups, delete(그룹 키 호환)
lambdas/api/groups.py           # NEW: 그룹 슬러그/검증 순수 헬퍼 (또는 slug 재사용)
lambdas/api/handler.py          # + groups/alias/group/resolve 라우트, decks type 필터
infra/slidecast/slidecast_stack.py  # + byAlias GSI, 신규 명시 라우트
viewer/src/types.ts             # + group/alias 필드, Group 타입
viewer/src/api.ts               # + group/alias/resolve 클라이언트 메서드
viewer/src/format.ts            # NEW: formatDate 헬퍼
viewer/src/components/GroupSidebar.tsx  # NEW
viewer/src/components/DeckCard.tsx      # + 그룹이동/alias편집 액션, formatDate
viewer/src/components/VersionMenu.tsx   # formatDate 적용
viewer/src/components/Gallery.tsx       # 그룹 필터+검색(alias) 결합, 사이드바 통합
viewer/src/App.tsx              # + /s/{alias} 라우트 감지
skill/slidecast-append/slidecast_append.py  # + --group/--alias/--new-group/--del-group
tests/**                        # 각 태스크 대응 테스트
```

---

## Task 1: 데이터 모델 — 그룹 메타 + alias 검증 헬퍼

**Files:**
- Modify: `shared/deck_model.py`
- Test: `tests/shared/test_deck_model_v2.py`

**Interfaces:**
- Consumes: 기존 deck_model
- Produces:
  - `RESERVED_ALIASES = frozenset({"api","slides","thumbnails","s","assets","web"})`
  - `group_pk(group_id: str) -> str` → `f"GROUP#{group_id}"`
  - `new_group_item(group_id: str, name: str, now_iso: str) -> dict` → `{deckId: group_pk, type:"group", groupId, name, status:"active", createdAt: now_iso}`
  - `is_valid_alias(alias: str) -> bool` → 비어있지 않고 예약어가 아니면 True (슬러그 형식은 호출측에서 slugify 후 검사)
  - `set_group(item: dict, group_id, now_iso) -> dict` → 새 dict, `group=group_id`(None 허용), `updatedAt` 갱신
  - `set_alias(item: dict, alias, now_iso) -> dict` → 새 dict, `alias=alias`(None 허용), `updatedAt` 갱신
  - `deck_type(item: dict) -> str` → `item.get("type") or "deck"`
- `new_deck_item`에 `type:"deck", group:None, alias:None` 기본 포함하도록 수정(기존 호출 무영향; 기존 필드 유지).

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_deck_model_v2.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    RESERVED_ALIASES, group_pk, new_group_item, is_valid_alias,
    set_group, set_alias, deck_type, new_deck_item,
)

def test_group_pk_and_item():
    g = new_group_item("marketing", "Marketing", "2026-07-21T00:00:00Z")
    assert g["deckId"] == "GROUP#marketing"
    assert g["type"] == "group"
    assert g["groupId"] == "marketing"
    assert g["name"] == "Marketing"
    assert g["status"] == "active"

def test_is_valid_alias():
    assert is_valid_alias("roadmap") is True
    assert is_valid_alias("api") is False       # reserved
    assert is_valid_alias("") is False

def test_set_group_immutable():
    d = new_deck_item("x", "X", [], "t0")
    g = set_group(d, "marketing", "t1")
    assert d.get("group") is None
    assert g["group"] == "marketing"
    assert g["updatedAt"] == "t1"
    assert set_group(g, None, "t2")["group"] is None

def test_set_alias_immutable():
    d = new_deck_item("x", "X", [], "t0")
    a = set_alias(d, "road", "t1")
    assert d.get("alias") is None
    assert a["alias"] == "road"

def test_new_deck_item_has_v2_defaults():
    d = new_deck_item("x", "X", [], "t0")
    assert d["type"] == "deck"
    assert d["group"] is None
    assert d["alias"] is None

def test_deck_type_defaults_to_deck():
    assert deck_type({"deckId": "x"}) == "deck"       # legacy item, no type
    assert deck_type({"type": "group"}) == "group"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model_v2.py -v`
Expected: FAIL — ImportError on new names.

- [ ] **Step 3: Write minimal implementation**

Append to `shared/deck_model.py`:

```python
RESERVED_ALIASES = frozenset({"api", "slides", "thumbnails", "s", "assets", "web"})


def group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def new_group_item(group_id: str, name: str, now_iso: str) -> dict:
    return {
        "deckId": group_pk(group_id),
        "type": "group",
        "groupId": group_id,
        "name": name,
        "status": "active",
        "createdAt": now_iso,
    }


def is_valid_alias(alias: str) -> bool:
    return bool(alias) and alias not in RESERVED_ALIASES


def deck_type(item: dict) -> str:
    return item.get("type") or "deck"


def set_group(item: dict, group_id, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["group"] = group_id
    new_item["updatedAt"] = now_iso
    return new_item


def set_alias(item: dict, alias, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["alias"] = alias
    new_item["updatedAt"] = now_iso
    return new_item
```

And modify `new_deck_item` to include v2 defaults (keep existing fields):

```python
def new_deck_item(deck_id: str, title: str, tags: list, now_iso: str) -> dict:
    return {
        "deckId": deck_id,
        "type": "deck",
        "title": title,
        "tags": list(tags),
        "group": None,
        "alias": None,
        "status": "active",
        "currentVersion": 0,
        "versions": [],
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model_v2.py tests/shared/test_deck_model.py -v`
Expected: PASS (new file + existing model tests still green).

- [ ] **Step 5: Commit**

```bash
git add shared/deck_model.py tests/shared/test_deck_model_v2.py
git commit -m "feat: add group meta and alias helpers to deck model"
```

---

## Task 2: DDB 리포지토리 — alias 조회 + 그룹 목록

**Files:**
- Modify: `lambdas/api/ddb.py`
- Test: `tests/lambdas/test_ddb_v2.py`

**Interfaces:**
- Consumes: DeckRepo
- Produces (new methods on DeckRepo):
  - `query_by_alias(alias: str) -> Optional[dict]` — GSI `byAlias` 조회, 첫 아이템 또는 None
  - `list_groups() -> list[dict]` — `type == "group"` 아이템 목록. 구현: `byUpdatedAt`은 status로만 쿼리하므로, 그룹은 `scan` + `FilterExpression type == "group"` (개인 규모, 그룹 소수 → scan 허용). 또는 status="active" 쿼리 후 type 필터. 여기선 scan+filter 사용.
- 기존 `get`/`delete`는 PK만 쓰므로 `GROUP#...` 키에도 그대로 동작(그룹 메타 get/delete에 재사용).

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_ddb_v2.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, pytest
from moto import mock_aws
from deck_model import new_deck_item, add_version, set_alias, new_group_item
from ddb import DeckRepo

TABLE = "SlideDecks"

def _make(res):
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
            {"AttributeName": "alias", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "byUpdatedAt",
             "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"},
                           {"AttributeName": "updatedAt", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "byAlias",
             "KeySchema": [{"AttributeName": "alias", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

@mock_aws
def test_query_by_alias():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make(res)
    repo = DeckRepo(TABLE, res)
    d = set_alias(add_version(new_deck_item("roadmap", "R", [], "t"), "k", 1, "t1"), "road", "t2")
    repo.put(d)
    assert repo.query_by_alias("road")["deckId"] == "roadmap"
    assert repo.query_by_alias("missing") is None

@mock_aws
def test_list_groups():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make(res)
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    repo.put(new_group_item("mkt", "Marketing", "t"))
    repo.put(new_group_item("eng", "Eng", "t"))
    ids = sorted(g["groupId"] for g in repo.list_groups())
    assert ids == ["eng", "mkt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_ddb_v2.py -v`
Expected: FAIL — AttributeError query_by_alias / list_groups.

- [ ] **Step 3: Write minimal implementation**

Append to `lambdas/api/ddb.py` (add `from boto3.dynamodb.conditions import Attr` alongside existing `Key` import):

```python
    def query_by_alias(self, alias: str):
        resp = self._table.query(
            IndexName="byAlias",
            KeyConditionExpression=Key("alias").eq(alias),
        )
        items = resp.get("Items", [])
        return items[0] if items else None

    def list_groups(self) -> list:
        resp = self._table.scan(FilterExpression=Attr("type").eq("group"))
        return resp.get("Items", [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_ddb_v2.py tests/lambdas/test_ddb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/ddb.py tests/lambdas/test_ddb_v2.py
git commit -m "feat: add alias GSI query and group listing to repo"
```

---

## Task 3: API 핸들러 — 그룹 CRUD, group/alias 배정, resolve

**Files:**
- Modify: `lambdas/api/handler.py`
- Test: `tests/lambdas/test_api_handler_v2.py`

**Interfaces:**
- Consumes: DeckRepo(+v2 methods), deck_model(+v2 helpers), slugify
- Produces (new routes in `handler`):
  - `GET /api/groups` → `{groups: repo.list_groups()}`
  - `POST /api/groups {name}` → groupId=slugify(name); 이미 존재(get(group_pk)) 시 409; else put new_group_item; `{groupId, name}`
  - `DELETE /api/groups/{groupId}` → byUpdatedAt로 active+archived 덱 조회, group==groupId인 덱을 set_group(None) 후 put; 그룹 메타 delete; `{ok:true}`
  - `PUT /api/decks/{id}/group {groupId|null}` → groupId 지정 시 그룹 존재 검증(없으면 400); set_group; `{ok:true}`
  - `PUT /api/decks/{id}/alias {alias|null}` → alias 지정 시 slugify→is_valid_alias(예약어 400)→query_by_alias 중복(다른 deckId면 409); set_alias; null이면 해제; `{ok:true}`
  - `GET /api/resolve/{alias}` → query_by_alias; 없으면 404; 있으면 덱 + versions[].url 부여(기존 GET/{id} 로직 재사용)
  - `GET /api/decks`에 `?group=` 필터 + `deck_type=="deck"`만 반환(그룹 메타 제외)
- 라우트 매칭 순서 주의: `/groups`, `/resolve` 프리픽스를 기존 `/decks` 분기보다 먼저; `/group`·`/alias` suffix를 generic PUT보다 먼저.

- [ ] **Step 1: Write the failing test** (moto DDB+S3; 표준 setup은 기존 test_api_handler.py 패턴 재사용, byAlias GSI 포함)

```python
# tests/lambdas/test_api_handler_v2.py
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, importlib, pytest
from moto import mock_aws

TABLE, BUCKET = "SlideDecks", "slidecast-test"

def _setup(res, s3):
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
            {"AttributeName": "alias", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "byUpdatedAt",
             "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"},
                           {"AttributeName": "updatedAt", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "byAlias",
             "KeySchema": [{"AttributeName": "alias", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    s3.create_bucket(Bucket=BUCKET)

def _evt(method, path, body=None, pp=None, qs=None):
    return {"requestContext": {"http": {"method": method, "path": path}},
            "rawPath": path, "pathParameters": pp or {},
            "queryStringParameters": qs or {},
            "body": json.dumps(body) if body is not None else None}

@mock_aws
def test_group_crud_and_assignment(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    # create group
    r = h.handler(_evt("POST", "/api/groups", {"name": "Marketing"}))
    assert r["statusCode"] == 200 and json.loads(r["body"])["groupId"] == "marketing"
    # assign deck
    h.handler(_evt("PUT", "/api/decks/a/group", {"groupId": "marketing"}, pp={"id": "a"}))
    assert repo.get("a")["group"] == "marketing"
    # list decks filtered by group excludes group meta items
    r = h.handler(_evt("GET", "/api/decks", qs={"group": "marketing"}))
    ids = [d["deckId"] for d in json.loads(r["body"])["decks"]]
    assert ids == ["a"]
    # delete group -> deck unassigned
    h.handler(_evt("DELETE", "/api/groups/marketing", pp={"groupId": "marketing"}))
    assert repo.get("a")["group"] is None
    assert repo.get("GROUP#marketing") is None

@mock_aws
def test_alias_set_conflict_reserved_and_resolve(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    repo.put(add_version(new_deck_item("b", "B", [], "t"), "k", 1, "t1"))
    # reserved -> 400
    assert h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": "api"}, pp={"id": "a"}))["statusCode"] == 400
    # set ok
    assert h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": "Road Map"}, pp={"id": "a"}))["statusCode"] == 200
    assert repo.get("a")["alias"] == "road-map"
    # conflict on b -> 409
    assert h.handler(_evt("PUT", "/api/decks/b/alias", {"alias": "road-map"}, pp={"id": "b"}))["statusCode"] == 409
    # resolve
    r = h.handler(_evt("GET", "/api/resolve/road-map", pp={"alias": "road-map"}))
    assert r["statusCode"] == 200 and json.loads(r["body"])["deckId"] == "a"
    assert h.handler(_evt("GET", "/api/resolve/none", pp={"alias": "none"}))["statusCode"] == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler_v2.py -v`
Expected: FAIL (routes return 404 no route).

- [ ] **Step 3: Write minimal implementation**

Add to `handler.py`. Place group/resolve blocks BEFORE the existing `/api/decks` blocks. Use `import deck_model as dm`, `from slug import slugify` (already imported). Extract group id from pathParameters or rawPath. Reference implementation:

```python
    # --- groups ---
    if method == "GET" and path == "/api/groups":
        return _resp(200, {"groups": repo.list_groups()})

    if method == "POST" and path == "/api/groups":
        name = _body(event)["name"]
        gid = slugify(name)
        if repo.get(dm.group_pk(gid)) is not None:
            return _resp(409, {"error": "group exists"})
        repo.put(dm.new_group_item(gid, name, now_iso()))
        return _resp(200, {"groupId": gid, "name": name})

    if method == "DELETE" and "/api/groups/" in path:
        gid = (event.get("pathParameters") or {}).get("groupId") or path.rsplit("/", 1)[-1]
        for status in ("active", "archived"):
            for d in repo.list_by_status(status):
                if d.get("group") == gid:
                    repo.put(dm.set_group(d, None, now_iso()))
        repo.delete(dm.group_pk(gid))
        return _resp(200, {"ok": True})

    # --- resolve ---
    if method == "GET" and "/api/resolve/" in path:
        alias = (event.get("pathParameters") or {}).get("alias") or path.rsplit("/", 1)[-1]
        item = repo.query_by_alias(alias)
        if not item:
            return _resp(404, {"error": "not found"})
        for v in item["versions"]:
            v["url"] = "/" + dm.slide_key(item["deckId"], v["n"])
        return _resp(200, item)

    # --- deck group/alias assignment (before generic PUT) ---
    if method == "PUT" and path.endswith("/group"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        gid = _body(event).get("groupId")
        if gid is not None and repo.get(dm.group_pk(gid)) is None:
            return _resp(400, {"error": "group does not exist"})
        repo.put(dm.set_group(item, gid, now_iso()))
        return _resp(200, {"ok": True})

    if method == "PUT" and path.endswith("/alias"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        raw = _body(event).get("alias")
        if raw is None:
            repo.put(dm.set_alias(item, None, now_iso()))
            return _resp(200, {"ok": True})
        alias = slugify(raw)
        if not dm.is_valid_alias(alias):
            return _resp(400, {"error": "invalid or reserved alias"})
        existing = repo.query_by_alias(alias)
        if existing and existing["deckId"] != item["deckId"]:
            return _resp(409, {"error": "alias taken"})
        repo.put(dm.set_alias(item, alias, now_iso()))
        return _resp(200, {"ok": True})
```

And modify the existing `GET /api/decks` block to filter by group + deck type:

```python
    if method == "GET" and path == "/api/decks":
        status = qs.get("status") or "active"
        group = qs.get("group")
        decks = [d for d in repo.list_by_status(status) if dm.deck_type(d) == "deck"]
        if group is not None:
            key = None if group == "__unassigned__" else group
            decks = [d for d in decks if d.get("group") == key]
        return _resp(200, {"decks": decks})
```

Note: group meta items have `status="active"` so they appear in `list_by_status("active")` — the `deck_type=="deck"` filter is REQUIRED to exclude them. Keep it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler_v2.py tests/lambdas/test_api_handler.py -v`
Expected: PASS (new + existing handler tests green).

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/handler.py tests/lambdas/test_api_handler_v2.py
git commit -m "feat: add groups, alias, and resolve API routes"
```

---

## Task 4: CDK — byAlias GSI + 신규 라우트

**Files:**
- Modify: `infra/slidecast/slidecast_stack.py`
- Test: `tests/infra/test_synth_v2.py`

**Interfaces:**
- Produces: DDB에 `alias` attribute + GSI `byAlias`(PK alias); HTTP API에 명시 라우트 추가: `ANY /api/groups`, `ANY /api/groups/{groupId}`, `ANY /api/decks/{id}/group`, `ANY /api/decks/{id}/alias`, `ANY /api/resolve/{alias}`. 모두 같은 api_fn 통합, 기존 JWT authorizer 하위.

- [ ] **Step 1: Write the failing test**

```python
# tests/infra/test_synth_v2.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template, Match
from slidecast.slidecast_stack import SlidecastStack

def _t():
    app = App()
    return Template.from_stack(SlidecastStack(app, "T", env={"account": "123456789012", "region": "us-east-1"}))

def test_byalias_gsi():
    _t().has_resource_properties("AWS::DynamoDB::Table", {
        "GlobalSecondaryIndexes": Match.array_with([
            Match.object_like({"IndexName": "byAlias"}),
        ]),
    })

def test_alias_route_exists():
    routes = _t().find_resources("AWS::ApiGatewayV2::Route")
    keys = [r["Properties"]["RouteKey"] for r in routes.values()]
    assert any("/api/resolve/{alias}" in k for k in keys)
    assert any("/api/groups" in k for k in keys)
    assert any("/group" in k for k in keys)
```

- [ ] **Step 2: Run test to verify it fails**

Run (build assets first, as in v1): `cd /Workshop/html-viewer && mkdir -p shared_layer/python && cp shared/deck_model.py shared_layer/python/ && cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py && cp shared/deck_model.py lambdas/thumbnail/deck_model.py && python3 -m pytest tests/infra/test_synth_v2.py -v`
Expected: FAIL — byAlias GSI/routes absent.

- [ ] **Step 3: Write minimal implementation**

In `slidecast_stack.py`, after the existing `add_global_secondary_index(byUpdatedAt...)`:

```python
        table.add_global_secondary_index(
            index_name="byAlias",
            partition_key=ddb.Attribute(name="alias", type=ddb.AttributeType.STRING),
        )
```

(DynamoDB GSI partition key attribute must be declared implicitly via the index; CDK infers the AttributeDefinition. Sparse because only items with `alias` set are indexed.)

Add explicit routes after the existing decks routes:

```python
        for rk in [
            "/api/groups", "/api/groups/{groupId}",
            "/api/decks/{id}/group", "/api/decks/{id}/alias",
            "/api/resolve/{alias}",
        ]:
            http_api.add_routes(
                path=rk, methods=[apigw.HttpMethod.ANY],
                integration=integrations.HttpLambdaIntegration(
                    "Int" + rk.replace("/", "_").replace("{", "").replace("}", ""), api_fn),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/infra/test_synth_v2.py tests/infra/test_synth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/slidecast/slidecast_stack.py tests/infra/test_synth_v2.py
git commit -m "feat: add byAlias GSI and group/alias/resolve routes to stack"
```

---

## Task 5: 뷰어 타입 + API 클라이언트 + 날짜 헬퍼

**Files:**
- Modify: `viewer/src/types.ts`, `viewer/src/api.ts`
- Create: `viewer/src/format.ts`
- Test: `viewer/src/format.test.ts`, extend `viewer/src/api.test.ts`

**Interfaces:**
- `types.ts`: `Deck`에 `group: string | null`, `alias: string | null` 추가. `interface Group { groupId: string; name: string }`.
- `format.ts`: `formatDate(iso: string): string` → `YYYY-MM-DD` (빈/잘못된 입력은 원문 반환).
- `api.ts` 신규 메서드: `listGroups(): Promise<Group[]>`, `createGroup(name)`, `deleteGroup(groupId)`, `setGroup(id, groupId|null)`, `setAlias(id, alias|null)`, `resolve(alias): Promise<Deck>`. `listDecks(status, group?)`에 group 쿼리 추가.

- [ ] **Step 1: Write the failing test**

```ts
// viewer/src/format.test.ts
import { describe, it, expect } from "vitest";
import { formatDate } from "./format";
describe("formatDate", () => {
  it("formats ISO to YYYY-MM-DD", () => {
    expect(formatDate("2026-07-21T09:30:00Z")).toBe("2026-07-21");
  });
  it("returns input on empty/invalid", () => {
    expect(formatDate("")).toBe("");
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});
```

Add to `viewer/src/api.test.ts` a case asserting `listGroups()` attaches bearer and parses `{groups:[...]}`, and `listDecks("active","mkt")` hits `?status=active&group=mkt`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/format.test.ts`
Expected: FAIL — cannot find ./format.

- [ ] **Step 3: Write minimal implementation**

```ts
// viewer/src/format.ts
export function formatDate(iso: string): string {
  if (!iso) return iso;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
```

types.ts additions:
```ts
export interface Group { groupId: string; name: string; }
// in Deck: group: string | null; alias: string | null;
```

api.ts additions (inside createApi return object; `auth()` already attaches bearer):
```ts
    async listGroups(): Promise<Group[]> {
      return (await j(await fetch(`${baseUrl}/api/groups`, { headers: auth() }))).groups;
    },
    async createGroup(name: string) {
      return j(await fetch(`${baseUrl}/api/groups`, { method: "POST", headers: auth(), body: JSON.stringify({ name }) }));
    },
    async deleteGroup(groupId: string) {
      return j(await fetch(`${baseUrl}/api/groups/${groupId}`, { method: "DELETE", headers: auth() }));
    },
    async setGroup(id: string, groupId: string | null) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/group`, { method: "PUT", headers: auth(), body: JSON.stringify({ groupId }) }));
    },
    async setAlias(id: string, alias: string | null) {
      return j(await fetch(`${baseUrl}/api/decks/${id}/alias`, { method: "PUT", headers: auth(), body: JSON.stringify({ alias }) }));
    },
    async resolve(alias: string): Promise<Deck> {
      return j(await fetch(`${baseUrl}/api/resolve/${alias}`, { headers: auth() }));
    },
```
And update `listDecks`:
```ts
    async listDecks(status = "active", group?: string): Promise<Deck[]> {
      const q = new URLSearchParams({ status });
      if (group) q.set("group", group);
      const r = await fetch(`${baseUrl}/api/decks?${q}`, { headers: auth() });
      return (await j(r)).decks;
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/format.test.ts src/api.test.ts && npx tsc --noEmit`
Expected: PASS + tsc clean.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/types.ts viewer/src/api.ts viewer/src/format.ts viewer/src/format.test.ts viewer/src/api.test.ts
git commit -m "feat: add group/alias API client methods and date formatter"
```

---

## Task 6: 뷰어 UI — 그룹 사이드바 + 카드 액션 + alias 라우트 + 검색

**Files:**
- Create: `viewer/src/components/GroupSidebar.tsx`
- Modify: `viewer/src/components/Gallery.tsx`, `DeckCard.tsx`, `VersionMenu.tsx`, `viewer/src/App.tsx`
- Test: extend `viewer/src/components/Gallery.test.tsx`

**Interfaces:**
- `GroupSidebar({ groups, selected, onSelect, onCreate, onDelete })` — 전체/미분류/각 그룹 목록 + 추가(+)/삭제.
- `DeckCard` props 추가: `groups: Group[]`, `onMoveGroup(groupId|null)`, `onSetAlias(alias|null)`. formatDate 적용, alias 배지 표시.
- `VersionMenu`: 날짜 formatDate 적용.
- `Gallery`: 사이드바 통합, `selectedGroup` state, `listDecks(status, selectedGroup)` 로드, 검색 필터에 alias 포함(title|tags|alias). 그룹 생성/삭제/이동/alias 편집 핸들러.
- `App.tsx`: `window.location.pathname`이 `/s/{alias}`면 로그인 후 `api.resolve(alias)` → 현재 버전 Player 렌더.

- [ ] **Step 1: Write the failing test**

Add to `Gallery.test.tsx`: fakeApi with `listGroups` returning `[{groupId:"mkt",name:"Marketing"}]`, `listDecks` returning a deck with `alias:"road"`. Assert group name "Marketing" renders in sidebar, and a query "road" (alias) keeps the deck.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/components/Gallery.test.tsx`
Expected: FAIL (GroupSidebar/alias-search not present).

- [ ] **Step 3: Write minimal implementation**

Implement `GroupSidebar.tsx` (dark cinematic, matches theme tokens). Extend `Gallery.tsx`:
- Load groups on mount (`api.listGroups()`), `selectedGroup` state (null=전체, `"__unassigned__"`=미분류).
- `reload` passes `selectedGroup` to `listDecks`.
- search filter: `d.title|tags|alias` includes query (reuse existing pattern, add `(d.alias ?? "")`).
- Handlers: `createGroup` (prompt/inline), `deleteGroup` (confirm modal "덱은 미분류로 이동"), `moveGroup` (card dropdown → api.setGroup → reload), `setAlias` (card inline input → api.setAlias, catch 409/400 → inline error).
DeckCard: render `formatDate(deck.updatedAt)`, alias badge if present, group-move dropdown, alias edit control.
VersionMenu: `formatDate(v.createdAt)`.
App.tsx: detect `/s/` path:
```tsx
const aliasMatch = window.location.pathname.match(/^\/s\/(.+)$/);
// after auth ready & authed: if aliasMatch, api.resolve(aliasMatch[1]) then render Player with /slides/{deckId}/v{currentVersion}/index.html; on 404 show a "not found" message with a link back to "/".
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all pass, tsc clean, build ok.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/components/ viewer/src/App.tsx
git commit -m "feat: add group sidebar, card group/alias actions, /s/alias route, readable dates"
```

---

## Task 7: 로컬 스킬 — group/alias 옵션 + 그룹 서브커맨드

**Files:**
- Modify: `skill/slidecast-append/slidecast_append.py`, `skill/slidecast-append/SKILL.md`
- Test: `tests/skill/test_slidecast_append_v2.py`

**Interfaces:**
- `append(...)`에 `group=None, alias=None` 파라미터: 업로드 후 `group` 지정 시 그룹 없으면 자동 생성(`new_group_item`) 후 `set_group`; `alias` 지정 시 slugify+is_valid_alias+중복검사(query_by_alias) 후 `set_alias`(중복 시 명확한 에러).
- `new_group(name, table, dynamodb=None)`, `del_group(group_id, table, dynamodb=None)` (API DELETE와 동일 시맨틱: 소속 덱 미분류 이동 후 그룹 메타 삭제).
- CLI: `--group <name>`, `--alias <slug>`, `--new-group <name>`, `--del-group <groupId>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/skill/test_slidecast_append_v2.py  (moto, stubbed capture; setup with byAlias GSI)
# - append(file, group="Marketing", alias="road") -> deck.group=="marketing", deck.alias=="road", GROUP#marketing exists
# - append second file with alias="road" -> raises/SystemExit (conflict)
# - new_group + del_group round trip; del_group reassigns member deck to None
```

(Write concrete assertions mirroring Task 3's semantics; reuse the v2 GSI table setup helper.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append_v2.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Extend `slidecast_append.py`: after the existing `append` upserts the deck item, apply group/alias via deck_model helpers + repo (auto-create group when missing; alias conflict raises SystemExit with a clear message). Add `new_group`/`del_group` functions and CLI args mirroring Task 3 semantics. Update SKILL.md usage (no emojis).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append_v2.py tests/skill/test_slidecast_append.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skill/ tests/skill/test_slidecast_append_v2.py
git commit -m "feat: add group/alias options and group subcommands to local skill"
```

---

## Task 8: 통합 검증 + 배포 + 리뷰

**Files:** none (verify/deploy task)

- [ ] **Step 1: 전체 테스트**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/ -q && (cd viewer && npx vitest run && npx tsc --noEmit && npm run build)`
Expected: 모든 Python + TS 테스트 통과, 빌드 성공.

- [ ] **Step 2: 최종 리뷰 (adversarial)**

전체 v2 diff에 대해 whole-branch 리뷰 (correctness/보안/통합). codex 리뷰 게이트 시도하되, **codex가 비정상 실패하거나 과도하게 지연되면 skip**(사용자 지시) — 대신 opus 서브에이전트 리뷰로 대체. CRITICAL/Important 발견 시 수정 후 재검증.
특히 확인: GET /api/decks가 그룹 메타를 절대 덱으로 반환 안 함; alias 예약어/중복 거부; 그룹 삭제 시 덱 보존; /s/{alias} 미인증/404 처리; byAlias GSI sparse 동작; 기존 v1 덱(신규 필드 없음) 정상.

- [ ] **Step 3: 배포**

```bash
cd /Workshop/html-viewer && ./scripts/deploy.sh && ./scripts/deploy-viewer.sh
```
GSI 추가는 온라인 인덱스 빌드(무중단). Docker 필요(썸네일 이미지). 배포 후 스모크:
- `GET /api/groups` → 401(미인증) 확인 (authorizer 동작)
- SPA 200, 기존 덱 여전히 표시

- [ ] **Step 4: README 갱신**

그룹/alias/`/s/` 사용법, `--group`/`--alias`/`--new-group`/`--del-group` 스킬 옵션 추가.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document groups, alias, and readable dates"
```

---

## Self-Review (계획 검토)

- **Spec coverage:** 그룹 CRUD(Task 3), 덱 group/alias 배정(Task 3), alias GSI/리졸브(Task 2,3,4), `/s/{alias}` 라우트(Task 6), 날짜 가독성(Task 5,6), 검색 alias 포함(Task 6), 로컬 스킬 group/alias(Task 7), CDK GSI+라우트(Task 4) — 스펙 전 항목 커버.
- **Placeholder scan:** Task 1-5는 완전한 코드 포함. Task 6·7은 기존 컴포넌트/스킬 확장이라 변경 지점과 시그니처를 명시하고 핵심 코드를 제공(대형 UI 파일 전체 재기술은 회피, 변경 인터페이스는 명확). Task 7 테스트는 시맨틱을 서술로 명시 — 구현자가 Task 3 패턴을 그대로 따르도록 지시.
- **Type consistency:** `set_group`/`set_alias`/`new_group_item`/`group_pk`/`is_valid_alias`/`deck_type`가 Task 1 정의와 Task 3·7 사용처 일치. `query_by_alias`/`list_groups`가 Task 2 정의와 Task 3 사용처 일치. api.ts 메서드(listGroups/createGroup/deleteGroup/setGroup/setAlias/resolve)가 Task 5 정의와 Task 6 사용처 일치.
- **주의:** GET /api/decks의 `deck_type=="deck"` 필터는 그룹 메타가 status="active"로 byUpdatedAt에 섞이므로 필수 — Task 3에 명시. byAlias는 sparse(alias 없는 아이템 미포함)라 그룹 메타/미설정 덱은 GSI에 안 나타남.
