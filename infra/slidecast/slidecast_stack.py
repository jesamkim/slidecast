import os

from aws_cdk import (
    Stack, RemovalPolicy, Duration, CfnOutput,
    aws_s3 as s3,
    aws_dynamodb as ddb,
    aws_cognito as cognito,
    aws_lambda as lambda_,
    aws_s3_notifications as s3n,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_apigatewayv2_authorizers as authorizers,
    aws_cloudfront as cf,
    aws_cloudfront_origins as origins,
)
from constructs import Construct


class SlidecastStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        shared_layer_path = os.path.join(repo_root, "shared_layer")
        api_asset_path = os.path.join(repo_root, "lambdas", "api")
        thumb_asset_path = os.path.join(repo_root, "lambdas", "thumbnail")

        bucket = s3.Bucket(
            self, "AssetsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        table = ddb.Table(
            self, "SlideDecks",
            table_name="SlideDecks",
            partition_key=ddb.Attribute(name="deckId", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="byUpdatedAt",
            partition_key=ddb.Attribute(name="status", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="updatedAt", type=ddb.AttributeType.STRING),
        )

        user_pool = cognito.UserPool(
            self, "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        user_pool_client = user_pool.add_client(
            "WebClient",
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            ),
            generate_secret=False,
        )

        # Hosted UI domain. Prefix must be globally unique per region; account id
        # is used to keep it stable across redeploys. Callback URLs for the client
        # are intentionally left unset here because the CloudFront domain is not
        # known at synth time; configure them post-deploy via the AWS console or
        # a follow-up script once DistributionDomain is available.
        user_pool_domain = user_pool.add_domain(
            "HostedUiDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"slidecast-{self.account}",
            ),
        )

        shared_layer = lambda_.LayerVersion(
            self, "SharedLayer",
            code=lambda_.Code.from_asset(shared_layer_path),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
        )

        api_fn = lambda_.Function(
            self, "ApiFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(api_asset_path),
            layers=[shared_layer],
            timeout=Duration.seconds(15),
            environment={"TABLE_NAME": table.table_name, "BUCKET_NAME": bucket.bucket_name},
        )
        table.grant_read_write_data(api_fn)
        bucket.grant_read_write(api_fn)

        thumb_fn = lambda_.Function(
            self, "ThumbFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(thumb_asset_path),
            layers=[shared_layer],
            memory_size=2048,
            timeout=Duration.seconds(60),
            environment={"TABLE_NAME": table.table_name, "BUCKET_NAME": bucket.bucket_name},
        )
        table.grant_read_write_data(thumb_fn)
        bucket.grant_read_write(thumb_fn)
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(thumb_fn),
            s3.NotificationKeyFilter(prefix="slides/", suffix="index.html"),
        )

        authorizer = authorizers.HttpJwtAuthorizer(
            "JwtAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            identity_source=["$request.header.Authorization"],
            jwt_audience=[user_pool_client.user_pool_client_id],
        )
        http_api = apigw.HttpApi(self, "HttpApi", default_authorizer=authorizer)
        api_integration = integrations.HttpLambdaIntegration("ApiInt", api_fn)
        # Register explicit routes so API Gateway populates pathParameters
        # with the `id` key. A single {proxy+} catch-all would only ever
        # expose pathParameters["proxy"], causing every per-deck route to
        # 404 in the handler.
        for route_path in (
            "/api/decks",
            "/api/decks/{id}",
            "/api/decks/{id}/current",
            "/api/decks/{id}/restore",
        ):
            http_api.add_routes(
                path=route_path,
                methods=[apigw.HttpMethod.ANY],
                integration=api_integration,
            )

        oac = cf.S3OriginAccessControl(self, "Oac")
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(bucket, origin_access_control=oac)
        api_domain = f"{http_api.api_id}.execute-api.{self.region}.amazonaws.com"
        distribution = cf.Distribution(
            self, "Cdn",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=origins.HttpOrigin(api_domain),
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
        )

        CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "CognitoDomain", value=user_pool_domain.domain_name)
