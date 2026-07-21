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


@mock_aws
def test_reserve_alias_atomic():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make(res)
    repo = DeckRepo(TABLE, res)
    assert repo.reserve_alias("road", "a", "t") is True
    # Same alias, second writer loses.
    assert repo.reserve_alias("road", "b", "t") is False
    # Release then re-reserve.
    repo.release_alias("road")
    assert repo.reserve_alias("road", "b", "t") is True
    # Idempotent release.
    repo.release_alias("nonexistent")


@mock_aws
def test_reservation_not_visible_in_byalias_gsi():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make(res)
    repo = DeckRepo(TABLE, res)
    # Reservation must NOT carry the `alias` attribute -> stays out of GSI.
    repo.reserve_alias("road", "a", "t")
    assert repo.query_by_alias("road") is None
    # Deck with alias attribute is discoverable.
    d = set_alias(add_version(new_deck_item("a", "A", [], "t"), "k", 1, "t1"), "road", "t2")
    repo.put(d)
    assert repo.query_by_alias("road")["deckId"] == "a"


@mock_aws
def test_list_by_status_accumulates_all_pages():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    _make(res)
    repo = DeckRepo(TABLE, res)
    for i in range(3):
        repo.put(add_version(new_deck_item(f"d{i}", "T", [], f"t{i}"), "k", 1, f"t{i}"))
    assert len(repo.list_by_status("active")) == 3


def test_list_by_status_paginates_lek(monkeypatch):
    repo = DeckRepo.__new__(DeckRepo)

    class T:
        def __init__(self):
            self.calls = 0

        def query(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert "ExclusiveStartKey" not in kwargs
                return {"Items": [{"deckId": "p1"}], "LastEvaluatedKey": {"k": "1"}}
            assert kwargs["ExclusiveStartKey"] == {"k": "1"}
            return {"Items": [{"deckId": "p2"}]}

    repo._table = T()
    items = repo.list_by_status("active")
    assert [i["deckId"] for i in items] == ["p1", "p2"]


def test_list_groups_paginates_lek():
    repo = DeckRepo.__new__(DeckRepo)

    class T:
        def __init__(self):
            self.calls = 0

        def scan(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert "ExclusiveStartKey" not in kwargs
                return {"Items": [{"groupId": "g1"}], "LastEvaluatedKey": {"k": "1"}}
            assert kwargs["ExclusiveStartKey"] == {"k": "1"}
            return {"Items": [{"groupId": "g2"}]}

    repo._table = T()
    items = repo.list_groups()
    assert [i["groupId"] for i in items] == ["g1", "g2"]
