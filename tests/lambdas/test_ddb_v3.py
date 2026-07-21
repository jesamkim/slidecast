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
    assert repo.reserve_public("tok", "deckB", 1, "t2") is False
    repo.release_public("tok")
    assert repo.reserve_public("tok", "deckB", 1, "t3") is True

@mock_aws
def test_public_reservation_not_in_gsis():
    res = boto3.resource("dynamodb", region_name="us-east-1"); _make(res)
    repo = DeckRepo(TABLE, res)
    repo.reserve_public("tok", "deckA", 1, "t1")
    assert repo.query_by_alias("tok") is None
    assert repo.get(dm.public_pk("tok"))["ownerDeckId"] == "deckA"
