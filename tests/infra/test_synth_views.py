import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template
from slidecast.slidecast_stack import SlidecastStack

def test_views_routes_exist():
    app = App()
    t = Template.from_stack(SlidecastStack(app, "T", env={"account": "111111111111", "region": "us-east-1"}))
    keys = [r["Properties"]["RouteKey"] for r in t.find_resources("AWS::ApiGatewayV2::Route").values()]
    assert any(k.startswith("GET ") and k.endswith("/api/decks/{id}/views") for k in keys)
    assert any(k.startswith("GET ") and k.endswith("/api/decks/{id}/views/export") for k in keys)
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    none_routes = [r["Properties"]["RouteKey"] for r in routes.values()
                   if r["Properties"].get("AuthorizationType", "NONE") == "NONE"]
    assert none_routes == [k for k in none_routes if "/api/public/{token}" in k]
