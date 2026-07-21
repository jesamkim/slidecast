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


def _seed(res, s3, deck_id="a", title="Title", n=1):
    from ddb import DeckRepo
    import deck_model as dm
    repo = DeckRepo(TABLE, res)
    item = dm.new_deck_item(deck_id, title, [], "t0")
    item = dm.add_pending_version(item, n, "t1")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key(deck_id, n),
                  Body=b"<html>hi</html>", ContentType="text/html")
    return repo


@mock_aws
def test_public_resolve_increments_views(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]

    r1 = h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))
    r2 = h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))
    assert r1["statusCode"] == 200 and r2["statusCode"] == 200
    # public body stays minimal (no stats leak)
    pub = json.loads(r1["body"])
    assert set(pub.keys()) == {"title", "htmlUrl"}

    v = h.handler(_evt("GET", "/api/decks/a/views", pp={"id": "a"}))
    assert v["statusCode"] == 200
    body = json.loads(v["body"])
    assert body["total"] == 2
    assert len(body["byDay"]) == 1
    assert body["byDay"][0]["count"] == 2
    assert len(body["byDay"][0]["date"]) == 10  # YYYY-MM-DD


@mock_aws
def test_public_bad_token_does_not_count(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = DeckRepo(TABLE, res)
    r = h.handler(_evt("GET", "/api/public/badtoken", pp={"token": "badtoken"}))
    assert r["statusCode"] == 404
    assert repo.get_views("badtoken") == {"total": 0, "byDay": {}}


@mock_aws
def test_views_unshared_deck_returns_zero(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3, deck_id="b", title="B")
    r = h.handler(_evt("GET", "/api/decks/b/views", pp={"id": "b"}))
    assert r["statusCode"] == 200
    assert json.loads(r["body"]) == {"total": 0, "byDay": []}


@mock_aws
def test_views_export_csv(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))

    r = h.handler(_evt("GET", "/api/decks/a/views/export",
                       pp={"id": "a"}, qs={"format": "csv"}))
    assert r["statusCode"] == 200
    assert r["headers"]["Content-Type"] == "text/csv"
    assert 'attachment; filename="a-views.csv"' in r["headers"]["Content-Disposition"]
    assert r["body"].startswith("date,count")


@mock_aws
def test_views_export_json(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))

    r = h.handler(_evt("GET", "/api/decks/a/views/export",
                       pp={"id": "a"}, qs={"format": "json"}))
    assert r["statusCode"] == 200
    assert r["headers"]["Content-Type"] == "application/json"
    assert 'attachment; filename="a-views.json"' in r["headers"]["Content-Disposition"]
    body = json.loads(r["body"])
    assert body["deckId"] == "a"
    assert body["total"] == 1
    assert isinstance(body["byDay"], list) and body["byDay"][0]["count"] == 1


@mock_aws
def test_decks_list_includes_view_count_for_public_deck(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3, deck_id="a", title="A")
    _seed(res, s3, deck_id="b", title="B")
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))
    h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))

    r = h.handler(_evt("GET", "/api/decks"))
    assert r["statusCode"] == 200
    decks = {d["deckId"]: d for d in json.loads(r["body"])["decks"]}
    assert decks["a"]["viewCount"] == 2
    assert decks["b"].get("viewCount", 0) == 0


@mock_aws
def test_resolve_still_200_when_increment_raises(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]

    def boom(self, *a, **kw):
        raise RuntimeError("ddb down")
    monkeypatch.setattr("ddb.DeckRepo.increment_views", boom)

    r = h.handler(_evt("GET", f"/api/public/{tok}", pp={"token": tok}))
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["title"] == "Title"
    assert body["htmlUrl"] == f"/public/{tok}/index.html"


@mock_aws
def test_republish_preserves_view_counters(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    import deck_model as dm
    repo = _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]

    # Accumulate 3 views.
    for _ in range(3):
        repo.increment_views(tok, "2026-07-21")
    assert repo.get_views(tok)["total"] == 3

    # Add a new version so republish has something to promote.
    item = repo.get("a")
    item = dm.add_pending_version(item, 2, "t2")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key("a", 2),
                  Body=b"<html>v2</html>", ContentType="text/html")

    r = h.handler(_evt("POST", "/api/decks/a/share/republish", pp={"id": "a"}))
    assert r["statusCode"] == 200

    # Views survive republish (same token, same reservation).
    v = h.handler(_evt("GET", "/api/decks/a/views", pp={"id": "a"}))
    assert v["statusCode"] == 200
    body = json.loads(v["body"])
    assert body["total"] == 3
    # publicVersion was bumped to the new content version.
    reservation = repo.get(dm.public_pk(tok))
    assert reservation["publicVersion"] == 2
