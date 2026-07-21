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
    import importlib, handler as h
    importlib.reload(h)
    resp = h.handler(_evt("POST", "/api/decks", {"filename": "My Deck.html", "title": "My Deck"}))
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["deckId"] == "my-deck"
    assert body["version"] == 1
    assert "uploadUrl" in body
    # POST must persist a pending version so the deck is recoverable even
    # if the thumbnail Lambda never runs.
    from ddb import DeckRepo
    item = DeckRepo(TABLE, res).get("my-deck")
    assert item["currentVersion"] == 1
    assert item["versions"][0]["n"] == 1
    assert item["versions"][0]["thumbnailKey"] is None


@mock_aws
def test_put_after_rollback_yields_monotonic_version(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import importlib, handler as h
    importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version, set_current
    repo = DeckRepo(TABLE, res)
    item = add_version(new_deck_item("d", "D", [], "t0"), "k1", 1, "t1")
    item = add_version(item, "k2", 1, "t2")           # now has v1, v2, current=2
    item = set_current(item, 1, "t3")                  # rolled back to v1
    repo.put(item)
    resp = h.handler(_evt("PUT", "/api/decks/d", path_params={"id": "d"}))
    body = json.loads(resp["body"])
    # Must be v3, not overwriting v2.
    assert body["version"] == 3
    got = repo.get("d")
    ns = sorted(v["n"] for v in got["versions"])
    assert ns == [1, 2, 3]


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
