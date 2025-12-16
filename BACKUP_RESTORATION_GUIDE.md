# 💾 Database Backup & Restoration Guide (Supabase)

**Last Updated:** November 23, 2025
**Status:** DRAFT (To be verified)

---

## 1. Overview

This guide outlines the procedures for backing up and restoring the KaibiganGPT database hosted on Supabase. 

**Critical Note:** We are currently on the **Supabase Free Tier**.
- **Point-in-Time Recovery (PITR):** NOT AVAILABLE.
- **Automatic Backups:** Daily (Midnight UTC).
- **Retention:** 7 Days.

---

## 2. Manual Backup Procedure (Before Major Changes)

Before deploying major updates or running risky migrations, perform a manual backup.

### Option A: Using Supabase Dashboard (Easiest)
1. Log in to the [Supabase Dashboard](https://supabase.com/dashboard).
2. Select the project: `kaibigan-gpt-v3`.
3. Go to **Database** -> **Backups**.
4. Click **Download** on the latest backup to save a `.sql` file locally.
   *Note: On Free Tier, you can only download the daily backups, not trigger a new one instantly via UI.*

### Option B: Using Supabase CLI (Recommended for Developers)
Prerequisite: You must have `supabase` CLI installed and logged in.

```bash
# 1. Login to Supabase
supabase login

# 2. Dump the database structure and data to a file
# Replace <project-ref> with your actual project ID (found in Dashboard Settings > General)
supabase db dump --project-ref <project-ref> -f backup_$(date +%Y%m%d_%H%M%S).sql
```

---

## 3. Restoration Procedure (Disaster Recovery)

**⚠️ WARNING:** Restoring a backup will **OVERWRITE** the current database. All data created after the backup point will be lost.

### Scenario 1: Total Data Loss / Corruption
If the production database is corrupted or deleted.

#### Step 1: Notify Stakeholders
- Notify the team immediately.
- Put the application in "Maintenance Mode" (if possible) to prevent users from writing data.

#### Step 2: Restore via Dashboard (If available)
1. Go to **Database** -> **Backups** in the Supabase Dashboard.
2. Find the last healthy backup.
3. Click **Restore**.
   *Note: On Free Tier, this might not be available directly. You may need to use the CLI.*

#### Step 3: Restore via CLI (Reliable Method)
If you have a local `.sql` backup file (from Option B above or downloaded previously):

```bash
# 1. Reset the remote database (CAUTION: DELETES EVERYTHING)
# Only do this if the database is completely FUBAR.
supabase db reset --linked

# 2. Push the backup file to the remote database
# You need the connection string from Settings > Database > Connection String (URI)
# Format: postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres

psql -d "postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres" -f backup_20251123_120000.sql
```

---

## 4. Verification (The "Fire Drill")

We must verify that this process works.

**Test Plan:**
1. Create a **new** empty Supabase project (e.g., `kaibigan-staging`).
2. Take a backup of the **Production** database using the CLI (`supabase db dump`).
3. Restore that backup into the **Staging** project.
4. Verify that:
   - All tables exist (`profiles`, `transactions`, etc.).
   - Row Level Security (RLS) policies are active.
   - Recent data is present.
   - The API can connect to Staging and fetch data.

**Action Item:** Run this test before launch.
