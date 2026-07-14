# Business Insight Agent Aliyun Coexist Deployment

This runbook deploys Business Insight Agent on the same ECS host as an existing public service without letting the two applications compete for ports `80` and `443`.

## Goal

Target host:

- `39.106.96.209`

Target topology:

```text
Public Internet
  -> Nginx on 80/443
     -> https://<primary-domain>     -> http://127.0.0.1:8080
     -> https://bi.<primary-domain>  -> http://127.0.0.1:5568
```

Business Insight Agent runs in `business_insight` mode inside Docker Compose and persists all workspace data under:

- application directory: `/srv/business-insight-agent`
- data directory: `/srv/business-insight-agent/data`
- env file: `/srv/business-insight-agent/.env`

## Repo Artifacts Added For This Deployment

- [docker-compose.bia-aliyun.yml](/D:/VisualStudioProjects/AgentDevelopment/business-insight-agent/docker-compose.bia-aliyun.yml)
- [deploy/aliyun/.env.business_insight.template](/D:/VisualStudioProjects/AgentDevelopment/business-insight-agent/deploy/aliyun/.env.business_insight.template)
- [deploy/nginx/business-insight-agent-coexist.conf.template](/D:/VisualStudioProjects/AgentDevelopment/business-insight-agent/deploy/nginx/business-insight-agent-coexist.conf.template)

## Fixed Runtime Contract

Business Insight Agent must run with:

- `APP_PRODUCT_MODE=business_insight`
- `SANDBOX=local`
- `WORKSPACE_BACKEND=local`
- `DATA_FORMULATOR_HOME=/srv/business-insight-agent/data`
- `FLASK_SECRET_KEY=<stable explicit value>`
- `DISABLE_DISPLAY_KEYS=true`
- `DISABLE_DATA_CONNECTORS=true`
- `DISABLE_CUSTOM_MODELS=true`

Network exposure must stay limited to:

- `22`, `80`, `443` in the Alibaba Cloud security group
- no public `5568`
- no public `8080`

Business Insight Agent egress policy remains fail-closed by default:

- LiteLLM telemetry disabled
- external callbacks disabled in `business_insight` mode
- Azure Blob Workspace blocked in `business_insight` mode
- Microsoft Chartifact online viewer blocked in `business_insight` mode
- remote analysis services disabled until an administrator explicitly enables them

## Before You Start

Prepare these inputs first:

1. A fixed source version or image tag for the Business Insight Agent build.
2. The existing public domain, referred to below as `<primary-domain>`.
3. A new DNS record `bi.<primary-domain>` pointing to `39.106.96.209`.
4. A certificate that covers both `<primary-domain>` and `bi.<primary-domain>`.
5. Permission to change the current service so it listens on `127.0.0.1:8080` instead of directly occupying public `80/443`.

## Step 1: Freeze The Deployable Version

Use a verified commit or tag before building on the ECS host.

Example:

```bash
git fetch origin
git checkout <verified-commit-or-tag>
git rev-parse HEAD
```

If you are packaging an image instead of building on-host, keep the image tag aligned with the same verified commit.

## Step 2: Prepare The Host Directories

```bash
sudo mkdir -p /srv/business-insight-agent/data
sudo chown -R "$USER":"$USER" /srv/business-insight-agent
```

If the container reports a permission error while writing workspace files, grant the bind-mounted data directory to the container user:

```bash
sudo chown -R 1000:1000 /srv/business-insight-agent/data
```

## Step 3: Put The Repo In Place

Example fresh checkout:

```bash
cd /srv
git clone <your-business-insight-agent-repo-url> business-insight-agent
cd /srv/business-insight-agent
git checkout <verified-commit-or-tag>
```

Example update of an existing checkout:

```bash
cd /srv/business-insight-agent
git fetch origin
git checkout <verified-commit-or-tag>
```

## Step 4: Create The Production .env File

```bash
cd /srv/business-insight-agent
cp deploy/aliyun/.env.business_insight.template .env
```

Edit `.env` and set at least:

- `FLASK_SECRET_KEY`
- one real model provider API key and model list
- optional `BIA_IMAGE_TAG`

Keep these values fixed:

- `APP_PRODUCT_MODE=business_insight`
- `SANDBOX=local`
- `WORKSPACE_BACKEND=local`
- `DATA_FORMULATOR_HOME=/srv/business-insight-agent/data`
- `DISABLE_DISPLAY_KEYS=true`
- `DISABLE_DATA_CONNECTORS=true`
- `DISABLE_CUSTOM_MODELS=true`

## Step 5: Validate Docker Compose Configuration

```bash
cd /srv/business-insight-agent
docker compose -f docker-compose.bia-aliyun.yml config
```

This must render successfully before you start the container.

## Step 6: Start The Business Insight Agent Container

```bash
cd /srv/business-insight-agent
docker compose -f docker-compose.bia-aliyun.yml up -d --build
docker compose -f docker-compose.bia-aliyun.yml ps
```

Verify the container only binds to localhost:

```bash
ss -ltnp | grep 5568
```

Expected shape:

```text
LISTEN 0 4096 127.0.0.1:5568 ...
```

Verify the internal health endpoint through the host binding:

```bash
curl -fsS http://127.0.0.1:5568/api/insight/health
```

## Step 7: Move The Existing Public Service Behind Nginx

The existing service must end up listening on:

- `127.0.0.1:8080`

Do this in the way that matches the existing service:

- if it is a Docker container, publish `127.0.0.1:8080:<container-port>`
- if it is a systemd or host process, change its bind host and port accordingly

Before the cutover window, make sure you can reach the legacy app locally:

```bash
curl -I http://127.0.0.1:8080
```

## Step 8: Install The Nginx Site Template

Copy the template and replace all placeholders:

```bash
sudo cp deploy/nginx/business-insight-agent-coexist.conf.template /etc/nginx/conf.d/business-insight-agent.conf
```

Replace:

- `__PRIMARY_DOMAIN__`
- `__BI_DOMAIN__`
- `__SSL_FULLCHAIN__`
- `__SSL_KEY__`

The template assumes:

- legacy service upstream: `127.0.0.1:8080`
- Business Insight upstream: `127.0.0.1:5568`

## Step 9: Cut Over Public 80/443 To Nginx

Use a short maintenance window if the existing service currently occupies public `80/443` directly.

Recommended order:

1. Stop the current direct public listener on `80/443`.
2. Confirm the legacy app is reachable on `127.0.0.1:8080`.
3. Start or reload Nginx so it becomes the only public listener on `80/443`.
4. Recheck the primary domain first.
5. Only after the primary domain is healthy, validate `bi.<primary-domain>`.

Nginx validation and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Public listener check:

```bash
ss -ltnp | grep -E ':80|:443'
```

Expected result:

- only Nginx owns public `80/443`

## Step 10: Smoke Test The New Service

Primary site:

```bash
curl -I https://<primary-domain>
```

Business Insight site:

```bash
curl -I https://bi.<primary-domain>
curl -fsS https://bi.<primary-domain>/api/auth/info
curl -fsS https://bi.<primary-domain>/api/app-config
curl -fsS https://bi.<primary-domain>/api/agent/list-global-models
curl -fsS https://bi.<primary-domain>/api/sessions/list
```

Manual browser checks:

1. Open `https://<primary-domain>` and confirm the legacy service behaves exactly as before.
2. Open `https://bi.<primary-domain>` and confirm the Business Insight UI loads without a permanent loading screen.
3. Pick a configured model and confirm a simple prompt returns successfully.
4. Create a workspace or session, then restart the Business Insight container and confirm the data still exists.

Restart persistence check:

```bash
cd /srv/business-insight-agent
docker compose -f docker-compose.bia-aliyun.yml restart
docker compose -f docker-compose.bia-aliyun.yml ps
```

## Step 11: Confirm The Security Boundary

Alibaba Cloud security group:

- allow `22`
- allow `80`
- allow `443`
- do not allow `5568`

Host-side checks:

```bash
ss -ltnp | grep -E ':5568|:8080'
```

Expected result:

- `127.0.0.1:5568` only
- `127.0.0.1:8080` only

From an external network, `http://39.106.96.209:5568` should fail because the security group must not expose it.

## Backup Checklist

Back up these items before cutover:

- `/srv/business-insight-agent/data`
- `/srv/business-insight-agent/.env`
- the fixed `FLASK_SECRET_KEY`
- any server-configured model keys
- the existing service's current public-listener config
- the final Nginx site file

Example data backup:

```bash
sudo tar -czf /srv/business-insight-agent-backup-$(date +%F-%H%M%S).tgz \
  /srv/business-insight-agent/data \
  /srv/business-insight-agent/.env
```

## Rollback Plan

If the new Business Insight service fails:

1. Keep the legacy service serving traffic.
2. Stop only the Business Insight container:

```bash
cd /srv/business-insight-agent
docker compose -f docker-compose.bia-aliyun.yml down
```

3. Remove or disable the `bi.<primary-domain>` Nginx server block if needed.
4. Reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If the Nginx cutover itself fails and the main site must be restored immediately:

1. Stop or disable the broken Nginx config.
2. Restore the legacy service's original direct public listener.
3. Confirm the primary domain is healthy again.
4. Retry the coexist deployment only after the direct path is stable.

## Expected Final State

After a successful rollout:

- Nginx is the only public listener on `80/443`
- the legacy app lives behind `127.0.0.1:8080`
- Business Insight Agent lives behind `127.0.0.1:5568`
- only `22`, `80`, and `443` are open in the Alibaba Cloud security group
- Business Insight data persists under `/srv/business-insight-agent/data`
- remote analysis receivers stay disabled until an administrator explicitly enables them
