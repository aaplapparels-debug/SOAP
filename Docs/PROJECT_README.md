# AAPL Sales & Operations Dashboard — Project Documentation

**Tenant:** AAPL (Jockey brand apparel distributor — SPM/Mens Outerwear, SPW/Womens Outerwear, Thermal, KTH/Kids Thermal divisions)

This document covers the project from its original Google-Sheets-based form through to the current architecture, so it can be picked up and maintained in VS Code without needing to reconstruct the reasoning from scratch.

---

## 1. What This Project Is

A multi-source business intelligence dashboard replacing a Gemini-assisted Google Sheets system. It pulls data from two live business systems — **Shoper** (POS/ERP, SQL Server-backed) and **Tally** (accounting, XML/HTTP API) — into a single canonical Postgres database, which a Streamlit dashboard reads from.

**Core architecture: ports-and-adapters.** Neither Shoper's schema nor Tally's XML shape ever leaks past their respective adapter files. The dashboard, and the canonical database itself, only ever speak in plain business terms (`customer_code`, `item_code`, `sale_date`, `net_value`) — regardless of which source system, or which future source system, the data came from.

**Multi-tenant, multi-source by design, not by accident.** Each tenant (AAPL today, potentially other distributors later) gets its own isolated Postgres database (via Neon, one project per tenant) — not a shared database with a `tenant_id` column. Within one tenant's database, every canonical table carries a `source_system` column, and every load is scoped to that source (never a table-wide wipe) — so a second source (a future Botree adapter, an Excel-based adapter for a division without a proper ERP) could feed the same table without destroying the first source's data.

---

## 2. Why It Looks The Way It Does — Key Decisions

These aren't arbitrary choices; each one came from a real problem encountered along the way.

- **Native SQL Server, not Docker.** Early restores through a Dockerized SQL Server were wildly inconsistent (5 minutes to 97+ minutes for the same file) and sometimes got permanently stuck in a `RESTORING` state that couldn't self-recover. Moving to a native SQL Server 2017 install on the processing machine removed a whole layer of Docker Desktop/WSL2 uncertainty.
- **`sqlcmd.exe` for the actual `RESTORE DATABASE`, not `pyodbc`.** Even after moving off Docker, every restore run through a persistent `pyodbc` connection still got stuck; every restore run by hand through `sqlcmd` succeeded, every single time, no exceptions. Rather than keep debugging *why*, `restore_shoper_backups.py` shells out to real `sqlcmd.exe` as a subprocess for that one specific command, while `pyodbc` is still used everywhere else (simple reads, and all of `shoper_adapter.py`'s actual data extraction) — never once a problem there.
- **Google Drive relay between production and processing machines.** The Shoper/Tally machine is down entirely outside business hours (no safe overnight window exists at all), and Day-End backup timing is genuinely unpredictable (manual process, sometimes delayed). A lightweight uploader on the production machine (low resource cost, tolerant of any timing) pushes new backups to Drive during business hours; a downloader on the processing machine pulls them whenever convenient, decoupling the heavy restore/extract work entirely from production's constraints.
- **OAuth user login for Drive, not a service account.** Google flatly refuses to let a service account write to personal Drive storage (zero quota by design, confirmed via testing) — OAuth as a real Google account, one-time browser login, was the actual supported path for a non-Workspace account.
- **Financial-year-anchored date windows, not rolling N-years-from-today.** Indian FY runs April–March; "3 years back" means April 1 three FYs ago, not exactly 1,095 days before today. Baked into `get_financial_year_cutoff()` in `shoper_adapter.py`.
- **Full-refresh (truncate + reload), not upsert, for "live snapshot" tables** (`sales_orders`, `outstanding_debtors`, `items`/`customers`). An upsert-only approach can add or update rows but never remove one that's no longer true (an order that got fully billed, a customer that no longer exists) — leaving stale data with no way to detect it went stale. A full refresh, scoped to the relevant `source_system`, is always an honest current snapshot.
- **Sales orders: `PendingQty > 0` AND placed within a recent lookback window** (`sales_orders_lookback_days` in config), not just "still pending." An order stuck unbilled for months isn't actionable — the customer just places a fresh order rather than chasing an old one — so it's deliberately excluded even though technically still pending.
- **PDC is not a separate extraction.** Once `receipts` carries `instrument_date` directly, "is this a post-dated cheque" is just a query-time filter (`instrument_date > today()`), not duplicated detection logic in the adapter.
- **Bill-wise attribution via `BILLALLOCATIONS.LIST` and presence/absence of it**, not Tally's `ISPARTYLEDGER` flag or simple ledger-name comparison. Both simpler approaches were tried and empirically failed once a real receipt was found that settles bills across *multiple different customer ledgers in one bank transaction* — confirmed against an actual Tally screen. A party/customer ledger entry always carries `BILLALLOCATIONS.LIST`; the payment-side (bank/cash) entry never does — that's the reliable signal.
- **No `tenant_id` column inside business tables.** Isolation happens at the database level (Neon project per tenant), so business tables stay clean.

---

## 3. Known Open Items / Deliberately Deferred

Named explicitly so they don't get mistaken for oversights:

- **Full pipeline automation is not yet built.** Every step (upload → download → restore → extract → load) has so far been run manually. This is the biggest gap before "production ready."
- **Tally's `receipts`/`credit_notes` are full-refresh, not incremental** — `extract_receipts`/`extract_credit_notes` don't yet accept a `since_date`. Correct, just re-pulls the whole window every run instead of only what changed.
- **Ledger view** (invoices + receipts + CN combined into a running balance per customer) — the building blocks exist; the view itself doesn't yet. Deliberately meant to be a SQL view computed at read time, not a stored/duplicated table.
- **Delivery Dashboard — explicitly out of scope.** No delivery data source exists anywhere in Shoper or Tally today; AAPL doesn't track deliveries in any system yet.
- **JC (Journey Cycle) date boundaries** (`jc_periods` table) are manually curated, same as the old `JC_Master` sheet — populated by hand via `INSERT`, not derived from any system.
- **Excel-based adapter and a no-code column-mapping tool** — correctly deferred until a real second source/tenant exists to design against, rather than guessed at now.
- **Cross-system identity matching** (e.g. if a future source described "the same" customer under a different ID scheme) — not solved. Rows would sit tagged by `source_system`, unmatched.
- **Dashboard OAuth login** — Web-application Google OAuth flow was in progress; a PKCE `code_verifier` persistence bug was hit and resolved outside this thread.
- **Original Tally-pipeline `credentials.json`/`viewercredentials.json`** — flagged very early in this project as exposed/compromised. Confirm these were rotated if not already done; this project no longer depends on them (Sheets access is being fully retired), but the exposure itself is a separate concern from this migration.

---

## 4. Data Flow, End to End

```
Production machine (Shoper + Tally, no safe overnight window)
    │
    ├── Shoper Day-End backup (.ZIP, one per division, unpredictable timing)
    │       │
    │       ▼
    │   upload_backups_to_drive.py  (lightweight, business-hours safe)
    │       │
    │       ▼
    │   Google Drive (relay only)
    │       │
    │       ▼
    │   download_backups_from_drive.py   ─── runs on PROCESSING machine
    │       │
    │       ▼
    │   restore_shoper_backups.py   (extract zip → sqlcmd RESTORE → per-division staging DB)
    │       │
    │       ▼
    │   shoper_adapter.py   (SQL Server → canonical-shaped DataFrames)
    │
    └── Tally (live XML/HTTP API, queried directly — no file relay needed)
            │
            ▼
        tally_adapter.py   (Tally XML → canonical-shaped DataFrames)

                    │                           │
                    └───────────┬───────────────┘
                                ▼
                    load_to_postgres.py
                    (source-scoped load into canonical schema)
                                ▼
                        Neon Postgres (canonical_schema.sql)
                                ▼
                        dashboard.py (Streamlit, Google OAuth login)
```

---

## 5. File Inventory

| File | Purpose |
|---|---|
| `config_loader.py` | Reads `config.<env>.yaml` based on `APP_ENV` env var; resolves the SQL Server password from `SHOPER_SA_PASSWORD` env var, never from the file. |
| `config.dev.yaml` | All environment-specific settings: backup paths, SQL Server instance, Google Drive, Postgres connection, Tally URL/division prefixes, sync windows, dashboard OAuth. `config.prod.yaml` would mirror this with production values. |
| `restore_shoper_backups.py` | Finds each division's latest backup zip, extracts it, copies into SQL Server's data folder, restores via `sqlcmd.exe`, verifies `ONLINE` state, cleans up. |
| `shoper_adapter.py` | `ShoperAdapter` class + `DivisionConfig`. Extracts customers, items, sales, sales_orders, purchases from Shoper's restored SQL Server databases. Owns the financial-year cutoff math (`get_financial_year_cutoff`). |
| `tally_adapter.py` | `TallyAdapter` class. Extracts outstanding debtors, receipts (with payment detail), credit notes from Tally's XML API. Config-driven division-prefix mapping (no hardcoding). |
| `drive_auth.py` | Shared OAuth-as-user helper for Google Drive access (used by both upload/download scripts). One-time browser login, cached token reused after. |
| `upload_backups_to_drive.py` | Runs on the **production** machine. Finds new backup zips matching each division's pattern, uploads any not already logged as shipped. |
| `download_backups_from_drive.py` | Runs on the **processing** machine. Pulls anything in the Drive folder not already logged as downloaded, into the local watch folder `restore_shoper_backups.py` reads from. |
| `transfer_log.py` | Shared plain-text transfer log (one filename per line) used by both the uploader and downloader — a file only gets logged as complete *after* its transfer fully succeeds, so a partial/corrupted transfer never gets wrongly treated as done. |
| `canonical_schema.sql` | The full canonical Postgres schema — customers, items, sales, sales_orders, purchases, outstanding_debtors, receipts, credit_notes, sync_state, dashboard_users, jc_periods. Every business table carries `source_system`; every `CREATE TABLE` uses `IF NOT EXISTS` (safe to re-run). |
| `load_to_postgres.py` | Orchestrates both adapters, applies the schema, and loads every table with source-scoped logic (full refresh vs. incremental-by-watermark, per table). |
| `dashboard.py` | The new Streamlit dashboard reading from Neon. Currently contains the Google OAuth login gate only — report pages are the next layer to build on top. |

---

## 6. Setup From Scratch (VS Code)

1. **Clone/copy all files above into one project folder.**
2. **Python environment:** `pip install -r requirements.txt` (see below).
3. **Environment variables** (set in your shell, or a `.env` file loaded via `python-dotenv` if you add that):
   - `SHOPER_SA_PASSWORD` — the SQL Server `sa` password.
   - `APP_ENV` — `dev` or `prod`, selects which `config.<env>.yaml` loads. Defaults to `dev` if unset.
4. **Credential files needed alongside the code** (none of these should ever be committed to a public repo):
   - `drive_client_secret.json` — Google OAuth **Desktop app** client, for the Drive relay's `drive_auth.py`.
   - `dashboard_client_secret.json` — Google OAuth **Web application** client (different type — needed for multi-user browser login), for `dashboard.py`.
   - `token.json` — auto-created after the first Drive login; don't create manually.
5. **Fill in `config.dev.yaml`** with real values: backup folder paths, SQL Server instance name (`localhost\INSTANCENAME`), Neon connection string, Tally URL, Drive folder ID.
6. **Neon setup:** create a free project, run `canonical_schema.sql` against it (via `load_to_postgres.py`, which applies it automatically — or manually in Neon's SQL editor for a first look).
7. **Seed required manual data:**
   ```sql
   INSERT INTO dashboard_users (email, role) VALUES ('your-email@gmail.com', 'Admin');
   INSERT INTO jc_periods (jc_code, financial_year, start_date, end_date)
       VALUES ('M1', 20262027, '2026-04-01', '2026-04-30');
   ```
8. **SQL Server:** native install (not Docker), named instance, Mixed Mode authentication, `sa` login enabled.
9. **Run order for a fresh sync:**
   ```
   python download_backups_from_drive.py     # only if using the Drive relay
   python restore_shoper_backups.py
   python load_to_postgres.py
   streamlit run dashboard.py
   ```

---

## 7. Glossary (Shoper/Tally-specific terms used throughout the code)

- **JC (Journey Cycle):** AAPL's internal review period — like a custom fiscal month. Boundaries vary year to year, hence `jc_periods` keys on `(jc_code, financial_year)`, not `jc_code` alone.
- **PDC (Post-Dated Cheque):** A cheque dated in the future. Not a separate table — just `receipts` rows where `instrument_date > today()`.
- **SaleTrnType / TrnType codes (Shoper):** `2100` = Sales Invoice, `1300` = Sales Return, `1600` = Void/Cancel (excluded entirely, not subtracted), `1100` = Purchase.
- **BILLALLOCATIONS.LIST (Tally):** Tally's mechanism for linking a receipt or credit note back to the specific invoice it settles — the equivalent of a foreign key, expressed in XML.
- **Division prefixes (SCRS/SWCRS/THCRS/KTHCRS):** Voucher-numbering convention shared by both Shoper and Tally, used to identify which division (SPM/SPW/Thermal/KTH) a transaction belongs to. Config-driven in both adapters, not hardcoded.
