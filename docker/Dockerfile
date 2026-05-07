FROM node:26-alpine AS node-runtime

FROM python:3.14-alpine

WORKDIR /work

COPY requirements.txt /tmp/requirements.txt
COPY docker/ai-video-generator /usr/local/bin/ai-video-generator
COPY docker/codex /usr/local/bin/codex
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

# Alpineでffmpeg・日本語フォント・Node実行互換ライブラリを最小構成で入れる。
# DockerのCOPYでnpm/npxの相対リンクが崩れるため、最終イメージ側で張り直す。
RUN apk add --no-cache \
    bash \
    ca-certificates \
    curl \
    ffmpeg \
    fontconfig \
    font-noto-cjk \
    gcompat \
    libc6-compat \
    libstdc++ \
  && ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
  && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
  && python -m venv /opt/ai-video-generator-venv \
  && /opt/ai-video-generator-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
  && chmod +x /usr/local/bin/ai-video-generator /usr/local/bin/codex \
  && rm -rf /root/.npm

ENV PATH="/opt/ai-video-generator-venv/bin:${PATH}"

ENTRYPOINT ["ai-video-generator"]
CMD ["--help"]
