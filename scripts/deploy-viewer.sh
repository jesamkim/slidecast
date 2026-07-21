#!/usr/bin/env bash
set -euo pipefail

# Slidecast viewer build + deploy script.
# Reads config from cdk-outputs.json (produced by scripts/deploy.sh),
# builds the React viewer with Vite env vars injected, and syncs the
# resulting dist/ to the S3 bucket root. The sync explicitly excludes
# user data prefixes (slides/, thumbnails/, web/) so --delete cannot
# wipe uploaded decks.

export AWS_PROFILE=profile2
export AWS_REGION=us-east-1

cd "$(dirname "$0")/.."

O=cdk-outputs.json
if [[ ! -f "$O" ]]; then
  echo "error: $O not found. Run scripts/deploy.sh first." >&2
  exit 1
fi

read_out() {
  python3 -c "import json,sys;print(json.load(open('$O'))['SlidecastStack']['$1'])"
}

BUCKET=$(read_out BucketName)
POOL=$(read_out UserPoolId)
CLIENT=$(read_out UserPoolClientId)
COGNITO_DOMAIN=$(read_out CognitoDomain)
DIST_DOMAIN=$(read_out DistributionDomain)
DIST_ID=$(read_out DistributionId 2>/dev/null || true)

# The viewer calls the API on the same CloudFront origin (path /api/*),
# so VITE_API_BASE is empty and api.ts uses relative URLs.
API_BASE=""

cd viewer

echo "Building viewer with:"
echo "  VITE_REGION=us-east-1"
echo "  VITE_USER_POOL_ID=$POOL"
echo "  VITE_CLIENT_ID=$CLIENT"
echo "  VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN"
echo "  VITE_API_BASE=$API_BASE"

VITE_REGION=us-east-1 \
VITE_USER_POOL_ID="$POOL" \
VITE_CLIENT_ID="$CLIENT" \
VITE_COGNITO_DOMAIN="$COGNITO_DOMAIN" \
VITE_API_BASE="$API_BASE" \
npm run build

if [[ ! -f dist/index.html ]]; then
  echo "error: viewer/dist/index.html missing after build" >&2
  exit 1
fi

echo "Syncing viewer/dist to s3://$BUCKET/ (protecting slides/, thumbnails/, web/)"
aws s3 sync dist/ "s3://$BUCKET/" \
  --delete \
  --exclude "slides/*" \
  --exclude "thumbnails/*" \
  --exclude "web/*"

# Best-effort CloudFront invalidation so a redeploy is immediately visible.
if [[ -n "${DIST_ID:-}" ]]; then
  echo "Invalidating CloudFront distribution $DIST_ID (/*)"
  aws cloudfront create-invalidation \
    --distribution-id "$DIST_ID" \
    --paths "/*" >/dev/null || echo "warn: invalidation failed (non-fatal)"
else
  echo "note: DistributionId output not found; skipping invalidation. CloudFront default TTL applies."
fi

# Point the Cognito app client at the real CloudFront domain. The CDK
# stack synthesizes the client with a localhost placeholder (Cognito
# requires at least one callback URL when the code grant flow is enabled),
# and this step is the source of truth for the deployed values. Idempotent:
# rerunning simply reasserts the same URLs and OAuth settings.
CALLBACK="https://$DIST_DOMAIN/"
LOGOUT="https://$DIST_DOMAIN/"
echo "Updating Cognito app client $CLIENT callback/logout URLs to $CALLBACK"
aws cognito-idp update-user-pool-client \
  --user-pool-id "$POOL" \
  --client-id "$CLIENT" \
  --callback-urls "$CALLBACK" \
  --logout-urls "$LOGOUT" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  >/dev/null
echo "Cognito app client updated."

echo "Deploy complete: https://$DIST_DOMAIN"
