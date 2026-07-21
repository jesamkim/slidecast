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
def test_views_returns_total_and_by_day_for_shared_deck():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo

    stub = lambda html: b"PNG"
    sa.append(_write("dv1.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    path = sa.share("dv1", TABLE, BUCKET, dynamodb=res, s3=s3)
    token = path[len("/p/"):]

    repo = DeckRepo(TABLE, res)
    repo.increment_views(token, "2026-07-20")
    repo.increment_views(token, "2026-07-20")
    repo.increment_views(token, "2026-07-21")

    stats = sa.views("dv1", TABLE, dynamodb=res)
    assert stats == {"total": 3, "byDay": {"2026-07-20": 2, "2026-07-21": 1}}


@mock_aws
def test_views_unshared_deck_returns_zero():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa

    stub = lambda html: b"PNG"
    sa.append(_write("dv2.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)

    stats = sa.views("dv2", TABLE, dynamodb=res)
    assert stats == {"total": 0, "byDay": {}}


@mock_aws
def test_views_missing_deck_returns_zero():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa

    stats = sa.views("nope", TABLE, dynamodb=res)
    assert stats == {"total": 0, "byDay": {}}
