import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "thumbnail"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import importlib.util
import boto3
from moto import mock_aws

TABLE = "SlideDecks"
BUCKET = "slidecast-test"


def _load_thumbnail_handler():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "thumbnail", "handler.py")
    spec = importlib.util.spec_from_file_location("thumbnail_handler_v3", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _create_table(res):
    res.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "deckId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
            {"AttributeName": "aliasPk", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "deckId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "byUpdatedAt",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "updatedAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "byAlias",
                "KeySchema": [
                    {"AttributeName": "aliasPk", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_handler_generates_pdf_alongside_thumbnail(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _create_table(res)
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key="slides/roadmap/v1/index.html", Body=b"<html>d</html>")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    t = _load_thumbnail_handler()
    monkeypatch.setattr(t, "capture_png", lambda html: b"\x89PNG_fake")
    monkeypatch.setattr(t, "capture_pdf", lambda html: b"%PDF-fake")
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_pending_version
    repo = DeckRepo(TABLE, res)
    item = add_pending_version(new_deck_item("roadmap", "Roadmap", [], "t0"), 1, "t1")
    repo.put(item)
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": "slides/roadmap/v1/index.html"}}}]}
    t.handler(event)

    assert s3.get_object(Bucket=BUCKET, Key="thumbnails/roadmap/v1.png")["Body"].read() == b"\x89PNG_fake"
    pdf_obj = s3.get_object(Bucket=BUCKET, Key="pdfs/roadmap/v1.pdf")
    assert pdf_obj["Body"].read() == b"%PDF-fake"
    assert pdf_obj["ContentType"] == "application/pdf"

    got = repo.get("roadmap")
    v1 = next(v for v in got["versions"] if v["n"] == 1)
    assert v1["thumbnailKey"] == "thumbnails/roadmap/v1.png"
    assert v1["pdfKey"] == "pdfs/roadmap/v1.pdf"


@mock_aws
def test_handler_pdf_generation_is_idempotent(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _create_table(res)
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key="slides/beta/v1/index.html", Body=b"<html>b</html>")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    t = _load_thumbnail_handler()
    monkeypatch.setattr(t, "capture_png", lambda html: b"\x89PNG")
    monkeypatch.setattr(t, "capture_pdf", lambda html: b"%PDF")
    from ddb import DeckRepo
    from deck_model import new_deck_item, add_pending_version
    repo = DeckRepo(TABLE, res)
    item = add_pending_version(new_deck_item("beta", "Beta", [], "t0"), 1, "t1")
    repo.put(item)
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": "slides/beta/v1/index.html"}}}]}
    t.handler(event)
    t.handler(event)
    got = repo.get("beta")
    versions_at_1 = [v for v in got["versions"] if v["n"] == 1]
    assert len(versions_at_1) == 1
    assert versions_at_1[0]["pdfKey"] == "pdfs/beta/v1.pdf"
    assert versions_at_1[0]["thumbnailKey"] == "thumbnails/beta/v1.png"
