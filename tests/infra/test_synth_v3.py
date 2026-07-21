import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template
from slidecast.slidecast_stack import SlidecastStack


def _routes():
    app = App()
    t = Template.from_stack(SlidecastStack(app, "T", env={"account": "123456789012", "region": "us-east-1"}))
    return [r["Properties"]["RouteKey"] for r in t.find_resources("AWS::ApiGatewayV2::Route").values()], t


def test_share_download_public_routes_exist():
    keys, _ = _routes()
    assert any("/api/decks/{id}/share" in k for k in keys)
    assert any("/api/decks/{id}/download" in k for k in keys)
    assert any("GET /api/public/{token}" in k for k in keys)


def test_public_route_has_no_jwt_authorizer():
    keys, t = _routes()
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    pub = [r for r in routes.values() if "/api/public/{token}" in r["Properties"]["RouteKey"]]
    assert pub, "public route missing"
    props = pub[0]["Properties"]
    assert props.get("AuthorizationType", "NONE") == "NONE"
