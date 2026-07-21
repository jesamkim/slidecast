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


def test_spa_fallback_via_cloudfront_function():
    """SPA deep-link fallback is implemented via a CloudFront Function on the
    default (S3) behavior only, NOT via distribution-level CustomErrorResponses
    (which would remap /api/* 4xx into index.html+200 and mask real API errors).
    """
    t = _t()

    # A CloudFront Function resource must exist.
    fns = t.find_resources("AWS::CloudFront::Function")
    assert fns, "expected a CloudFront Function for SPA rewrite"
    # And its code should route non-/api extension-less paths to /index.html.
    code_blobs = [
        f["Properties"]["FunctionCode"] for f in fns.values()
    ]
    assert any("/index.html" in c and "/api/" in c for c in code_blobs), (
        "CloudFront Function code should guard /api and rewrite to /index.html"
    )

    # The distribution's DEFAULT behavior must associate the function as
    # viewer-request. The /api/* additional behavior must NOT.
    t.has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": Match.object_like({
            "DefaultCacheBehavior": Match.object_like({
                "FunctionAssociations": Match.array_with([
                    Match.object_like({"EventType": "viewer-request"}),
                ]),
            }),
        }),
    })

    # Distribution-level CustomErrorResponses SPA remap (403/404 -> /index.html)
    # must be gone; otherwise API 404s get masked.
    dists = t.find_resources("AWS::CloudFront::Distribution")
    for d in dists.values():
        cers = d["Properties"]["DistributionConfig"].get("CustomErrorResponses", [])
        for cer in cers:
            if cer.get("ResponsePagePath") == "/index.html":
                assert False, "distribution-level SPA CustomErrorResponses must be removed"
