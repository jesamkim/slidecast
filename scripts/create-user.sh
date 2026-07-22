#!/usr/bin/env bash
set -euo pipefail

# Uses the caller's AWS credentials (set AWS_PROFILE to target a profile,
# or rely on the default chain). Region defaults to us-east-1.
export AWS_REGION="${AWS_REGION:-us-east-1}"

EMAIL="${1:?usage: create-user.sh <email>}"

OUTPUTS="$(dirname "$0")/../cdk-outputs.json"
POOL_ID=$(python3 -c "import json,sys;print(json.load(open('$OUTPUTS'))['SlidecastStack']['UserPoolId'])")

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true

echo "User created. A temporary password will be emailed to $EMAIL."
