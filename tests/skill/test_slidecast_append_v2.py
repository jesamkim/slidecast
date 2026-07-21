import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill", "slidecast-append"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import boto3
import pytest
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def _mk(res, s3):
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


def _write(name: str, body: bytes = b"<html>d</html>") -> str:
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "wb") as f:
        f.write(body)
    return path


@mock_aws
def test_append_with_group_auto_creates_and_sets_alias():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm

    path = _write("roadmap.html")
    stub = lambda html: b"PNG"
    sa.append(path, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub,
              group="Marketing Team", alias="road")
    repo = DeckRepo(TABLE, res)
    deck = repo.get("roadmap")
    assert deck["group"] == "marketing-team"
    assert deck["alias"] == "road"
    grp = repo.get(dm.group_pk("marketing-team"))
    assert grp is not None
    assert grp["name"] == "Marketing Team"
    assert grp["type"] == "group"


@mock_aws
def test_append_alias_conflict_raises():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    stub = lambda html: b"PNG"

    p1 = _write("first.html")
    p2 = _write("second.html")
    sa.append(p1, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub, alias="road")
    with pytest.raises(SystemExit):
        sa.append(p2, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub, alias="road")


@mock_aws
def test_append_reserved_alias_raises():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    stub = lambda html: b"PNG"
    path = _write("thing.html")
    with pytest.raises(SystemExit):
        sa.append(path, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub, alias="api")


@mock_aws
def test_new_group_and_del_group_reassigns_members():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm

    stub = lambda html: b"PNG"
    gid = sa.new_group("Engineering", TABLE, dynamodb=res)
    assert gid == "engineering"
    repo = DeckRepo(TABLE, res)
    assert repo.get(dm.group_pk("engineering"))["name"] == "Engineering"

    path = _write("plan.html")
    sa.append(path, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub, group="Engineering")
    assert repo.get("plan")["group"] == "engineering"

    sa.del_group("engineering", TABLE, dynamodb=res)
    assert repo.get(dm.group_pk("engineering")) is None
    # Member deck reassigned to no group (None stripped by repo.put).
    plan = repo.get("plan")
    assert plan.get("group") is None
