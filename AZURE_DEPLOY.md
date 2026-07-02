# Azure Deployment Guide

Deploy the **Global Economic Stress Monitoring Platform** to your existing Azure Web App.

## Your Azure resources

| Setting | Value |
|---------|-------|
| **Subscription ID** | `5e3bcb35-22ff-455d-a6ad-a0eeefba56f5` |
| **Tenant / Directory ID** | `0bc92751-071a-4e2c-a48b-633206fef374` |
| **Resource group** | `E-Commerce-Intelligence-Platform` |
| **API Web App** | `E-Commerce-Intelligence-Platform` |
| **Region** | Switzerland North |
| **GitHub repo** | https://github.com/M7MDGAMERG/E-Commerce-Intelligence-Platform |
| **API URL** | https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net |

---

## Step 1 — Push this code to GitHub

```powershell
cd "C:\Users\Z-Drive\Documents\GitHub\E-Commerce-Intelligence-Platform"
git add .
git commit -m "Add Azure deployment config and startup scripts"
git push origin main
```

---

## Step 2 — Fix the Web App startup command (fixes "Issues Detected")

1. Open [Azure Portal](https://portal.azure.com)
2. Go to **E-Commerce-Intelligence-Platform** Web App
3. **Settings** → **Configuration** → **General settings**
4. Set **Startup Command** to:

   ```
   bash startup.sh
   ```

5. Click **Save** and **Continue** when prompted to restart

---

## Step 3 — Add application settings

Still in **Configuration** → **Application settings**, add:

| Name | Value |
|------|-------|
| `FRED_API_KEY` | Your key from https://fred.stlouisfed.org/docs/api/api_key.html |
| `WEBSITES_PORT` | `8000` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |
| `LOG_LEVEL` | `INFO` |

Click **Save**.

---

## Step 4 — Configure health check

1. **Settings** → **Health check**
2. Enable health check
3. Path: `/health`
4. Save

---

## Step 5 — GitHub Actions (deploy on push)

If Azure **Deployment Center** already created a workflow, you may have two workflows. Keep **one** API deploy workflow:

- Preferred: `.github/workflows/azure-api.yml` (includes tests)

**If deploy fails with "publish profile" error:**

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Find the secret named like `AZUREAPPSERVICE_PUBLISHPROFILE_...`
3. Copy the exact name into `azure-api.yml` under `publish-profile:`

Or re-connect Deployment Center: Web App → **Deployment Center** → **Disconnect** → reconnect GitHub → it recreates the secret.

---

## Step 6 — Ship the database to Azure (required for API data)

**Recommended — deploy via GitHub (no Kudu, SSH, or Azure CLI):**

The bootstrap SQLite file `data/economic_stress.db` is tracked in git and deployed automatically by GitHub Actions on every push to `main`.

### 6A — First-time setup (run once)

1. Install Python 3.11 and Git for Windows (or use GitHub Desktop).

2. Run ETL locally if you don't already have the database:

```cmd
cd C:\Users\Z-Drive\Documents\GitHub\E-Commerce-Intelligence-Platform
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
scripts\run_etl_local.bat
```

3. Add `FRED_API_KEY` to `.env` (optional but recommended for fresh ETL runs).

4. Push the database to GitHub — this triggers an automatic API deploy:

```cmd
scripts\push_db_to_azure.bat
```

Or manually:

```cmd
git add data/economic_stress.db data/stress_model_params.json
git commit -m "Deploy bootstrap database to Azure API"
git push origin main
```

5. Watch **GitHub → Actions** until the API workflow completes.

6. Verify in browser:

- https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/global-summary

Expected: JSON with stress metrics (not HTTP 500).

### 6B — Refresh data later

Re-run ETL locally, then `scripts\push_db_to_azure.bat` again. Each push redeploys the API with the updated database.

---

### Alternative — upload via Kudu / FTPS (if you cannot push to GitHub)

Kudu URL for this app (regional hostname — **not** `.scm.azurewebsites.net`):

```
https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.scm.switzerlandnorth-01.azurewebsites.net
```

Or Portal → API Web App → **Advanced Tools** → **Go** → **Debug console** → **CMD** → drag-and-drop into `site/wwwroot/data/`.

---

### Alternative — run ETL on Azure (SSH)

1. Web App → **Development Tools** → **SSH**
2. Run:

   ```bash
   cd /home/site/wwwroot
   bash scripts/run_etl.sh
   ```

   Requires `FRED_API_KEY` in app settings. Takes 5–15 minutes.

---

## Step 7 — Verify the API

Open in browser:

- https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/
- https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/health
- https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/docs
- https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net/global-summary

Expected:

- `/` → `"status": "running"`
- `/health` → `"status": "healthy"` (after ETL)
- `/global-summary` → JSON with stress metrics

---

## Step 8 — Deploy the Streamlit dashboard (second Web App)

The dashboard is a **separate** app. One Web App cannot run FastAPI and Streamlit together.

### 8a. Create dashboard Web App

1. Portal → **Create a resource** → **Web App**
2. Name: `E-Commerce-Intelligence-Dashboard` (must be globally unique)
3. Resource group: `E-Commerce-Intelligence-Platform`
4. Runtime: **Python 3.11** on **Linux**
5. Plan: same as API (`ASP-ECommerceIntelligencePlatform-86d5`)

### 8b. Configure dashboard

**Startup Command:**

```
bash startup-dashboard.sh
```

**Application settings:**

| Name | Value |
|------|-------|
| `API_BASE_URL` | `https://e-commerce-intelligence-platform-f9dnhnfng5g2c6bz.switzerlandnorth-01.azurewebsites.net` |
| `WEBSITES_PORT` | `8000` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |

### 8c. Connect GitHub for dashboard

1. Dashboard Web App → **Deployment Center** → GitHub → same repo, branch `main`
2. Or run workflow manually: GitHub → **Actions** → **Build and deploy Dashboard** → **Run workflow**
3. Add publish profile secret for the dashboard app

### 8d. Restrict CORS on API (optional)

On the **API** Web App, add setting:

| Name | Value |
|------|-------|
| `CORS_ORIGINS` | `https://e-commerce-intelligence-dashboard.azurewebsites.net` |

(Use your actual dashboard URL.)

---

## Step 9 — Schedule daily ETL (optional)

Matches the Airflow schedule (02:00 UTC daily).

1. Create a service principal (Azure CLI):

   ```powershell
   az ad sp create-for-rbac --name "github-etl-ecommerce" `
     --role contributor `
     --scopes /subscriptions/5e3bcb35-22ff-455d-a6ad-a0eeefba56f5/resourceGroups/E-Commerce-Intelligence-Platform `
     --sdk-auth
   ```

2. GitHub repo → **Settings** → **Secrets** → **New repository secret**
3. Name: `AZURE_CREDENTIALS`
4. Value: paste the full JSON from step 1
5. Workflow `.github/workflows/daily-etl.yml` runs automatically at 02:00 UTC

Manual trigger: GitHub → **Actions** → **Daily ETL Pipeline** → **Run workflow**

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Issues Detected** / app won't start | Set startup command: `bash startup.sh` |
| 502 / connection refused | Check `WEBSITES_PORT=8000` |
| `/health` shows `"database": "missing"` or data endpoints return 500 | Run `scripts\push_db_to_azure.bat` (Step 6A) |
| FRED collector fails | Set valid `FRED_API_KEY` |
| Dashboard "API Offline" | Set `API_BASE_URL` to API HTTPS URL |
| Deploy succeeds but old code | Restart Web App; check GitHub Actions logs |
| GitHub Action fails on secret | Fix publish profile secret name in workflow |

**View logs:** Web App → **Monitoring** → **Log stream**

---

## Architecture

```
GitHub (main branch)
    │
    ├─► GitHub Actions ──► API Web App (FastAPI + gunicorn)
    │                         │
    │                         └─► SQLite: data/economic_stress.db
    │
    └─► GitHub Actions ──► Dashboard Web App (Streamlit)
                              │
                              └─► calls API via API_BASE_URL
```

ETL: run locally, then `scripts\push_db_to_azure.bat` to deploy via GitHub Actions. Optional daily refresh via `daily-etl.yml`.
