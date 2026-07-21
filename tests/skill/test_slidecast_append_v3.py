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


def _keys(s3, prefix: str) -> list:
    listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in listed.get("Contents", [])]


@mock_aws
def test_share_returns_public_path_and_copies_current_version():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo

    stub = lambda html: b"PNG"
    sa.append(_write("d1.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    path = sa.share("d1", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert path.startswith("/p/")
    token = path[len("/p/"):]
    assert token
    repo = DeckRepo(TABLE, res)
    deck = repo.get("d1")
    assert deck.get("publicToken") == token
    assert _keys(s3, f"public/{token}/") == [f"public/{token}/index.html"]


@mock_aws
def test_share_idempotent_returns_same_token():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa

    stub = lambda html: b"PNG"
    sa.append(_write("d2.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    p1 = sa.share("d2", TABLE, BUCKET, dynamodb=res, s3=s3)
    p2 = sa.share("d2", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert p1 == p2


@mock_aws
def test_unshare_clears_token_and_deletes_public_prefix():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm

    stub = lambda html: b"PNG"
    sa.append(_write("d3.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    path = sa.share("d3", TABLE, BUCKET, dynamodb=res, s3=s3)
    token = path[len("/p/"):]
    sa.unshare("d3", TABLE, BUCKET, dynamodb=res, s3=s3)
    repo = DeckRepo(TABLE, res)
    assert repo.get("d3").get("publicToken") is None
    assert _keys(s3, f"public/{token}/") == []
    # reservation released
    assert repo.get(dm.public_pk(token)) is None


@mock_aws
def test_share_after_unshare_issues_new_token():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa

    stub = lambda html: b"PNG"
    sa.append(_write("d4.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    p1 = sa.share("d4", TABLE, BUCKET, dynamodb=res, s3=s3)
    sa.unshare("d4", TABLE, BUCKET, dynamodb=res, s3=s3)
    p2 = sa.share("d4", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert p1 != p2


@mock_aws
def test_hard_delete_shared_deck_with_pdf_removes_public_and_pdfs():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm

    stub = lambda html: b"PNG"
    sa.append(_write("d5.html"), TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    path = sa.share("d5", TABLE, BUCKET, dynamodb=res, s3=s3)
    token = path[len("/p/"):]
    # Simulate a pdf uploaded for this deck
    s3.put_object(Bucket=BUCKET, Key=dm.pdf_key("d5", 1), Body=b"%PDF", ContentType="application/pdf")
    assert _keys(s3, "pdfs/d5/") != []

    sa.hard_delete("d5", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert _keys(s3, "slides/d5/") == []
    assert _keys(s3, "thumbnails/d5/") == []
    assert _keys(s3, "pdfs/d5/") == []
    assert _keys(s3, f"public/{token}/") == []
    repo = DeckRepo(TABLE, res)
    assert repo.get(dm.public_pk(token)) is None
    assert repo.get("d5") is None
