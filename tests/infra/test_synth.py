import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
from aws_cdk import App
from aws_cdk.assertions import Template
from slidecast.slidecast_stack import SlidecastStack


def _template():
    app = App()
    stack = SlidecastStack(app, "TestStack", env={"account": "123456789012", "region": "us-east-1"})
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
        "GlobalSecondaryIndexes": [{"IndexName": "byUpdatedAt"}],
    })


def test_cognito_self_signup_disabled():
    t = _template()
    t.has_resource_properties("AWS::Cognito::UserPool", {
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
    })


def test_cognito_hosted_ui_domain_exists():
    t = _template()
    assert t.find_resources("AWS::Cognito::UserPoolDomain") != {}


def test_no_public_ingress_alb():
    t = _template()
    assert t.find_resources("AWS::ElasticLoadBalancingV2::LoadBalancer") == {}
    assert t.find_resources("AWS::EC2::SecurityGroup") == {}
