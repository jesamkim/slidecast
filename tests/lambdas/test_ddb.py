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
