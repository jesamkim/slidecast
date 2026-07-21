import os

import aws_cdk as cdk
from slidecast.slidecast_stack import SlidecastStack

app = cdk.App()
# Account/region come from the environment so the stack is not tied to a
# specific AWS account in source. `cdk deploy` sets CDK_DEFAULT_ACCOUNT from
# the active credentials; AWS_REGION/CDK_DEFAULT_REGION default to us-east-1.
account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = (
    os.environ.get("AWS_REGION")
    or os.environ.get("CDK_DEFAULT_REGION")
    or "us-east-1"
)
SlidecastStack(
    app, "SlidecastStack",
    env=cdk.Environment(account=account, region=region),
)
app.synth()
