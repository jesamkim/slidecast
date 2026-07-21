import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill", "slidecast-append"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, tempfile
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


@mock_aws
def test_append_then_update_increments_version():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    with tempfile.NamedTemporaryFile(suffix="=roadmap.html", delete=False) as f:
        f.write(b"<html>deck</html>"); path = f.name
    import shutil
    named = os.path.join(tempfile.gettempdir(), "roadmap.html")
    shutil.copy(path, named)
    stub = lambda html: b"PNG"
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    repo = DeckRepo(TABLE, res)
    assert repo.get("roadmap")["currentVersion"] == 1
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    assert repo.get("roadmap")["currentVersion"] == 2
    assert s3.get_object(Bucket=BUCKET, Key="slides/roadmap/v2/index.html")


@mock_aws
def test_append_after_rollback_is_monotonic():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm
    named = os.path.join(tempfile.gettempdir(), "beta.html")
    open(named, "wb").write(b"<html>b</html>")
    stub = lambda html: b"PNG"
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)  # v1
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)  # v2
    repo = DeckRepo(TABLE, res)
    # Roll currentVersion back to v1.
    repo.put(dm.set_current(repo.get("beta"), 1, "t"))
    assert repo.get("beta")["currentVersion"] == 1
    # Next append must land on v3, not overwrite v2.
    _, n = sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=stub)
    assert n == 3
    item = repo.get("beta")
    ns = sorted(v["n"] for v in item["versions"])
    assert ns == [1, 2, 3]


@mock_aws
def test_soft_and_hard_delete():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import shutil, tempfile
    named = os.path.join(tempfile.gettempdir(), "gamma.html")
    open(named, "wb").write(b"<html>g</html>")
    sa.append(named, TABLE, BUCKET, dynamodb=res, s3=s3, capture=lambda h: b"P")
    repo = DeckRepo(TABLE, res)
    sa.soft_delete("gamma", TABLE, dynamodb=res)
    assert repo.get("gamma")["status"] == "archived"
    sa.hard_delete("gamma", TABLE, BUCKET, dynamodb=res, s3=s3)
    assert repo.get("gamma") is None
