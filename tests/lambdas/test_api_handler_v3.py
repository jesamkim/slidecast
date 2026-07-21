import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import boto3, importlib
from moto import mock_aws

TABLE, BUCKET = "SlideDecks", "slidecast-test"


def _setup(res, s3):
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


def _evt(method, path, body=None, pp=None, qs=None):
    return {"requestContext": {"http": {"method": method, "path": path}},
            "rawPath": path, "pathParameters": pp or {},
            "queryStringParameters": qs or {},
            "body": json.dumps(body) if body is not None else None}


def _seed(res, s3, deck_id="a", title="Title", n=1):
    from ddb import DeckRepo
    import deck_model as dm
    repo = DeckRepo(TABLE, res)
    item = dm.new_deck_item(deck_id, title, [], "t0")
    item = dm.add_pending_version(item, n, "t1")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key(deck_id, n),
                  Body=b"<html>hi</html>", ContentType="text/html")
    return repo


@mock_aws
def test_share_creates_token_copies_html_and_public_resolve(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    repo = _seed(res, s3)

    r = h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    token = body["token"]
    assert token and body["url"] == f"/p/{token}"
    assert repo.get("a")["publicToken"] == token

    obj = s3.get_object(Bucket=BUCKET, Key=f"public/{token}/index.html")
    assert obj["Body"].read() == b"<html>hi</html>"

    r2 = h.handler(_evt("GET", f"/api/public/{token}", pp={"token": token}))
    assert r2["statusCode"] == 200
    pub = json.loads(r2["body"])
    assert pub == {"title": "Title", "htmlUrl": f"/public/{token}/index.html"}
    assert "deckId" not in pub and "versions" not in pub


@mock_aws
def test_share_is_idempotent(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    _seed(res, s3)
    t1 = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    t2 = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    assert t1 == t2


@mock_aws
def test_unshare_and_reshare_new_token(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    from ddb import DeckRepo
    repo = DeckRepo(TABLE, res)
    _seed(res, s3)
    t1 = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]

    r = h.handler(_evt("DELETE", "/api/decks/a/share", pp={"id": "a"}))
    assert r["statusCode"] == 200
    assert repo.get("a").get("publicToken") is None
    listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"public/{t1}/")
    assert listed.get("KeyCount", 0) == 0
    assert h.handler(_evt("GET", f"/api/public/{t1}", pp={"token": t1}))["statusCode"] == 404

    t2 = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    assert t2 != t1


@mock_aws
def test_public_bad_token_404(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    assert h.handler(_evt("GET", "/api/public/badtoken", pp={"token": "badtoken"}))["statusCode"] == 404


@mock_aws
def test_republish_copies_current_version(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    import deck_model as dm
    from ddb import DeckRepo
    repo = _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    # Add v2 and set current
    item = repo.get("a")
    item = dm.add_pending_version(item, 2, "t2")
    repo.put(item)
    s3.put_object(Bucket=BUCKET, Key=dm.slide_key("a", 2),
                  Body=b"<html>v2</html>", ContentType="text/html")
    r = h.handler(_evt("POST", "/api/decks/a/share/republish", pp={"id": "a"}))
    assert r["statusCode"] == 200
    assert s3.get_object(Bucket=BUCKET, Key=f"public/{tok}/index.html")["Body"].read() == b"<html>v2</html>"
    # reservation publicVersion updated to current version (unconditional put)
    assert repo.get(dm.public_pk(tok))["publicVersion"] == 2

    # republish without share -> 400
    _seed(res, s3, deck_id="b", title="B")
    assert h.handler(_evt("POST", "/api/decks/b/share/republish", pp={"id": "b"}))["statusCode"] == 400


@mock_aws
def test_download_html_and_pdf(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    import deck_model as dm
    from ddb import DeckRepo
    repo = _seed(res, s3)

    r = h.handler(_evt("GET", "/api/decks/a/download", pp={"id": "a"}, qs={"format": "html"}))
    assert r["statusCode"] == 200
    url = json.loads(r["body"])["downloadUrl"]
    assert isinstance(url, str) and BUCKET in url and "slides/a/v1/index.html" in url

    r = h.handler(_evt("GET", "/api/decks/a/download", pp={"id": "a"}, qs={"format": "pdf"}))
    assert r["statusCode"] == 409

    item = repo.get("a")
    item = dm.set_version_pdf(item, 1, "pdfs/a/v1.pdf", "t2")
    repo.put(item)
    r = h.handler(_evt("GET", "/api/decks/a/download", pp={"id": "a"}, qs={"format": "pdf"}))
    assert r["statusCode"] == 200
    pdf_url = json.loads(r["body"])["downloadUrl"]
    assert "pdfs/a/v1.pdf" in pdf_url


@mock_aws
def test_hard_delete_cleans_public_and_pdfs(monkeypatch):
    res = boto3.resource("dynamodb", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    _setup(res, s3)
    monkeypatch.setenv("TABLE_NAME", TABLE); monkeypatch.setenv("BUCKET_NAME", BUCKET)
    import handler as h; importlib.reload(h)
    import deck_model as dm
    from ddb import DeckRepo
    repo = _seed(res, s3)
    tok = json.loads(h.handler(_evt("PUT", "/api/decks/a/share", pp={"id": "a"}))["body"])["token"]
    s3.put_object(Bucket=BUCKET, Key=f"pdfs/a/v1.pdf", Body=b"%PDF")
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix=f"public/{tok}/").get("KeyCount", 0) == 1
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="pdfs/a/").get("KeyCount", 0) == 1

    r = h.handler(_evt("DELETE", "/api/decks/a", pp={"id": "a"}, qs={"hard": "true"}))
    assert r["statusCode"] == 200
    assert repo.get("a") is None
    assert repo.get(dm.public_pk(tok)) is None
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix=f"public/{tok}/").get("KeyCount", 0) == 0
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="pdfs/a/").get("KeyCount", 0) == 0
