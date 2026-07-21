import aws_cdk as cdk
from slidecast.slidecast_stack import SlidecastStack

app = cdk.App()
SlidecastStack(
    app, "SlidecastStack",
    env=cdk.Environment(account="123456789012", region="us-east-1"),
)
app.synth()
