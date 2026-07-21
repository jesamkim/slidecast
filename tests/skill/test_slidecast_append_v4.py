import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill", "slidecast-append"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import boto3
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


class _StubPaginatingS3:
    def __init__(self, real, page_size=2):
        self._real = real
        self._page_size = page_size
        self.delete_calls = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def list_objects_v2(self, **kwargs):
        token = kwargs.pop("ContinuationToken", None)
        resp = self._real.list_objects_v2(**kwargs)
        contents = resp.get("Contents", [])
        if token is not None:
            contents = [o for o in contents if o["Key"] > token]
        page = contents[:self._page_size]
        out = {"Contents": page}
        if len(contents) > self._page_size:
            out["IsTruncated"] = True
            out["NextContinuationToken"] = page[-1]["Key"]
        return out

    def delete_objects(self, **kwargs):
        self.delete_calls += 1
        return self._real.delete_objects(**kwargs)


@mock_aws
def test_delete_prefix_paginates_and_deletes_all():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa

    for i in range(5):
        s3.put_object(Bucket=BUCKET, Key=f"public/tok/f{i}", Body=b"x")

    stub = _StubPaginatingS3(s3, page_size=2)
    sa._delete_prefix(stub, BUCKET, "public/tok/")
    remaining = s3.list_objects_v2(Bucket=BUCKET, Prefix="public/tok/").get("Contents", [])
    assert remaining == []
    assert stub.delete_calls == 3


@mock_aws
def test_share_copy_uses_no_cache_headers():
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _mk(res, s3)
    import slidecast_append as sa
    from ddb import DeckRepo
    import deck_model as dm

    repo = DeckRepo(TABLE, res)
    deck_id = "d1"
    item = dm.new_deck_item(deck_id, "T", [], "t0")
    item = dm.add_pending_version(item, 1, "t1")
    item = dm.upsert_version(item, 1, dm.thumb_key(deck_id, 1), 100, "t2")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key(deck_id, 1), Body=b"<html>x</html>",
                  ContentType="text/html")

    path = sa.share(deck_id, table=TABLE, bucket=BUCKET, dynamodb=res, s3=s3)
    token = path.rsplit("/", 1)[-1]
    obj = s3.get_object(Bucket=BUCKET, Key=f"public/{token}/index.html")
    assert "no-cache" in obj.get("CacheControl", "")
    assert "no-store" in obj["CacheControl"]
