# Business Insight Agent Aliyun Public 8081 Deployment

This runbook documents the deployment path that was verified on Alibaba Cloud ECS `39.106.96.209`.

It keeps the existing service on public port `80` unchanged and exposes Business Insight Agent through:

- public URL: `http://39.106.96.209:8081/`
- public Nginx listener: `0.0.0.0:8081`
- local BIA upstream: `http://127.0.0.1:5568`
- BIA container port: `5567`

## Why This Deployment Uses Prebuilt Images

The ECS host has about `1.6 GB` RAM and `2 GB` swap. Building the frontend inside Docker on this host caused Vite to stall at `transforming...` and made SSH, Cloud Assistant, and the existing public service unstable.

Use this safer flow instead:

```text
GitHub Actions runner
  -> docker build
  -> docker save | gzip
  -> upload image artifact
  -> download artifact locally
  -> SFTP image tar.gz to ECS
  -> docker load on ECS
  -> docker-compose up -d --no-build
```

The ECS host should only load and run the image. It should not build the frontend.

## Fixed Runtime Contract

The Business Insight Agent container must run with:

```text
APP_PRODUCT_MODE=business_insight
SANDBOX=local
WORKSPACE_BACKEND=local
DATA_FORMULATOR_HOME=/srv/business-insight-agent/data
DISABLE_DISPLAY_KEYS=true
DISABLE_DATA_CONNECTORS=true
DISABLE_CUSTOM_MODELS=true
BIA_USER_DEEPSEEK_KEYS_ENABLED=true
BIA_USER_DEEPSEEK_API_BASE=https://api.deepseek.com/v1
BIA_USER_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro
DF_ALLOWED_API_BASES=https://api.deepseek.com/v1
BIA_REMOTE_ANALYSIS_SERVICES=[]
```

The verified server config must report:

```text
DISABLE_DISPLAY_KEYS=true
DISABLE_DATA_CONNECTORS=true
DISABLE_CUSTOM_MODELS=true
BIA_USER_DEEPSEEK_KEYS_ENABLED=true
BIA_USER_DEEPSEEK_API_BASE=https://api.deepseek.com/v1
BIA_USER_DEEPSEEK_MODELS=[deepseek-v4-flash, deepseek-v4-pro]
BIA_AZURE_WORKSPACE_BLOCKED=true
BIA_ONLINE_CHARTIFACT_BLOCKED=true
LITELLM_TELEMETRY_DISABLED=true
REMOTE_ANALYSIS_SERVICES=[]
```

Do not store API keys or Alibaba Cloud AccessKeys in this repository.
In this deployment, `DISABLE_CUSTOM_MODELS=true` still blocks arbitrary custom providers and API base URLs. The only user-editable model setting is the DeepSeek API Key in the browser UI; provider, base URL, API version, and model choices remain server-controlled.

## GitHub Actions Image Build

The manual and deploy-triggered workflow is:

- `.github/workflows/bia-docker-image.yml`

It builds:

```text
business-insight-agent:local
```

and uploads an artifact named like:

```text
business-insight-agent-image-local-<commit_sha>
```

The artifact is a ZIP containing:

```text
business-insight-agent-local-<commit_sha>.tar.gz
```

Trigger conditions:

- manual `workflow_dispatch`
- push to `develop` when one of these changes:
  - `Dockerfile`
  - `docker-compose.bia-aliyun.yml`
  - `.github/workflows/bia-docker-image.yml`

## ECS Directory Layout

The verified deployment uses:

```text
/srv/business-insight-agent
/srv/business-insight-agent/data
/srv/business-insight-agent/.env
```

The source tree under `/srv/business-insight-agent` may be replaced during deployment, but these must be preserved:

```text
/srv/business-insight-agent/data
/srv/business-insight-agent/.env
```

The `.env` file should be based on:

```text
deploy/aliyun/.env.business_insight.template
```

Generate and keep a stable `FLASK_SECRET_KEY`.

## Upload And Load The Image

Download the GitHub Actions artifact locally, extract the ZIP, then upload the contained `tar.gz` to ECS.

Example remote path:

```text
/tmp/business-insight-agent-local-<commit>.tar.gz
```

On ECS:

```bash
gzip -dc /tmp/business-insight-agent-local-<commit>.tar.gz | docker load
```

Confirm the image exists:

```bash
docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}' \
  | grep business-insight-agent
```

Expected image:

```text
business-insight-agent    local
```

## Start Without Building On ECS

Update the source tree first, preserving `data/` and `.env`.

Then start using the preloaded image:

```bash
cd /srv/business-insight-agent
docker-compose -f docker-compose.bia-aliyun.yml up -d --no-build --remove-orphans business-insight-agent
```

If Docker Compose v1 fails with `KeyError: 'ContainerConfig'`, remove old BIA containers and retry:

```bash
docker ps -a --format '{{.ID}} {{.Names}}' \
  | awk '/business-insight-agent|business_insight_agent/ {print $1}' \
  | xargs -r docker rm -f

docker-compose -f docker-compose.bia-aliyun.yml up -d --no-build --remove-orphans business-insight-agent
```

The container must remain local-only:

```text
127.0.0.1:5568 -> 5567/tcp
```

## Public Nginx 8081 Route

Create:

```text
/etc/nginx/sites-available/business-insight-agent-public-8081
/etc/nginx/sites-enabled/business-insight-agent-public-8081
```

Config:

```nginx
server {
    listen 8081;
    server_name _;

    client_max_body_size 500m;

    location / {
        proxy_pass http://127.0.0.1:5568;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Apply:

```bash
nginx -t
systemctl reload nginx
```

Verify locally on ECS:

```bash
curl -fsS http://127.0.0.1:8081/api/insight/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
```

Expected:

```text
BIA health: success
BIA root: 200
existing service root: 200
```

## Alibaba Cloud Security Group

To expose `8081` publicly, add an inbound rule:

```text
Protocol: TCP
Port range: 8081/8081
Source: 0.0.0.0/0
Policy: Accept
Description: Business Insight Agent public HTTP on 8081
```

The verified deployment used one security group attached to the ECS instance.

After adding the rule, verify from outside ECS:

```powershell
Invoke-WebRequest -UseBasicParsing `
  -Uri 'http://39.106.96.209:8081/api/insight/health' `
  -TimeoutSec 20

Invoke-WebRequest -UseBasicParsing `
  -Uri 'http://39.106.96.209:8081/' `
  -TimeoutSec 20
```

## Final Verification Checklist

Run on ECS:

```bash
docker-compose -f /srv/business-insight-agent/docker-compose.bia-aliyun.yml ps
ss -ltnp | grep -E ':(80|8081|5568|8100)\b'
curl -fsS http://127.0.0.1:5568/api/insight/health
curl -fsS http://127.0.0.1:8081/api/insight/health
curl -fsS http://127.0.0.1:5568/api/app-config
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
```

Expected:

```text
business-insight-agent: Up (healthy)
Nginx: 0.0.0.0:8081
BIA container: 127.0.0.1:5568
existing service: 0.0.0.0:80
existing service HTTP: 200
```

Run externally:

```text
http://39.106.96.209:8081/api/insight/health -> 200
http://39.106.96.209:8081/ -> 200
http://39.106.96.209/ -> 200
```

## Rollback

To remove public access while keeping the BIA container running locally:

```bash
rm -f /etc/nginx/sites-enabled/business-insight-agent-public-8081
nginx -t
systemctl reload nginx
```

Also remove the Alibaba Cloud security group rule for TCP `8081/8081`.

To stop BIA completely:

```bash
cd /srv/business-insight-agent
docker-compose -f docker-compose.bia-aliyun.yml down
```

The existing service on port `80` should remain unaffected.

## Known Risks And Follow-Up

- This deployment exposes BIA over public HTTP without application-level login.
- Anyone who knows `http://39.106.96.209:8081/` can open it while the security group rule is public.
- Prefer adding one of these before broader use:
  - domain plus HTTPS
  - Basic Auth at Nginx
  - IP allowlist instead of `0.0.0.0/0`
  - formal application login
- Rotate any Alibaba Cloud AccessKey that was shared during deployment.
- LiteLLM still attempted to fetch its remote model cost map during startup and fell back to local backup after timeout. Telemetry and callbacks remain disabled, but this fetch should be reviewed if strict no-egress startup is required.
