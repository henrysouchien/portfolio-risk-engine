# 3J. Final Deploy + Verify — Execution Plan

**Status:** READY TO EXECUTE
**Date:** 2026-03-15 (v11-final — 10 Codex review rounds)
**Depends on:** 1B Multi-User Deployment Plan (`docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md`)
**Prerequisite:** Domain name registered, 1B infrastructure phases complete (or executing in parallel)

---

## Context

The Multi-User Deployment Plan (1B) covers the full infra setup: EBS expansion, RDS, EC2 code deploy, Nginx, SSL, Vercel, Google OAuth, DNS, monitoring. This plan (3J) is the **final gate** — the last deploy after all code changes are landed, plus the smoke test that confirms everything works end-to-end.

This is NOT a first deploy. 1B gets the infrastructure running. 3J is the "ship it" checklist — final rsync with all latest code, run migrations, verify every layer.

---

## Pre-Flight Checklist

Before executing 3J, confirm ALL of these are done. **Hard-stop if any fail.**

### Infrastructure (1B)

| # | Prerequisite | How to verify | Status |
|---|-------------|---------------|--------|
| P1 | EBS expanded (1B.0) | `ssh EC2 'df -h /'` → 20 GB | |
| P2 | RDS database + schema applied (1B Phase 1) | `ssh EC2 'set -a && source /var/www/risk_module/.env && set +a && psql "$DATABASE_URL" -c "SELECT count(*) FROM _migrations"'` → matches migration count. Also: `ssh EC2 'set -a && source /var/www/risk_module/.env && set +a && psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='"'"'pgcrypto'"'"'"'` → 1 row | |
| P3 | Reference data seeded (1B.1C) | `ssh EC2 'set -a && source /var/www/risk_module/.env && set +a && psql "$DATABASE_URL" -c "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY relname"'` — 9+ reference tables with rows | |
| P4 | FMP read-only user (1B.1D) | `ssh EC2 'set -a && source /var/www/risk_module/.env && set +a && psql "$FMP_DATA_DATABASE_URL" -c "SELECT current_user"'` → `risk_module_fmp_reader` (not `estimateadmin`) | |
| P5 | Systemd service exists (1B.2C) | `ssh EC2 'systemctl status risk_module'` → loaded | |
| P6 | Nginx config exists + test passes (1B.2D) | `ssh EC2 'sudo nginx -t'` passes | |
| P7 | SSL certificate provisioned (1B.2D) | `curl -sI https://api.<domain>/api/health 2>&1 \| grep -i 'HTTP/2 200\|HTTP/1.1 200'` | |
| P8 | DNS records live + propagated (1B Phase 6) | `dig +short api.<domain>` → EC2 IP AND `dig +short app.<domain>` → CNAME. If fresh, wait for TTL (check `dig +trace`) | |
| P9 | Google OAuth production (1B Phase 5) | Console → consent screen status = "Production". Authorized JS origins include `https://app.<domain>` | |

### Code & Config

| # | Prerequisite | How to verify | Status |
|---|-------------|---------------|--------|
| P10 | Code changes landed (CORS, session cookie, deploy script) | `git log --oneline -5` shows relevant commits | |
| P11 | Release scrub done (3K) — if deploying public repo | Verification checks pass | |
| P12 | Production `.env` has all required vars | `ssh EC2 'grep -c "=" /var/www/risk_module/.env'` → ~25+ vars. Spot-check: `ENVIRONMENT=production`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `FMP_API_KEY`, `ADMIN_TOKEN` all non-empty | |
| P13 | `.env` permissions | `ssh EC2 'stat -c %a /var/www/risk_module/.env'` → `600` | |
| P14 | Vercel env vars set | Vercel dashboard: `VITE_API_URL`, `VITE_ENVIRONMENT`, `VITE_GOOGLE_CLIENT_ID` all configured for production | |
| P15 | Vercel SPA rewrite configured | Either `frontend/vercel.json` exists in repo with rewrite rule, OR the rewrite is configured in Vercel dashboard (Settings → Rewrites). Verify by curling a non-root path: `curl -sI https://app.<domain>/analyst \| head -1` → 200. If neither exists, create `frontend/vercel.json`: `{"rewrites": [{"source": "/(.*)", "destination": "/index.html"}]}` | |
| P16 | Admin-token health enhancement exists (1B.8B) | Check the code: `grep -n 'X-Admin-Token\|system.*cpu_percent' app.py`. If no match, the 1B.8B enhancement hasn't been implemented — skip detailed health checks in Step 3A. If implemented, verify at runtime: `ADMIN_TOKEN=$(ssh EC2 'set -a && source /var/www/risk_module/.env && set +a && echo $ADMIN_TOKEN') && curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" https://api.<domain>/api/health \| python3 -c "import sys,json; d=json.load(sys.stdin); print('YES' if 'system' in d else 'NO')"`. The current `app.py` health endpoint has no admin-token branch — this is a 1B.8B code change that may or may not be landed by deploy time. | |

### Local Validation

| # | Prerequisite | How to verify | Status |
|---|-------------|---------------|--------|
| P17 | Backend tests pass locally | `pytest --tb=short -q` → green | |
| P18 | Frontend production build succeeds | `cd frontend && pnpm build` → no errors | |
| P19 | Working tree is clean + committed | `git status --porcelain \| grep -v '^??'` → empty | |

### Migration Sequencing

| # | Prerequisite | How to verify | Status |
|---|-------------|---------------|--------|
| P20 | Portfolio account migrations applied in order | If this is a fresh DB from `schema_prod.sql`, all migrations are pre-marked and this is N/A. If migrating incrementally, verify that `20260312b` was applied, `scripts/fixup_account_slugs.py` was run, then `20260313_portfolio_accounts.sql` was applied, then `scripts/link_portfolio_accounts.py` was run. See `docs/planning/completed/ACCOUNTS_PORTFOLIOS_SPEC.md` §Phase 3 for the required sequence. `20260313` has a guard (`DO $$...$$`) that blocks if prerequisites are missing. | |

---

## Step 0: Pre-Deploy Backup (~5 min)

**Before any changes**, take a snapshot for rollback:

```bash
SSH_KEY="$HOME/Documents/Jupyter/Edgar_updater/edgar-updater-key.pem"
EC2="ubuntu@3.136.23.202"

# 1. Tag the current commit being deployed
DEPLOY_SHA=$(git rev-parse --short HEAD)
git tag "deploy-$(date +%Y%m%d-%H%M)-${DEPLOY_SHA}" HEAD

# 2. Snapshot current backend code on EC2 (include time + SHA to avoid collisions on same-day retries)
BACKUP_SUFFIX="$(date +%Y%m%d-%H%M)-${DEPLOY_SHA}"
ssh -i "$SSH_KEY" "$EC2" "cp -a /var/www/risk_module /var/www/risk_module.bak.${BACKUP_SUFFIX}"

# 3. Database backup
ssh -i "$SSH_KEY" "$EC2" "set -a && source /var/www/risk_module/.env && set +a && pg_dump \"\$DATABASE_URL\" --no-owner --no-privileges > /var/www/risk_module_db_backup_${BACKUP_SUFFIX}.sql"

# 4. Verify backups exist
ssh -i "$SSH_KEY" "$EC2" "ls -la /var/www/risk_module.bak.${BACKUP_SUFFIX} /var/www/risk_module_db_backup_${BACKUP_SUFFIX}.sql"

echo "Backup complete. Deploy SHA: $DEPLOY_SHA"
```

**Gate:** Backup files exist on EC2. Deploy SHA recorded.

---

## Step 1: Final Code Sync to EC2 (~10 min)

**Deploy consistency:** The goal is that backend and frontend ship the same code. In practice:
- **Backend** deploys via `rsync` from the local working tree (not `HEAD`). Untracked files are included. The script aborts on uncommitted changes.
- **Frontend** deploys via Vercel. The git-push path builds from the pushed commit (SHA-verifiable). The manual `vercel --prod` path builds from the local working tree (not SHA-verifiable — use timestamp + visual check).

For strict reproducibility, use the git-push frontend path and ensure no untracked files exist.

```bash
# Hard gate: abort if working tree has uncommitted changes
if git status --porcelain | grep -v '^??' | grep -q .; then
  echo "ABORT: uncommitted changes. Commit first."
  exit 1
fi

# Warn about untracked files (rsync deploys the working tree, not HEAD)
UNTRACKED=$(git status --porcelain | grep '^??' | grep -vE 'node_modules|__pycache__|\.pyc|venv|cache_prices|\.env' || true)
if [[ -n "$UNTRACKED" ]]; then
  echo "WARNING: untracked files will be included in rsync deploy:"
  echo "$UNTRACKED"
  echo "If these shouldn't ship, add them to .gitignore or the rsync --exclude list."
  # Not a hard stop — untracked files are common (new features). But be aware.
fi

# Record the SHA being deployed
DEPLOY_SHA=$(git rev-parse HEAD)
echo "Deploying SHA: $DEPLOY_SHA"
```

Use the deploy script created in 1B.3D:

```bash
./scripts/deploy.sh
```

This does:
1. `rsync` code to EC2 (excludes venv, node_modules, .env, .git, frontend, etc.)
2. `pip install -r requirements.txt` (catches any new deps)
3. `python3 scripts/run_migrations.py` (applies any new migrations since initial schema)
4. `systemctl restart risk_module`
5. `curl localhost:5001/api/health` (basic health check)

**Migration sequencing caveat:** If deploying to a fresh DB built from `schema_prod.sql`, all migrations are pre-marked as applied (see 1B Phase 1B) and `run_migrations.py` is a no-op. If deploying incrementally, the portfolio-accounts migrations require a specific phased sequence — see P20 in the pre-flight checklist. If P20 is not satisfied, the `20260313` migration will fail with a guard error. **Do NOT skip the guard.** Complete the required sequence manually before re-running.

**If deploy script doesn't exist yet**, run manually:
```bash
rsync -avz --delete \
  -e "ssh -i $SSH_KEY" \
  --exclude='venv' --exclude='node_modules' --exclude='frontend' \
  --exclude='.git' --exclude='__pycache__' --exclude='cache_prices' \
  --exclude='.env' --exclude='*.pyc' --exclude='.claude' \
  --exclude='archive' --exclude='backup' --exclude='user_data' --exclude='logs' \
  ./ "$EC2:/var/www/risk_module/"

ssh -i "$SSH_KEY" "$EC2" "cd /var/www/risk_module && source venv/bin/activate && pip install -q -r requirements.txt"
ssh -i "$SSH_KEY" "$EC2" "cd /var/www/risk_module && set -a && source .env && set +a && source venv/bin/activate && python3 scripts/run_migrations.py"
ssh -i "$SSH_KEY" "$EC2" "sudo systemctl restart risk_module"
sleep 3
ssh -i "$SSH_KEY" "$EC2" "curl -sf http://localhost:5001/api/health | python3 -m json.tool"
```

**If migration fails:** The error will be in the deploy command's SSH output (migrations run as a one-off command before the service restarts, not inside the systemd service). If it's the portfolio-accounts guard, see P20 in the pre-flight checklist for the required sequence. Do NOT manually skip the guard.

**Gate:** Health endpoint returns `{"status": "healthy"}`.

---

## Step 2: Verify Frontend Deploy (~5 min)

Deploy the frontend, aiming for consistency with the backend deploy.

**Preferred: Git-push path** (ensures Vercel builds from the same commit):
```bash
# Hard gate: verify HEAD is DEPLOY_SHA and on main
CURRENT_SHA=$(git rev-parse HEAD)
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_SHA" != "$DEPLOY_SHA" ]]; then
  echo "ABORT: HEAD ($CURRENT_SHA) != deploy SHA ($DEPLOY_SHA). Check out the correct commit."
  exit 1
fi
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "ABORT: Not on main ($CURRENT_BRANCH). Vercel deploys from main."
  exit 1
fi

# Push to trigger Vercel auto-deploy (Vercel builds from the tip of main)
git push origin main
```

**Alternative: Manual Vercel deploy** (builds from local working tree):
```bash
# Re-check: working tree should not have changed since backend deploy
if git status --porcelain | grep -v '^??' | grep -q .; then
  echo "ABORT: uncommitted changes appeared since backend deploy."
  exit 1
fi
cd frontend && vercel --prod
# WARNING: This deploys the local working tree, not a git commit.
# Untracked frontend changes will be included, and deployed commit SHA
# cannot be verified in Vercel dashboard. Only use this if Vercel Git
# integration is not configured.
```

After pushing, wait for the Vercel deployment to complete:
```bash
# Check latest deployment status (if using Vercel CLI)
vercel ls --prod 2>/dev/null | head -5
# Or check Vercel dashboard → Deployments tab for the latest deployment
# Verify it shows the expected commit SHA and status = "Ready"
```

**Gate:**
- `https://app.<domain>` loads the landing page (sign-in card visible)
- **Git-push path:** Verify in Vercel dashboard (Deployments tab) that the deployed commit matches `$DEPLOY_SHA`
- **Manual Vercel path:** SHA verification is not possible. Instead, verify that the deployment timestamp in Vercel dashboard is from just now, and visually confirm the app reflects the latest changes

---

## Step 3: Layer-by-Layer Verification (~20 min)

### 3A. Backend Health

```bash
# Public health endpoint
curl -sf https://api.<domain>/api/health | python3 -m json.tool

# Detailed health (with admin token) — only if P16 confirmed
# First, get the admin token from EC2:
ADMIN_TOKEN=$(ssh -i "$SSH_KEY" "$EC2" 'set -a && source /var/www/risk_module/.env && set +a && echo $ADMIN_TOKEN')
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" https://api.<domain>/api/health | python3 -m json.tool
# Should show cpu_percent, memory_percent, disk_percent (if 1B.8B is implemented)
```

### 3B. SSL + HTTPS Redirect

```bash
# Both domains have valid certs
curl -vI https://api.<domain>/api/health 2>&1 | grep "SSL certificate verify ok"
curl -vI https://app.<domain> 2>&1 | grep "SSL certificate verify ok"

# HTTP redirects to HTTPS
curl -sI http://api.<domain>/api/health | head -1  # expect 301 or 308 → https://
curl -sI http://app.<domain> | head -1              # expect 301 → https://
```

### 3C. CORS + Cookie Headers

Verify with explicit `curl` from the frontend origin:

```bash
# Preflight OPTIONS
curl -sv -X OPTIONS \
  -H "Origin: https://app.<domain>" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  https://api.<domain>/auth/google 2>&1 | grep -iE 'access-control|HTTP/'

# Verify response includes:
#   Access-Control-Allow-Origin: https://app.<domain>   (exact, not *)
#   Access-Control-Allow-Credentials: true
#   HTTP/2 200 (or HTTP/1.1 200)
```

### 3D. Google OAuth Flow + Session Persistence

1. Open `https://app.<domain>` in browser
2. Click "Sign in with Google"
3. Google Identity Services popup appears → select account
4. ID token posted to `POST /auth/google` → session cookie set
5. Verify cookie attributes in browser devtools (Application → Cookies):
   - `session_id` cookie present
   - `HttpOnly: true`
   - `Secure: true`
   - `SameSite: Lax`
6. **Hard refresh** the page (Cmd+Shift+R) → still authenticated
7. Verify auth rehydration: devtools Network tab shows `GET /auth/status` → 200 with user data (not 401)

### 3E. Authenticated API Request

After login, in browser devtools console (use the full API URL, not relative path):

```javascript
// Production routes through VITE_API_URL — no dev proxy
const apiUrl = '<VITE_API_URL value>';  // e.g., https://api.<domain>
fetch(`${apiUrl}/api/positions/holdings`, {
  credentials: 'include'
}).then(r => {
  console.log('Status:', r.status);
  return r.json();
}).then(data => {
  // Response is a monitor payload object with positions array, not a bare array
  console.log('Positions:', data.positions?.length ?? 'N/A');
  console.log(data);
});
```

Should return 200 with a payload object containing `positions` (array, possibly empty for new user). Must NOT return 401 or CORS error.

### 3F. SPA Routing (Vercel rewrite verification)

The frontend is a SPA. Most views (Research, Scenarios, Settings, Performance) are **dashboard state** managed by the client-side store, not URL pathname routes. Only `/analyst`, `/plaid/success`, and `/snaptrade/success` are true pathname-based routes in the client router (`AppOrchestratorModern.tsx`).

However, Vercel's rewrite rule must still serve `index.html` for ANY path (so users can bookmark or share URLs, and hard-refresh doesn't 404). This test verifies the Vercel rewrite:

```bash
# All paths should return 200 with HTML (not 404)
# This proves Vercel's rewrite rule is active, not that the client router handles these paths
for path in / /analyst /plaid/success /anything/random; do
  STATUS=$(curl -sI "https://app.<domain>$path" | head -1)
  echo "$path → $STATUS"
done
# All should return HTTP 200
```

Also verify in browser: open `https://app.<domain>/analyst` directly — the Analyst app should load (this is a real client route).

### 3G. Service Persistence

```bash
# Restart and verify recovery
ssh -i "$SSH_KEY" "$EC2" "sudo systemctl restart risk_module"
sleep 5
curl -sf https://api.<domain>/api/health | python3 -m json.tool
# Should still be healthy
```

---

## Step 4: Smoke Test — Full User Journey (~15 min)

Test the complete flow as a new user. **Verify actual API responses, not just UI rendering.**

| # | Action | Expected | Verify |
|---|--------|----------|--------|
| 4.1 | Open `https://app.<domain>` | Landing page with sign-in card | Visual |
| 4.2 | Sign in with Google | OAuth popup → redirect to onboarding wizard | Cookie set, `/auth/status` → 200 |
| 4.3 | Upload CSV (Schwab or sample) | Preview step shows positions, auto-detected institution | Network: `POST /api/onboarding/preview-csv` → 200 |
| 4.4 | Confirm import | Completion step → redirect to dashboard | Network: import endpoint → 200 |
| 4.5 | Dashboard loads | Metric cards populate (or empty state) | Network: `/api/positions/holdings` → 200 with payload |
| 4.6 | Navigate to Research → Stock Lookup | Type a ticker (e.g., AAPL), results load | Network: stock analysis → 200 |
| 4.7 | Navigate to Scenarios → Stress Test | Select a scenario, click "Run" | Network: stress test endpoint → 200 with results (not just form render) |
| 4.8 | Navigate to Scenarios → Monte Carlo | Run a simulation with defaults | Network: monte carlo endpoint → 200 with simulation results |
| 4.9 | Hard-refresh on current page | SPA reloads correctly (not 404) | Cmd+Shift+R → page intact, no console errors |
| 4.10 | Open AI Assistant | Chat panel opens, input field visible | Visual |
| 4.11 | Check Settings | Account connections page loads | Visual + no 500s in Network tab |

**Gate:** All 11 steps pass. No console errors, no 500s, no CORS errors in Network tab.

---

## Step 5: Performance Sanity Check (~5 min)

```bash
# Check response times from local machine
time curl -sf https://api.<domain>/api/health > /dev/null
# Should be <500ms

# Check a real API call
time curl -sf -H "Cookie: session_id=<your-session>" https://api.<domain>/api/positions/holdings > /dev/null
# Should be <3s

# Check EC2 resource usage
ssh -i "$SSH_KEY" "$EC2" "free -m && df -h / && ps aux --sort=-%mem | head -10"
```

Verify:
- Memory usage < 85% after the smoke test
- Disk usage < 70%
- No OOM kills: `ssh EC2 'journalctl -u risk_module --since "10 min ago" | grep -i "kill\|oom\|error"'`

---

## Step 6: Post-Deploy Security Hardening (~15 min)

| # | Check | Command / How | Expected |
|---|-------|---------------|----------|
| 6.1 | `.env` permissions | `ssh EC2 'stat -c %a /var/www/risk_module/.env'` | `600` |
| 6.2 | `ENVIRONMENT=production` | `ssh EC2 'grep ENVIRONMENT /var/www/risk_module/.env'` | `production` |
| 6.3 | `FLASK_SECRET_KEY` is strong | `ssh EC2 'grep FLASK_SECRET_KEY /var/www/risk_module/.env \| wc -c'` | > 40 chars |
| 6.4 | `ADMIN_TOKEN` is strong | Same check | > 40 chars |
| 6.5 | No AWS keys in `.env` (if using IAM role) | `ssh EC2 'grep AWS_ACCESS_KEY /var/www/risk_module/.env'` | 0 results (or commented out) |
| 6.6 | EC2 security group | AWS Console or `aws ec2 describe-security-groups` | Only 80, 443, 22 inbound. No 5001. |
| 6.7 | RDS security group | AWS Console | Inbound 5432 only from EC2 SG |
| 6.8 | FastAPI Swagger disabled | `curl -sI https://api.<domain>/docs` | 404 (not 200) |
| 6.9 | OpenAPI JSON disabled | `curl -sI https://api.<domain>/openapi.json` | 404 |
| 6.10 | Redoc disabled | `curl -sI https://api.<domain>/redoc` | 404 |
| 6.11 | Dev timing endpoint | `curl -sI https://api.<domain>/api/debug/timing` | 404 or 401 (route in `routes/debug.py`, mounted conditionally) |
| 6.12 | Dev stream endpoint | `curl -sI https://api.<domain>/api/dev/stream` | 404 or 401 (route in `app.py`, NOT in debug router) |
| 6.13 | Dev stats endpoint | `curl -sI https://api.<domain>/api/dev/stats` | 404 or 401 (route in `app.py`, NOT in debug router) |
| 6.14 | Google OAuth JS origins | Google Console → exact match `https://app.<domain>` (no wildcards) | |
| 6.15 | Monitoring alarms active (1B.8) | CloudWatch Console | CPU, memory, status alarms configured |

**If any dev endpoints return 200:** They must be disabled or auth-gated in production. Add `ENVIRONMENT` check or admin-token guard. This is a code change — redeploy after fixing.

---

## Step 7: External Health Check Setup (~5 min)

StatusCheckFailed only catches full instance failures. Set up an HTTP-level check to catch nginx 502s, dead uvicorn, etc.:

**Option A — Route 53 Health Check** (recommended):
1. Create health check: `https://api.<domain>/api/health`, HTTPS, 30s interval, 3 failures before alerting
2. Alarm → same SNS topic

**Option B — Simple cron**:
```bash
# Add to local crontab or EC2 crontab
*/5 * * * * curl -sf https://api.<domain>/api/health > /dev/null || echo "risk_module DOWN" | mail -s "ALERT" your@email.com
```

---

## Step 8: Go/No-Go Checklist

All must be checked before declaring "shipped":

- [ ] Pre-deploy backup taken (Step 0)
- [ ] Backend tests pass locally (P17)
- [ ] Frontend build succeeds (P18)
- [ ] Deploy consistency verified (git-push: Vercel commit matches DEPLOY_SHA; manual: timestamp recent + no tracked changes between backend and frontend deploys. Note: rsync includes untracked backend files; vercel --prod includes untracked frontend files. For strict parity, use git-push path with no untracked files.)
- [ ] Health endpoint returns healthy
- [ ] Frontend loads on custom domain
- [ ] SSL valid on both api. and app. domains
- [ ] HTTP → HTTPS redirect works
- [ ] CORS headers correct (exact origin, credentials)
- [ ] Google OAuth login works end-to-end
- [ ] Session cookie attributes correct (HttpOnly, Secure, Lax)
- [ ] Auth persists across hard refresh (`/auth/status` → 200)
- [ ] Authenticated API calls return data
- [ ] SPA routing works on hard refresh (Vercel rewrite)
- [ ] Stress test + Monte Carlo actually return results (not just render)
- [ ] Service survives restart
- [ ] Memory/disk within safe limits
- [ ] Security hardening checks pass (6.1-6.15)
- [ ] All dev endpoints disabled or auth-gated: `/api/debug/timing`, `/api/dev/stream`, `/api/dev/stats` (6.11-6.13)
- [ ] External health check active
- [ ] Monitoring alarms active

**If all pass:** Update TODO.md — mark 3J as DONE.

**If any fail:** Document the failure, fix, re-run from the failing step.

---

## Rollback

If something goes critically wrong after deploy:

### Backend rollback
```bash
# 1. Restore previous code
ssh -i "$SSH_KEY" "$EC2" "
  sudo systemctl stop risk_module
  BACKUP_DIR=\$(ls -d /var/www/risk_module.bak.* 2>/dev/null | tail -1)
  if [[ -n \$BACKUP_DIR ]]; then
    rm -rf /var/www/risk_module
    mv \$BACKUP_DIR /var/www/risk_module
    sudo systemctl start risk_module
    echo 'Rolled back to: '\$BACKUP_DIR
  else
    echo 'ERROR: No backup found'
  fi
"

# 2. Verify health after rollback
sleep 3
curl -sf https://api.<domain>/api/health
```

### Database rollback (if migration broke something)
```bash
ssh -i "$SSH_KEY" "$EC2" "
  BACKUP_SQL=\$(ls /var/www/risk_module_db_backup_*.sql 2>/dev/null | tail -1)
  echo 'Would restore from: '\$BACKUP_SQL
  # Manual step — review before executing:
  # set -a && source /var/www/risk_module/.env && set +a
  # psql \"\$DATABASE_URL\" < \$BACKUP_SQL
"
```

### Frontend rollback
```bash
# Vercel maintains deployment history. Use the dashboard or CLI:
# Option A: Dashboard → Deployments → find previous → "..." → Promote to Production
# Option B: CLI (get deployment URL from `vercel ls`):
vercel rollback <previous-deployment-url>
```

---

## DNS Propagation Contingency

If DNS is freshly configured and `dig` shows correct records but browsers get errors:

1. Check propagation: `dig @8.8.8.8 api.<domain>`, `dig @1.1.1.1 api.<domain>`
2. If inconsistent, wait for TTL (usually 300s-3600s)
3. Test with direct IP in `/etc/hosts` to confirm backend works independently of DNS:
   ```
   3.136.23.202 api.<domain>
   ```
4. If Vercel CNAME isn't resolving, check Vercel dashboard → Domain → DNS status

---

## Total Effort

| Step | Effort |
|------|--------|
| 0. Backup | 5 min |
| 1. Code sync | 10 min |
| 2. Frontend deploy | 5 min |
| 3. Layer verification | 20 min |
| 4. Smoke test | 15 min |
| 5. Performance check | 5 min |
| 6. Security hardening | 15 min |
| 7. External health check | 5 min |
| 8. Go/no-go | 5 min |
| **Total** | **~1.5 hours** |

This assumes 1B infrastructure is already standing. Add debugging time if issues surface.
