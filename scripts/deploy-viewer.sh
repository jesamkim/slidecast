#!/usr/bin/env bash
set -euo pipefail

# Slidecast viewer build + deploy script.
# Reads config from cdk-outputs.json (produced by scripts/deploy.sh),
# builds the React viewer with Vite env vars injected, and syncs the
# resulting dist/ to the S3 bucket root. The sync explicitly excludes
# every user-data prefix (slides/, thumbnails/, web/, public/, pdfs/) so
# --delete only touches the viewer's own static assets and can never wipe
# uploaded decks, shared public links, or pre-generated PDFs.

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

echo "Syncing viewer/dist to s3://$BUCKET/ (protecting slides/, thumbnails/, web/, public/, pdfs/)"
aws s3 sync dist/ "s3://$BUCKET/" \
  --delete \
  --exclude "slides/*" \
  --exclude "thumbnails/*" \
  --exclude "web/*" \
  --exclude "public/*" \
  --exclude "pdfs/*"

# Best-effort CloudFront invalidation so a redeploy is immediately visible.
if [[ -n "${DIST_ID:-}" ]]; then
  echo "Invalidating CloudFront distribution $DIST_ID (/*)"
  aws cloudfront create-invalidation \
    --distribution-id "$DIST_ID" \
    --paths "/*" >/dev/null || echo "warn: invalidation failed (non-fatal)"
else
  echo "note: DistributionId output not found; skipping invalidation. CloudFront default TTL applies."
fi

# Ensure the CloudFront domain is a registered Cognito callback/logout URL.
# The CDK stack synthesizes the client with a localhost placeholder (Cognito
# requires at least one callback URL when the code grant flow is enabled).
#
# update-user-pool-client REPLACES the URL lists wholesale, so we must UNION
# the CloudFront URL with whatever is already registered — otherwise every
# redeploy wipes any custom domain that was added out of band, breaking its
# Cognito login. We read the current lists, add the CloudFront URL if
# missing, and reassert the union.
CF_URL="https://$DIST_DOMAIN/"
existing=$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$POOL" --client-id "$CLIENT" \
  --query "UserPoolClient.[CallbackURLs, LogoutURLs]" --output json)

# Build newline-separated union lists (existing ∪ CloudFront URL), deduped.
mapfile -t CALLBACKS < <(python3 -c "
import json,sys
cb,lo = json.loads('''$existing''')
u = list(dict.fromkeys((cb or []) + ['$CF_URL']))
print('\n'.join(u))
")
mapfile -t LOGOUTS < <(python3 -c "
import json,sys
cb,lo = json.loads('''$existing''')
u = list(dict.fromkeys((lo or []) + ['$CF_URL']))
print('\n'.join(u))
")
echo "Ensuring Cognito app client $CLIENT includes $CF_URL (preserving existing URLs)"
aws cognito-idp update-user-pool-client \
  --user-pool-id "$POOL" \
  --client-id "$CLIENT" \
  --callback-urls "${CALLBACKS[@]}" \
  --logout-urls "${LOGOUTS[@]}" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  >/dev/null
echo "Cognito app client updated (callback URLs: ${CALLBACKS[*]})."

echo "Deploy complete: https://$DIST_DOMAIN"
