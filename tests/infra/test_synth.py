import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template, Match
from slidecast.slidecast_stack import SlidecastStack


def _template():
    app = App()
    stack = SlidecastStack(app, "TestStack", env={"account": "111111111111", "region": "us-east-1"})
    return Template.from_stack(stack)


def test_has_private_bucket():
    t = _template()
    t.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        }
    })


def test_dynamodb_has_gsi():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "GlobalSecondaryIndexes": Match.array_with([
            Match.object_like({"IndexName": "byUpdatedAt"}),
        ]),
    })


def test_cognito_self_signup_disabled():
    t = _template()
    t.has_resource_properties("AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
    })


def test_cognito_hosted_ui_domain_exists():
    t = _template()
    assert t.find_resources("AWS::Cognito::UserPoolDomain") != {}


def test_api_routes_have_explicit_id_param():
    t = _template()
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    keys = [r["Properties"].get("RouteKey", "") for r in routes.values()]
    assert any("/api/decks/{id}" in k for k in keys), keys
    assert any(k.endswith("/api/decks") for k in keys), keys
    assert any("/api/decks/{id}/current" in k for k in keys), keys
    assert any("/api/decks/{id}/restore" in k for k in keys), keys


def test_dynamodb_table_name_is_fixed():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::Table", {"TableName": "SlideDecks"})


def test_thumbnail_is_container_image():
    t = _template()
    fns = t.find_resources("AWS::Lambda::Function")
    pkg_types = [f["Properties"].get("PackageType") for f in fns.values()]
    assert "Image" in pkg_types, pkg_types


def test_bucket_has_cors():
    t = _template()
    buckets = t.find_resources("AWS::S3::Bucket")
    assert any("CorsConfiguration" in b["Properties"] for b in buckets.values()), buckets


def test_no_public_ingress_alb():
    t = _template()
    assert t.find_resources("AWS::ElasticLoadBalancingV2::LoadBalancer") == {}
    assert t.find_resources("AWS::EC2::SecurityGroup") == {}
