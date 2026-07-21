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
