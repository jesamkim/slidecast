import os

# Ensure moto-mocked AWS clients resolve to us-east-1 regardless of local AWS profile.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ.pop("AWS_PROFILE", None)
