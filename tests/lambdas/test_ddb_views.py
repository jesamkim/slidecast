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
            {"IndexName": "byUpdatedAt", "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "byAlias", "KeySchema": [
                {"AttributeName": "alias", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

@mock_aws
def test_increment_and_get_views():
    res = boto3.resource("dynamodb", region_name="us-east-1"); _make(res)
    repo = DeckRepo(TABLE, res)
    repo.reserve_public("tok", "deckA", 1, "2026-07-21T00:00:00Z")
    repo.increment_views("tok", "2026-07-21")
    repo.increment_views("tok", "2026-07-21")
    repo.increment_views("tok", "2026-07-22")
    v = repo.get_views("tok")
    assert v["total"] == 3
    assert v["byDay"]["2026-07-21"] == 2
    assert v["byDay"]["2026-07-22"] == 1

@mock_aws
def test_get_views_empty():
    res = boto3.resource("dynamodb", region_name="us-east-1"); _make(res)
    repo = DeckRepo(TABLE, res)
    repo.reserve_public("tok", "deckA", 1, "t")
    v = repo.get_views("tok")
    assert v["total"] == 0 and v["byDay"] == {}
