import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "thumbnail"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import importlib.util
import boto3
import pytest
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def _load_thumbnail_handler():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "thumbnail", "handler.py")
    spec = importlib.util.spec_from_file_location("thumbnail_handler", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_key():
    t = _load_thumbnail_handler()
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
    t = _load_thumbnail_handler()
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


@mock_aws
def test_handler_fills_pending_version_thumbnail(monkeypatch):
    """When the API has already recorded a pending version (thumbnailKey=None),
    the thumbnail Lambda fills the existing record rather than creating a new
    one (which would clobber createdAt)."""
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
    s3.put_object(Bucket=BUCKET, Key="slides/beta/v1/index.html", Body=b"<html>b</html>")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    t = _load_thumbnail_handler()
    monkeypatch.setattr(t, "capture_png", lambda html: b"\x89PNG")
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_pending_version
    repo = DeckRepo(TABLE, res)
    # Simulate what the API POST now writes: a pending version.
    item = add_pending_version(new_deck_item("beta", "Beta", [], "t0"), 1, "t1")
    repo.put(item)
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": "slides/beta/v1/index.html"}}}]}
    t.handler(event)
    got = repo.get("beta")
    v1 = next(v for v in got["versions"] if v["n"] == 1)
    assert v1["thumbnailKey"] == "thumbnails/beta/v1.png"
    assert v1["sizeBytes"] == len(b"<html>b</html>")
    assert v1["createdAt"] == "t1"  # preserved from pending record


@mock_aws
def test_handler_respects_parsed_version_out_of_order(monkeypatch):
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
    s3.put_object(Bucket=BUCKET, Key="slides/roadmap/v3/index.html", Body=b"<html>v3</html>")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    t = _load_thumbnail_handler()
    monkeypatch.setattr(t, "capture_png", lambda html: b"\x89PNG_fake")
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_version
    repo = DeckRepo(TABLE, res)
    # deck already at currentVersion=1; a v3 event arrives out of order
    item = add_version(new_deck_item("roadmap", "Roadmap", [], "t0"), "thumbnails/roadmap/v1.png", 10, "t1")
    repo.put(item)
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": "slides/roadmap/v3/index.html"}}}]}
    t.handler(event)
    got = repo.get("roadmap")
    assert got["currentVersion"] == 3
    v3 = next(v for v in got["versions"] if v["n"] == 3)
    assert v3["thumbnailKey"] == "thumbnails/roadmap/v3.png"
    assert s3.get_object(Bucket=BUCKET, Key="thumbnails/roadmap/v3.png")["Body"].read() == b"\x89PNG_fake"
