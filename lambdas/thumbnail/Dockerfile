# Container image Lambda for the thumbnail worker.
# Bundles Chromium via Playwright so screenshots work without a Lambda layer.
#
# Build context is lambdas/thumbnail/. scripts/deploy.sh copies the shared
# modules (deck_model.py, ddb.py) into this directory before `cdk deploy`,
# so those files are COPYable from the build context root.
FROM public.ecr.aws/lambda/python:3.12

# Playwright's chromium needs a handful of system libraries at runtime.
# The Lambda base image is AL2023 minimal, so install them with dnf.
# List cross-referenced from playwright's ubuntu deps mapped to AL2023 names.
RUN dnf install -y \
        alsa-lib \
        atk \
        at-spi2-atk \
        at-spi2-core \
        cairo \
        cups-libs \
        dbus-libs \
        expat \
        gtk3 \
        libX11 \
        libXcomposite \
        libXdamage \
        libXext \
        libXfixes \
        libXrandr \
        libdrm \
        libxcb \
        libxkbcommon \
        libxshmfence \
        mesa-libgbm \
        nspr \
        nss \
        pango \
        fontconfig \
        google-noto-sans-cjk-fonts \
        google-noto-sans-fonts \
        google-noto-emoji-fonts \
    && fc-cache -f \
    && dnf clean all

# Install Python deps. Pin playwright to a version whose bundled chromium
# resolves cleanly against AL2023.
RUN pip install --no-cache-dir boto3==1.34.162 playwright==1.47.0

# Install the chromium browser bundle. We do NOT use `--with-deps` because
# that path shells out to apt/apt-get, which does not exist on AL2023 — we
# already installed the required libraries above via dnf.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN mkdir -p $PLAYWRIGHT_BROWSERS_PATH \
    && python -m playwright install chromium

# Copy application code into LAMBDA_TASK_ROOT. Shared modules (deck_model.py,
# ddb.py) are expected to already be in this build context — deploy.sh copies
# them from shared/ and lambdas/api/ before `cdk deploy`.
COPY handler.py ${LAMBDA_TASK_ROOT}/
COPY ddb.py ${LAMBDA_TASK_ROOT}/
COPY deck_model.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
