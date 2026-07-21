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
    r = h.handler(_evt("POST", "/api/groups", {"name": "Marketing"}))
    assert r["statusCode"] == 200 and json.loads(r["body"])["groupId"] == "marketing"
    h.handler(_evt("PUT", "/api/decks/a/group", {"groupId": "marketing"}, pp={"id": "a"}))
    assert repo.get("a")["group"] == "marketing"
    r = h.handler(_evt("GET", "/api/decks", qs={"group": "marketing"}))
    ids = [d["deckId"] for d in json.loads(r["body"])["decks"]]
    assert ids == ["a"]
    h.handler(_evt("DELETE", "/api/groups/marketing", pp={"groupId": "marketing"}))
    assert repo.get("a").get("group") is None
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
    assert h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": "api"}, pp={"id": "a"}))["statusCode"] == 400
    assert h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": "Road Map"}, pp={"id": "a"}))["statusCode"] == 200
    assert repo.get("a")["alias"] == "road-map"
    assert h.handler(_evt("PUT", "/api/decks/b/alias", {"alias": "road-map"}, pp={"id": "b"}))["statusCode"] == 409
    r = h.handler(_evt("GET", "/api/resolve/road-map", pp={"alias": "road-map"}))
    assert r["statusCode"] == 200 and json.loads(r["body"])["deckId"] == "a"
    assert h.handler(_evt("GET", "/api/resolve/none", pp={"alias": "none"}))["statusCode"] == 404


@mock_aws
def test_alias_empty_string_rejected(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    repo.put(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"))
    # Empty string must not be accepted (would slugify to "deck").
    r = h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": ""}, pp={"id": "a"}))
    assert r["statusCode"] == 400
    assert repo.get("a").get("alias") is None
    # Whitespace-only must also 400.
    r = h.handler(_evt("PUT", "/api/decks/a/alias", {"alias": "   "}, pp={"id": "a"}))
    assert r["statusCode"] == 400
    assert repo.get("a").get("alias") is None
