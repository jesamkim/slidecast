import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))

from aws_cdk import App
from aws_cdk.assertions import Template, Match
from slidecast.slidecast_stack import SlidecastStack


def _t():
    app = App()
    return Template.from_stack(
        SlidecastStack(app, "T", env={"account": "123456789012", "region": "us-east-1"})
    )


def test_byalias_gsi():
    _t().has_resource_properties("AWS::DynamoDB::Table", {
        "GlobalSecondaryIndexes": Match.array_with([
            Match.object_like({"IndexName": "byAlias"}),
        ]),
    })


def test_alias_route_exists():
    routes = _t().find_resources("AWS::ApiGatewayV2::Route")
    keys = [r["Properties"]["RouteKey"] for r in routes.values()]
    assert any("/api/resolve/{alias}" in k for k in keys)
    assert any("/api/groups" in k for k in keys)
    assert any("/group" in k for k in keys)


def test_spa_fallback_error_responses():
    _t().has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": Match.object_like({
            "CustomErrorResponses": Match.array_with([
                Match.object_like({
                    "ErrorCode": 403,
                    "ResponseCode": 200,
                    "ResponsePagePath": "/index.html",
                }),
                Match.object_like({
                    "ErrorCode": 404,
                    "ResponseCode": 200,
                    "ResponsePagePath": "/index.html",
                }),
            ]),
        }),
    })
