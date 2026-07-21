#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE=profile2
export AWS_REGION=us-east-1

cd "$(dirname "$0")/.."

# 1) Build shared layer + copy shared modules into thumbnail lambda.
# These steps MUST run before cdk synth/deploy because the stack reads
# these paths as CDK assets.
mkdir -p shared_layer/python
cp shared/deck_model.py shared_layer/python/deck_model.py
cp lambdas/api/ddb.py lambdas/thumbnail/ddb.py
cp lambdas/api/slug.py lambdas/thumbnail/slug.py 2>/dev/null || true

# 2) CDK deploy.
cd infra
python3 -m pip install -r requirements.txt -q
npx cdk bootstrap aws://123456789012/us-east-1 || true
npx cdk deploy --require-approval never --outputs-file ../cdk-outputs.json
