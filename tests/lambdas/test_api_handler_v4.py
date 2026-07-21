import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, importlib
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


def _seed(res, s3, deck_id="a", n=1):
    from ddb import DeckRepo
    import deck_model as dm
    repo = DeckRepo(TABLE, res)
    item = dm.new_deck_item(deck_id, "T", [], "t0")
    item = dm.add_pending_version(item, n, "t1")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key(deck_id, n),
                  Body=b"<html>hi</html>", ContentType="text/html")
    return repo


class _StubPaginatingS3:
    """Wraps a real S3 client but chunks list_objects_v2 to force pagination."""

    def __init__(self, real, page_size=2):
        self._real = real
        self._page_size = page_size
        self.delete_calls = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def list_objects_v2(self, **kwargs):
        # Mimic real S3: opaque token = last returned key, safe under
        # concurrent deletion because next page filters keys > last_key.
        token = kwargs.pop("ContinuationToken", None)
        resp = self._real.list_objects_v2(**kwargs)
        contents = resp.get("Contents", [])
        if token is not None:
            contents = [o for o in contents if o["Key"] > token]
        page = contents[:self._page_size]
        out = {"Contents": page}
        if len(contents) > self._page_size:
            out["IsTruncated"] = True
            out["NextContinuationToken"] = page[-1]["Key"]
        return out

    def delete_objects(self, **kwargs):
        self.delete_calls += 1
        return self._real.delete_objects(**kwargs)


@mock_aws
def test_delete_prefix_pagination_deletes_all_pages(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)

    # Seed 5 objects under public/tok/ to force >1 page at page_size=2
    for i in range(5):
        s3.put_object(Bucket=BUCKET, Key=f"public/tok/f{i}", Body=b"x")

    stub = _StubPaginatingS3(s3, page_size=2)
    monkeypatch.setattr(h, "_s3", lambda: stub)

    h._delete_prefix("public/tok/")
    remaining = s3.list_objects_v2(Bucket=BUCKET, Prefix="public/tok/").get("Contents", [])
    assert remaining == []
    assert stub.delete_calls == 3  # 2+2+1


@mock_aws
def test_share_copy_uses_no_cache_headers(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)

    r = h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))
    token = json.loads(r["body"])["token"]
    obj = s3.get_object(Bucket=BUCKET, Key=f"public/{token}/index.html")
    assert "no-cache" in obj.get("CacheControl", "")
    assert "no-store" in obj["CacheControl"]
    assert obj.get("ContentType") == "text/html"


@mock_aws
def test_republish_copy_uses_no_cache_headers(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    r = h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))
    token = json.loads(r["body"])["token"]
    # overwrite the public object with different headers then republish
    s3.put_object(Bucket=BUCKET, Key=f"public/{token}/index.html", Body=b"old",
                  ContentType="text/html", CacheControl="public, max-age=99")
    r2 = h.handler(_evt("POST", "/api/decks/a/share/republish", pp={"id": "a"}))
    assert r2["statusCode"] == 200
    obj = s3.get_object(Bucket=BUCKET, Key=f"public/{token}/index.html")
    assert "no-cache" in obj.get("CacheControl", "")


@mock_aws
def test_download_pdf_wrong_prefix_returns_409(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    import deck_model as dm
    repo = _seed(res, s3, deck_id="a", n=1)
    item = repo.get("a")
    # inject a malformed pdfKey pointing outside pdfs/a/
    item["versions"][0]["pdfKey"] = "pdfs/other-deck/v1.pdf"
    repo.put(item)
    r = h.handler(_evt("GET", "/api/decks/a/download", pp={"id": "a"},
                       qs={"format": "pdf", "version": "1"}))
    assert r["statusCode"] == 409
    assert "not ready" in json.loads(r["body"])["error"]


@mock_aws
def test_download_pdf_valid_prefix_presigns(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = _seed(res, s3, deck_id="a", n=1)
    item = repo.get("a")
    item["versions"][0]["pdfKey"] = "pdfs/a/v1.pdf"
    repo.put(item)
    r = h.handler(_evt("GET", "/api/decks/a/download", pp={"id": "a"},
                       qs={"format": "pdf", "version": "1"}))
    assert r["statusCode"] == 200
    assert "downloadUrl" in json.loads(r["body"])


@mock_aws
def test_delete_download_path_does_not_archive(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = _seed(res, s3)
    r = h.handler(_evt("DELETE", "/api/decks/a/download", pp={"id": "a"}))
    assert r["statusCode"] == 404
    # Deck must still be active (not archived)
    assert repo.get("a")["status"] == "active"


@mock_aws
def test_put_download_path_does_not_create_new_version(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = _seed(res, s3)
    before = len(repo.get("a")["versions"])
    r = h.handler(_evt("PUT", "/api/decks/a/download", pp={"id": "a"}))
    assert r["statusCode"] == 404
    assert len(repo.get("a")["versions"]) == before


@mock_aws
def test_delete_share_path_does_not_archive_deck(monkeypatch):
    """DELETE /api/decks/{id}/share must only unshare, never archive."""
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = _seed(res, s3)
    r = h.handler(_evt("DELETE", "/api/decks/a/share", pp={"id": "a"}))
    assert r["statusCode"] == 200
    assert repo.get("a")["status"] == "active"


@mock_aws
def test_post_decks_with_existing_group_assigns_deck(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    import deck_model as dm
    repo = DeckRepo(TABLE, res)
    repo.put(dm.new_group_item("marketing", "Marketing", "t0"))

    r = h.handler(_evt("POST", "/api/decks", body={"filename": "brief.html", "title": "Brief", "group": "marketing"}))
    assert r["statusCode"] == 200
    deck_id = json.loads(r["body"])["deckId"]
    assert repo.get(deck_id)["group"] == "marketing"


@mock_aws
def test_post_decks_with_ghost_group_ignores_and_leaves_unassigned(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = DeckRepo(TABLE, res)

    r = h.handler(_evt("POST", "/api/decks", body={"filename": "brief.html", "group": "ghost"}))
    assert r["statusCode"] == 200
    deck_id = json.loads(r["body"])["deckId"]
    assert repo.get(deck_id).get("group") is None


@mock_aws
def test_post_decks_without_group_is_unassigned(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = DeckRepo(TABLE, res)

    r = h.handler(_evt("POST", "/api/decks", body={"filename": "brief.html"}))
    assert r["statusCode"] == 200
    deck_id = json.loads(r["body"])["deckId"]
    assert repo.get(deck_id).get("group") is None


@mock_aws
def test_post_decks_reupload_does_not_change_group(monkeypatch):
    """Re-uploading an existing deck (new version) must respect its filed group."""
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    import deck_model as dm
    repo = DeckRepo(TABLE, res)
    repo.put(dm.new_group_item("sales", "Sales", "t0"))
    repo.put(dm.new_group_item("marketing", "Marketing", "t0"))
    # Seed an existing deck already filed under "sales".
    item = dm.new_deck_item("brief-html", "Brief", [], "t0")
    item = dm.set_group(item, "sales", "t0")
    item = dm.add_pending_version(item, 1, "t1")
    repo.put(item)

    r = h.handler(_evt("POST", "/api/decks", body={"filename": "brief.html", "group": "marketing"}))
    assert r["statusCode"] == 200
    assert repo.get("brief-html")["group"] == "sales"
