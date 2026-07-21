# Slidecast v3 (Public Share / Download) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 배포된 Slidecast에 덱별 public 공유(`/p/{token}`, 무인증 재생)와 로그인 사용자용 다운로드(원본 .html + 사전 생성 PDF)를 추가한다.

**Architecture:** 기존 v2(서버리스) 위에 최소 증분. public 토큰은 v2-9의 alias 원자 예약 패턴을 그대로 재사용(`PUBLIC#{token}` 조건부 예약). 공개 시 현재 버전 HTML을 `public/{token}/index.html`로 복사. PDF는 기존 Thumbnail 컨테이너 Lambda(Chromium)가 썸네일과 같은 S3 이벤트에서 함께 생성. 무인증 노출은 API 라우트 `GET /api/public/{token}` 하나 + S3 `public/*` 프리픽스로 한정.

**Tech Stack:** Python 3.12 Lambda, aws-cdk-lib(Python) 2.241, React+Vite+TS, boto3/moto, pytest, vitest, Chromium(Playwright) 컨테이너.

## Global Constraints

- AWS 계정 `123456789012`, 프로파일 `profile2`, 리전 `us-east-1`.
- 무인증 API 라우트는 `GET /api/public/{token}` 하나만(HttpNoneAuthorizer). 나머지 `/api/*`는 전부 기존 JWT authorizer 유지.
- 무인증 S3 노출은 `public/*` 프리픽스로 한정. `slides/`·`thumbnails/`·`pdfs/`는 프라이빗(OAC), presigned로만 다운로드.
- 다운로드는 로그인 사용자 전용. 공개 공유 페이지(`/p/{token}`)는 보기 전용(다운로드 없음).
- public 토큰: `secrets.token_urlsafe` 추측 불가; `PUBLIC#{token}` 조건부 예약(attribute_not_exists), 충돌 시 재생성; OFF/재공개 시 새 토큰.
- 공개 스냅샷은 명시적 재발행으로만 갱신(자동 아님).
- INVARIANT(v2-2): put()이 None 값 키 제거(sparse). group/alias/publicToken/pdfKey는 항상 `.get()`/`?? null`로 읽는다.
- 공개 iframe은 sandbox `allow-scripts`(same-origin 제외) 유지.
- PDF/공개 복사본 등 파일은 presigned URL(짧은 만료, Content-Disposition attachment)로만 제공.
- 코드/문서 이모지 금지. git 커밋 AI attribution 금지.
- 키: `public/{token}/index.html`, `pdfs/{deckId}/v{n}.pdf`. 리졸브 아이템 PK `PUBLIC#{token}`(status/updatedAt/alias 속성 미설정 → GSI 미노출, PK 직접 조회).

---

## File Structure

```
shared/deck_model.py           # + public_pk, new_public_reservation, set_public_token, set_version_pdf
lambdas/api/ddb.py             # + reserve_public/release_public (reserve_alias 패턴 복제), query_by_public 불필요(get(PK))
lambdas/api/handler.py         # + share/republish/unshare, GET /api/public/{token}(무인증), download presign
lambdas/thumbnail/handler.py   # + PDF 생성(capture_pdf) + set_version_pdf
lambdas/thumbnail/Dockerfile   # (변경 없음 — Chromium 이미 존재)
infra/slidecast/slidecast_stack.py  # + share/download 라우트(JWT), /api/public/{token}(NoneAuthorizer)
viewer/src/types.ts            # + publicToken, Version.pdfKey
viewer/src/api.ts              # + share/unshare/republish/getPublic/downloadUrl
viewer/src/components/ShareModal.tsx   # NEW
viewer/src/components/PublicPage.tsx   # NEW (/p/{token})
viewer/src/components/DeckCard.tsx     # + 공유 버튼, 다운로드(html/pdf), 공개 배지
viewer/src/components/VersionMenu.tsx  # + 버전별 다운로드
viewer/src/App.tsx             # + /p/{token} 라우트(무인증)
skill/slidecast-append/slidecast_append.py  # + --share/--unshare, hard delete public/pdf 정리
tests/**
```

---

## Task 1: deck_model — public 예약 + pdfKey 헬퍼

**Files:**
- Modify: `shared/deck_model.py`
- Test: `tests/shared/test_deck_model_v3.py`

**Interfaces:**
- Produces:
  - `public_pk(token) -> str` → `f"PUBLIC#{token}"`
  - `new_public_reservation(token, deck_id, public_version, now_iso) -> dict` → `{deckId: public_pk(token), type:"public", ownerDeckId: deck_id, publicVersion: public_version, createdAt: now_iso}` (NO status/updatedAt/alias attrs — stays out of GSIs)
  - `set_public_token(item, token, now_iso) -> dict` — immutable, sets `publicToken`(None 허용), updatedAt
  - `set_version_pdf(item, n, pdf_key, now_iso) -> dict` — immutable; find version n, set its `pdfKey`; if n absent, no-op returns copy (defensive). updatedAt 갱신.
- `new_deck_item`: add `publicToken: None`. (versions[] items gain pdfKey lazily via set_version_pdf; no schema change needed since add_pending_version already builds version dicts — add `pdfKey: None` there too.)

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_deck_model_v3.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from deck_model import (
    public_pk, new_public_reservation, set_public_token, set_version_pdf,
    new_deck_item, add_pending_version,
)

def test_public_pk_and_reservation():
    r = new_public_reservation("tok123", "roadmap", 2, "2026-07-21T00:00:00Z")
    assert r["deckId"] == "PUBLIC#tok123"
    assert r["type"] == "public"
    assert r["ownerDeckId"] == "roadmap"
    assert r["publicVersion"] == 2
    assert "status" not in r and "alias" not in r  # stays out of GSIs

def test_set_public_token_immutable():
    d = new_deck_item("x", "X", [], "t0")
    on = set_public_token(d, "tok", "t1")
    assert d.get("publicToken") is None
    assert on["publicToken"] == "tok"
    assert set_public_token(on, None, "t2")["publicToken"] is None

def test_new_deck_item_has_public_default():
    assert new_deck_item("x", "X", [], "t0")["publicToken"] is None

def test_set_version_pdf():
    d = new_deck_item("x", "X", [], "t0")
    d = add_pending_version(d, 1, "t1")
    d2 = set_version_pdf(d, 1, "pdfs/x/v1.pdf", "t2")
    v = next(v for v in d2["versions"] if v["n"] == 1)
    assert v["pdfKey"] == "pdfs/x/v1.pdf"
    # original untouched
    assert next(v for v in d["versions"] if v["n"] == 1).get("pdfKey") is None

def test_set_version_pdf_absent_version_noop():
    d = new_deck_item("x", "X", [], "t0")
    d2 = set_version_pdf(d, 9, "pdfs/x/v9.pdf", "t2")
    assert d2["versions"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model_v3.py -v`
Expected: FAIL — ImportError on new names.

- [ ] **Step 3: Write minimal implementation**

Append to `shared/deck_model.py`:

```python
def public_pk(token: str) -> str:
    return f"PUBLIC#{token}"


def new_public_reservation(token: str, deck_id: str, public_version: int, now_iso: str) -> dict:
    # No status/updatedAt/alias -> excluded from byUpdatedAt and byAlias GSIs.
    # Looked up by primary key: get(public_pk(token)).
    return {
        "deckId": public_pk(token),
        "type": "public",
        "ownerDeckId": deck_id,
        "publicVersion": public_version,
        "createdAt": now_iso,
    }


def set_public_token(item: dict, token, now_iso: str) -> dict:
    new_item = deepcopy(item)
    new_item["publicToken"] = token
    new_item["updatedAt"] = now_iso
    return new_item


def set_version_pdf(item: dict, n: int, pdf_key: str, now_iso: str) -> dict:
    new_item = deepcopy(item)
    for v in new_item["versions"]:
        if v["n"] == n:
            v["pdfKey"] = pdf_key
            new_item["updatedAt"] = now_iso
            break
    return new_item
```

Modify `new_deck_item` to add `"publicToken": None,`. Modify `add_pending_version`'s version dict to include `"pdfKey": None,`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/shared/test_deck_model_v3.py tests/shared/test_deck_model.py tests/shared/test_deck_model_v2.py -v`
Expected: PASS (new + existing model tests).

- [ ] **Step 5: Commit**

```bash
git add shared/deck_model.py tests/shared/test_deck_model_v3.py
git commit -m "feat: add public token reservation and version pdf helpers to model"
```

---

## Task 2: DDB — public 토큰 원자 예약 (reserve_alias 패턴 복제)

**Files:**
- Modify: `lambdas/api/ddb.py`
- Test: `tests/lambdas/test_ddb_v3.py`

**Interfaces:**
- Produces (DeckRepo):
  - `reserve_public(token, deck_id, public_version, now_iso) -> bool` — conditional PutItem of `new_public_reservation` with `ConditionExpression=attribute_not_exists(deckId)`; True on success, False on ConditionalCheckFailedException; other ClientErrors propagate.
  - `release_public(token) -> None` — `delete(public_pk(token))` (idempotent).
- (Lookup uses existing `get(public_pk(token))`.)

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_ddb_v3.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, pytest
from moto import mock_aws
from ddb import DeckRepo
import deck_model as dm

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
def test_reserve_public_atomic():
    res = boto3.resource("dynamodb", region_name="us-east-1"); _make(res)
    repo = DeckRepo(TABLE, res)
    assert repo.reserve_public("tok", "deckA", 1, "t1") is True
    assert repo.reserve_public("tok", "deckB", 1, "t2") is False  # taken
    repo.release_public("tok")
    assert repo.reserve_public("tok", "deckB", 1, "t3") is True  # freed

@mock_aws
def test_public_reservation_not_in_gsis():
    res = boto3.resource("dynamodb", region_name="us-east-1"); _make(res)
    repo = DeckRepo(TABLE, res)
    repo.reserve_public("tok", "deckA", 1, "t1")
    # reservation has no status -> not in byUpdatedAt; no alias -> not in byAlias
    assert repo.query_by_alias("tok") is None
    assert repo.get(dm.public_pk("tok"))["ownerDeckId"] == "deckA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_ddb_v3.py -v`
Expected: FAIL — AttributeError reserve_public.

- [ ] **Step 3: Write minimal implementation**

Append to `lambdas/api/ddb.py` (reuse existing `ClientError` import from reserve_alias; if not imported, add `from botocore.exceptions import ClientError`), mirroring reserve_alias/release_alias:

```python
    def reserve_public(self, token: str, deck_id: str, public_version: int, now_iso: str) -> bool:
        item = dm.new_public_reservation(token, deck_id, public_version, now_iso)
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(deckId)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def release_public(self, token: str) -> None:
        self.delete(dm.public_pk(token))
```

(Ensure `import deck_model as dm` is present in ddb.py; if reserve_alias already imports it, reuse.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_ddb_v3.py tests/lambdas/test_ddb_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/ddb.py tests/lambdas/test_ddb_v3.py
git commit -m "feat: add atomic public token reservation to repo"
```

---

## Task 3: API — share/republish/unshare + 무인증 public + download presign

**Files:**
- Modify: `lambdas/api/handler.py`
- Test: `tests/lambdas/test_api_handler_v3.py`

**Interfaces:**
- Consumes: DeckRepo(+reserve_public/release_public), deck_model(+public helpers, slide_key, thumb_key), `secrets`, `boto3` s3.
- Produces routes (place share/download/public BEFORE generic /decks blocks; `/share`,`/share/republish`,`/download` suffixes before generic PUT/POST; `/api/public/` prefix handled without requiring _pid):
  - `PUT /api/decks/{id}/share` (JWT) — if item.get("publicToken"): return existing `{token, url}`. Else: token=secrets.token_urlsafe(12); loop reserve_public until True (regen on False); copy S3 `slide_key(id, currentVersion)` -> `public/{token}/index.html` (s3.copy_object); repo.put(set_public_token(item, token, now)). Return `{token, url: f"/p/{token}"}`.
  - `POST /api/decks/{id}/share/republish` (JWT) — item must have publicToken (else 400); copy current version -> `public/{token}/index.html`; update reservation publicVersion (put new_public_reservation again with same token — overwrite OK). Return `{ok:true}`.
  - `DELETE /api/decks/{id}/share` (JWT) — token=item.get("publicToken"); if set: delete `public/{token}/` prefix objects, release_public(token), repo.put(set_public_token(item, None, now)). Return `{ok:true}`.
  - `GET /api/public/{token}` (**무인증** — via NoneAuthorizer route in CDK) — res=repo.get(public_pk(token)); if none 404; return `{title: <owner deck title>, htmlUrl: f"/public/{token}/index.html"}`. Fetch owner deck for title (repo.get(ownerDeckId)); if owner missing 404. Do NOT leak deckId/versions/tags/group.
  - `DELETE /api/decks/{id}` hard delete: also delete `public/{token}/`(if publicToken) + release_public + `pdfs/{deckId}/` prefix.
  - `GET /api/decks/{id}/download?format=html|pdf&version={n}` (JWT) — item=get(id) (404 if none); n = version or currentVersion; if format==html key=slide_key(id,n); if pdf: find version n's pdfKey (via item versions); if missing -> 409 "pdf not ready"; else key=pdfKey. Generate presigned GET url with ResponseContentDisposition=`attachment; filename="{safe_title}-v{n}.{ext}"`, ExpiresIn=300. Return `{downloadUrl}`.

- [ ] **Step 1: Write the failing test** (moto DDB+S3 with byAlias GSI; mirror v2 setup)

Key cases:
```python
# tests/lambdas/test_api_handler_v3.py  (setup like test_api_handler_v2 with byAlias GSI + bucket)
# - PUT /share on deck with v1 -> 200, returns token+url; deck.publicToken set; public/{token}/index.html exists (copied); GET /api/public/{token} -> 200 {title, htmlUrl}, NO deckId in body.
# - PUT /share again -> returns SAME token (idempotent).
# - DELETE /share -> deck.publicToken None; public/{token}/ gone; GET /api/public/{token} -> 404.
# - re-share after delete -> NEW token (different from first).
# - GET /api/public/badtoken -> 404.
# - download html -> 200 {downloadUrl contains presigned}, format=pdf with no pdfKey -> 409; after setting version pdfKey (via dm.set_version_pdf + put), pdf -> 200.
# - hard delete a shared deck removes public/ and pdfs/ objects.
```
(Write concrete asserts; use s3 stub/moto — presigned url just assert it's a non-empty string containing the bucket/key.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler_v3.py -v`
Expected: FAIL (routes 404 / no route).

- [ ] **Step 3: Write minimal implementation**

Add routes to handler.py per Interfaces. Reference for the public (unauth-at-APIGW, but handler is origin-agnostic) + download blocks:

```python
    import secrets  # at top of module

    # --- public resolve (unauthenticated route in APIGW) ---
    if method == "GET" and "/api/public/" in path:
        token = (event.get("pathParameters") or {}).get("token") or path.rsplit("/", 1)[-1]
        res = repo.get(dm.public_pk(token))
        if not res:
            return _resp(404, {"error": "not found"})
        owner = repo.get(res["ownerDeckId"])
        if not owner:
            return _resp(404, {"error": "not found"})
        return _resp(200, {"title": owner.get("title", ""), "htmlUrl": f"/public/{token}/index.html"})

    # --- share ---
    if method == "PUT" and path.endswith("/share"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        existing = item.get("publicToken")
        if existing:
            return _resp(200, {"token": existing, "url": f"/p/{existing}"})
        n = item["currentVersion"]
        token = secrets.token_urlsafe(12)
        while not repo.reserve_public(token, item["deckId"], n, now_iso()):
            token = secrets.token_urlsafe(12)
        _s3().copy_object(
            Bucket=_bucket(),
            CopySource={"Bucket": _bucket(), "Key": dm.slide_key(item["deckId"], n)},
            Key=f"public/{token}/index.html", ContentType="text/html",
        )
        repo.put(dm.set_public_token(item, token, now_iso()))
        return _resp(200, {"token": token, "url": f"/p/{token}"})

    if method == "POST" and path.endswith("/share/republish"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        token = item.get("publicToken")
        if not token:
            return _resp(400, {"error": "not shared"})
        n = item["currentVersion"]
        _s3().copy_object(
            Bucket=_bucket(),
            CopySource={"Bucket": _bucket(), "Key": dm.slide_key(item["deckId"], n)},
            Key=f"public/{token}/index.html", ContentType="text/html",
        )
        repo.reserve_public(token, item["deckId"], n, now_iso())  # overwrite publicVersion (idempotent same token)
        return _resp(200, {"ok": True})

    if method == "DELETE" and path.endswith("/share"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        token = item.get("publicToken")
        if token:
            _delete_prefix(f"public/{token}/")   # helper: list+delete objects under prefix
            repo.release_public(token)
            repo.put(dm.set_public_token(item, None, now_iso()))
        return _resp(200, {"ok": True})

    # --- download ---
    if method == "GET" and path.endswith("/download"):
        item = repo.get(_pid(event))
        if not item:
            return _resp(404, {"error": "not found"})
        fmt = qs.get("format", "html")
        n = int(qs.get("version") or item["currentVersion"])
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", item.get("title") or item["deckId"])
        if fmt == "pdf":
            ver = next((v for v in item["versions"] if v["n"] == n), None)
            key = ver.get("pdfKey") if ver else None
            if not key:
                return _resp(409, {"error": "pdf not ready"})
            ext = "pdf"
        else:
            key = dm.slide_key(item["deckId"], n)
            ext = "html"
        url = _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_title}-v{n}.{ext}"'},
            ExpiresIn=300,
        )
        return _resp(200, {"downloadUrl": url})
```

Add helper `_delete_prefix(prefix)` (list_objects_v2 + delete_objects) reused by hard delete; update hard delete to also clean `public/{token}/` and `pdfs/{deckId}/`. Add `import re, secrets` at top.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_api_handler_v3.py tests/lambdas/test_api_handler_v2.py tests/lambdas/test_api_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lambdas/api/handler.py tests/lambdas/test_api_handler_v3.py
git commit -m "feat: add share/republish/unshare, public resolve, and download presign"
```

---

## Task 4: Thumbnail Lambda — PDF 사전 생성

**Files:**
- Modify: `lambdas/thumbnail/handler.py`
- Test: `tests/lambdas/test_thumbnail_v3.py`

**Interfaces:**
- Produces:
  - `capture_pdf(html_bytes: bytes) -> bytes` — Chromium print-to-PDF (landscape, print CSS). Isolated like capture_png; tests stub it.
  - handler: after thumbnail, also generate PDF -> `pdfs/{deckId}/v{n}.pdf` (ContentType application/pdf), then DDB `set_version_pdf(item, n, pdfkey, now)`. Idempotent.
- Use `pdf_key(deck_id, n) -> f"pdfs/{deck_id}/v{n}.pdf"` (add to deck_model or inline in handler; prefer deck_model for reuse by handler download + skill).

- [ ] **Step 1: Write the failing test**

```python
# tests/lambdas/test_thumbnail_v3.py  (importlib-load thumbnail handler as in test_thumbnail.py; moto + byAlias GSI table + bucket)
# - put slides/roadmap/v1/index.html; deck item at v1 (via add_pending_version so version exists)
# - monkeypatch t.capture_png -> b"PNG", t.capture_pdf -> b"%PDF-fake"
# - run handler event -> assert thumbnails/roadmap/v1.png AND pdfs/roadmap/v1.pdf exist,
#   and repo.get("roadmap") version 1 has thumbnailKey and pdfKey set.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_thumbnail_v3.py -v`
Expected: FAIL — capture_pdf / pdfKey absent.

- [ ] **Step 3: Write minimal implementation**

Add `pdf_key` to deck_model (`def pdf_key(deck_id, n): return f"pdfs/{deck_id}/v{n}.pdf"`). In thumbnail/handler.py add capture_pdf (playwright `page.pdf(...)` inside the same sync_playwright block pattern as capture_png; keep import inside function) and in handler after thumbnail write:

```python
        pdf = capture_pdf(html)
        pkey = dm.pdf_key(deck_id, n)
        s3.put_object(Bucket=bucket, Key=pkey, Body=pdf, ContentType="application/pdf",
                      CacheControl="public, max-age=31536000, immutable")
        item = repo.get(deck_id) or item
        item = dm.set_version_pdf(item, n, pkey, now_iso())
        repo.put(item)
```

(Place after the existing set_version_thumbnail put; re-get to build on latest. Keep capture_pdf stubbable — import playwright inside.)

capture_pdf reference:
```python
def capture_pdf(html_bytes: bytes) -> bytes:
    import tempfile
    from playwright.sync_api import sync_playwright
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html_bytes); p = f.name
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        page = b.new_page()
        page.goto(f"file://{p}")
        page.wait_for_timeout(1200)
        data = page.pdf(landscape=True, print_background=True, width="1280px", height="720px")
        b.close()
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/lambdas/test_thumbnail_v3.py tests/lambdas/test_thumbnail.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lambdas/thumbnail/handler.py shared/deck_model.py tests/lambdas/test_thumbnail_v3.py
git commit -m "feat: pre-generate per-version PDF in thumbnail Lambda"
```

---

## Task 5: CDK — share/download 라우트(JWT) + public 무인증 라우트

**Files:**
- Modify: `infra/slidecast/slidecast_stack.py`
- Test: `tests/infra/test_synth_v3.py`

**Interfaces:**
- JWT routes (default authorizer): `ANY /api/decks/{id}/share`, `ANY /api/decks/{id}/share/republish`, `ANY /api/decks/{id}/download`.
- Unauthenticated route: `GET /api/public/{token}` with `authorizer=authorizers.HttpNoneAuthorizer()` explicitly (overrides the HttpApi default_authorizer).
- No new S3 bucket/GSI; `pdfs/` and `public/` are prefixes in the existing bucket. Thumbnail Lambda already has bucket read/write.

- [ ] **Step 1: Write the failing test**

```python
# tests/infra/test_synth_v3.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template
from slidecast.slidecast_stack import SlidecastStack

def _routes():
    app = App()
    t = Template.from_stack(SlidecastStack(app, "T", env={"account": "123456789012", "region": "us-east-1"}))
    return [r["Properties"]["RouteKey"] for r in t.find_resources("AWS::ApiGatewayV2::Route").values()], t

def test_share_download_public_routes_exist():
    keys, _ = _routes()
    assert any("/api/decks/{id}/share" in k for k in keys)
    assert any("/api/decks/{id}/download" in k for k in keys)
    assert any("GET /api/public/{token}" in k for k in keys)

def test_public_route_has_no_jwt_authorizer():
    keys, t = _routes()
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    pub = [r for r in routes.values() if "/api/public/{token}" in r["Properties"]["RouteKey"]]
    assert pub, "public route missing"
    # NoneAuthorizer => AuthorizationType NONE (or no AuthorizerId)
    props = pub[0]["Properties"]
    assert props.get("AuthorizationType", "NONE") == "NONE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && mkdir -p shared_layer/python && cp shared/deck_model.py shared_layer/python/ && cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py && cp shared/deck_model.py lambdas/thumbnail/deck_model.py && python3 -m pytest tests/infra/test_synth_v3.py -v`
Expected: FAIL — routes absent.

- [ ] **Step 3: Write minimal implementation**

In slidecast_stack.py add JWT routes to the existing explicit-routes loop list: `/api/decks/{id}/share`, `/api/decks/{id}/share/republish`, `/api/decks/{id}/download`. Then add the public route separately with an explicit None authorizer:

```python
        http_api.add_routes(
            path="/api/public/{token}",
            methods=[apigw.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("IntApiPublic", api_fn),
            authorizer=authorizers.HttpNoneAuthorizer(),
        )
```

(Confirm the installed aws-cdk-lib exposes HttpNoneAuthorizer in aws_apigatewayv2_authorizers; if named differently, adapt and note in report.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/infra/test_synth_v3.py tests/infra/test_synth_v2.py tests/infra/test_synth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/slidecast/slidecast_stack.py tests/infra/test_synth_v3.py
git commit -m "feat: add share/download JWT routes and unauthenticated public route"
```

---

## Task 6: 뷰어 — types + api 클라이언트

**Files:**
- Modify: `viewer/src/types.ts`, `viewer/src/api.ts`
- Test: extend `viewer/src/api.test.ts`

**Interfaces:**
- types.ts: `Deck` gains `publicToken: string | null`; `Version` gains `pdfKey: string | null`. `interface PublicDeck { title: string; htmlUrl: string }`.
- api.ts (JWT via auth()): `share(id): Promise<{token,url}>`, `unshare(id)`, `republish(id)`, `downloadUrl(id, format, version?): Promise<{downloadUrl}>`. Unauth: `getPublic(token): Promise<PublicDeck>` — NO auth header (public route; must NOT send bearer since token may be absent/expired for a logged-out viewer). Actually for a logged-out public viewer there is no token; getPublic must call fetch WITHOUT auth().

- [ ] **Step 1: Write the failing test**

Extend api.test.ts: assert `share(id)` POSTs to `/api/decks/{id}/share` with bearer; assert `getPublic(token)` fetches `/api/public/{token}` WITHOUT an Authorization header (logged-out safe).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/api.test.ts`
Expected: FAIL — methods absent.

- [ ] **Step 3: Write minimal implementation**

types.ts: add fields + PublicDeck. api.ts inside createApi return:
```ts
    async share(id: string) { return j(await fetch(`${baseUrl}/api/decks/${id}/share`, { method: "PUT", headers: auth() })); },
    async unshare(id: string) { return j(await fetch(`${baseUrl}/api/decks/${id}/share`, { method: "DELETE", headers: auth() })); },
    async republish(id: string) { return j(await fetch(`${baseUrl}/api/decks/${id}/share/republish`, { method: "POST", headers: auth() })); },
    async downloadUrl(id: string, format: "html" | "pdf", version?: number) {
      const q = new URLSearchParams({ format }); if (version != null) q.set("version", String(version));
      return j(await fetch(`${baseUrl}/api/decks/${id}/download?${q}`, { headers: auth() }));
    },
```
Add a module-level `getPublic` (does NOT need a token/auth): export a standalone `export async function fetchPublic(baseUrl: string, token: string): Promise<PublicDeck> { const r = await fetch(`${baseUrl}/api/public/${token}`); if (!r.ok) throw new Error(`public ${r.status}`); return r.json(); }` — used by the logged-out public page.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run src/api.test.ts && npx tsc --noEmit`
Expected: PASS + tsc clean.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/types.ts viewer/src/api.ts viewer/src/api.test.ts
git commit -m "feat: add share/download/public API client methods"
```

---

## Task 7: 뷰어 UI — ShareModal + PublicPage + 카드 다운로드 + /p 라우트

**Files:**
- Create: `viewer/src/components/ShareModal.tsx`, `viewer/src/components/PublicPage.tsx`
- Modify: `viewer/src/components/DeckCard.tsx`, `VersionMenu.tsx`, `viewer/src/App.tsx`, `Gallery.tsx`
- Test: extend `viewer/src/components/Gallery.test.tsx` (+ a PublicPage test)

**Interfaces:**
- `ShareModal({ deck, api, onClose, onChanged })` — 공개 토글: OFF면 "공유하기"(api.share→링크 표시), ON이면 링크(readonly input)+복사 버튼+재발행(api.republish)+공유 해제(api.unshare, 확인). double-submit 가드(ref).
- `PublicPage({ token, baseUrl })` — 무인증. mount 시 `fetchPublic(baseUrl, token)`; 성공→풀스크린 iframe(sandbox allow-scripts, src=htmlUrl); 실패(404)→"만료되었거나 없는 링크". 로그인/갤러리 없음.
- DeckCard: "공유" 버튼(모달 오픈) + 공개 배지(deck.publicToken 있으면) + "다운로드" 컨트롤(HTML / PDF; PDF는 현재 버전 pdfKey 없으면 비활성+"PDF 생성 중"). 다운로드는 api.downloadUrl→받은 downloadUrl로 `window.location.assign` 또는 임시 anchor click.
- VersionMenu: 각 버전에 다운로드(HTML/PDF, 그 버전 pdfKey 기준).
- App.tsx: `window.location.pathname`이 `/p/{token}`이면 (auth 무관) `<PublicPage token baseUrl="">` 렌더 — 로그인 게이트 이전에 분기. (기존 /s/{alias}는 로그인 필요, /p/{token}은 불필요.)
- Gallery: DeckCard에 api 전달(다운로드/공유용) — 이미 api 보유.

- [ ] **Step 1: Write the failing test**

Gallery.test.tsx: fakeApi with share/unshare/downloadUrl; assert clicking 공유 opens modal and calling share sets a link; assert a deck with publicToken shows the 공개 badge. Add PublicPage.test.tsx: fetchPublic stubbed → renders iframe with htmlUrl; 404 → renders not-found text.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run`
Expected: FAIL — components absent.

- [ ] **Step 3: Write minimal implementation**

Implement ShareModal, PublicPage (dark cinematic, theme tokens), extend DeckCard/VersionMenu with download controls + share button + public badge, wire App.tsx `/p/{token}` branch BEFORE the auth gate (public viewers are logged out). Download action: `const {downloadUrl} = await api.downloadUrl(id, fmt, n); const a = document.createElement("a"); a.href = downloadUrl; a.click();`. Guard share/unshare/republish submits with a ref (double-submit lesson). PDF option disabled when the target version has no pdfKey (show "PDF 생성 중").

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer/viewer && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all pass, tsc clean, build ok.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/components/ viewer/src/App.tsx
git commit -m "feat: add share modal, public page, and download UI"
```

---

## Task 8: 로컬 스킬 — share/unshare + 정리

**Files:**
- Modify: `skill/slidecast-append/slidecast_append.py`, `SKILL.md`
- Test: `tests/skill/test_slidecast_append_v3.py`

**Interfaces:**
- `share(deck_id, table, bucket, dynamodb=None, s3=None) -> str` — mirror API share: existing token returned; else reserve_public loop + copy current version to public/{token}/index.html + set_public_token; return `/p/{token}`.
- `unshare(deck_id, table, bucket, dynamodb=None, s3=None)` — delete public/{token}/ + release_public + set_public_token None.
- hard_delete: also delete public/{token}/ (if token) + pdfs/{deck_id}/ prefixes.
- CLI: `--share <deckId>`, `--unshare <deckId>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/skill/test_slidecast_append_v3.py (moto + byAlias GSI; stub capture)
# - append a deck (v1). share(deckId) -> returns /p/{token}; deck.publicToken set; public/{token}/index.html exists.
# - share again -> same token.
# - unshare -> publicToken None; public/{token}/ gone.
# - hard_delete a shared deck with a pdf -> public/ and pdfs/ prefixes removed.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append_v3.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Add share/unshare functions (reuse deck_model + repo.reserve_public/release_public + s3.copy_object/_delete prefix) and CLI args; extend hard_delete to clean public/ and pdfs/ prefixes. Update SKILL.md (no emojis).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/skill/test_slidecast_append_v3.py tests/skill/test_slidecast_append_v2.py tests/skill/test_slidecast_append.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skill/ tests/skill/test_slidecast_append_v3.py
git commit -m "feat: add share/unshare and public/pdf cleanup to local skill"
```

---

## Task 9: 통합 검증 + 리뷰 + 배포

**Files:** none (verify/deploy) + README

- [ ] **Step 1: 전체 테스트**

Run: `cd /Workshop/html-viewer && python3 -m pytest tests/ -q && (cd viewer && npx vitest run && npx tsc --noEmit && npm run build)`
Expected: 모든 테스트 통과 + 빌드 성공.

- [ ] **Step 2: 최종 whole-branch 리뷰 (adversarial)**

opus 서브에이전트 whole-branch 리뷰. codex 게이트 시도하되 **비정상 실패/과다 지연 시 skip**(사용자 상시 지시). 중점 확인:
- 무인증 노출이 정확히 `GET /api/public/{token}` + `public/*`뿐. share/republish/unshare/download는 전부 JWT.
- `GET /api/public/{token}`이 title+htmlUrl만 반환하고 deckId/versions/tags/group 미노출.
- OFF 후 옛 토큰 404, 재공개 새 토큰, 재발행 없이는 옛 스냅샷 유지.
- 다운로드 presigned가 프라이빗 키에 대해서만, attachment 헤더, 짧은 만료. PDF 미준비 409.
- public token 예약이 원자적(조건부), GSI 오염 없음(reservation에 status/alias 없음).
- hard delete가 public/ + pdfs/ 정리.
- 공개 iframe sandbox 유지. /p 라우트가 로그인 게이트 이전에 분기(로그아웃 뷰어 동작).
CRITICAL/Important 발견 시 수정→재검증.

- [ ] **Step 3: 배포**

```bash
cd /Workshop/html-viewer && ./scripts/deploy.sh && ./scripts/deploy-viewer.sh
```
Docker 필요(thumbnail 이미지 재빌드 — capture_pdf 추가). 배포 후 스모크:
- `GET /api/public/nonexistent` → 404 (JWT 없이 도달 → 무인증 라우트 동작 확인; 401 아님).
- `PUT /api/decks/x/share` (무인증) → 401 (JWT 보호 확인).
- `GET /api/decks/x/download` (무인증) → 401.
- `/p/anything` → 200 SPA 서빙(폴백).

- [ ] **Step 4: README 갱신**

공유(`/p/{token}`, 토글/재발행/OFF)와 다운로드(html/pdf, presigned) 사용법 + 스킬 `--share`/`--unshare` 추가.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document public share and download"
```

---

## Self-Review (계획 검토)

- **Spec coverage:** public 토큰 예약(Task 1,2), share/republish/unshare(Task 3), 무인증 public 라우트(Task 3,5), download presign html/pdf(Task 3), PDF 사전 생성(Task 4), CDK 라우트+NoneAuthorizer(Task 5), 뷰어 types/api(Task 6), ShareModal/PublicPage/다운로드 UI/`/p` 라우트(Task 7), 로컬 스킬 share/unshare + 정리(Task 8) — 스펙 전 항목 커버.
- **Placeholder scan:** Task 1-6은 완전 코드. Task 3의 `_delete_prefix` 헬퍼는 명시(list+delete). Task 7·8은 기존 컴포넌트/스킬 확장이라 변경 지점·시그니처·핵심 코드 제공. Task 3·8 테스트는 케이스를 서술로 명시하고 v2 패턴 준수 지시.
- **Type consistency:** `public_pk`/`new_public_reservation`/`set_public_token`/`set_version_pdf`/`pdf_key`가 Task 1/4 정의와 Task 3/8 사용처 일치. `reserve_public`/`release_public`가 Task 2 정의와 Task 3/8 사용처 일치. api.ts(share/unshare/republish/downloadUrl/fetchPublic)가 Task 6 정의와 Task 7 사용처 일치.
- **주의:** (a) `/api/public/{token}` 무인증은 CDK NoneAuthorizer로만 열림 — 핸들러는 origin-agnostic이므로 CDK 라우트 authorizer가 유일한 게이트. Task 5 synth 테스트가 AuthorizationType NONE 확인. (b) getPublic/fetchPublic은 로그아웃 뷰어용이라 bearer 미첨부 — Task 6에 명시. (c) reservation 아이템은 status/alias 미설정으로 GSI 오염 방지(v2-9와 동일 불변식).
