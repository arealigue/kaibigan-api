-- =============================================================================
-- Migration: Add pay cycle columns to profiles table
-- Date: 2026-02-17
-- Description: Adds pay_cycle_type, kinsenas_day, katapusan_day,
--              monthly_payday, and base_salary to the profiles table.
--              These are used by Dashboard, Kaban, and Profile pages.
-- =============================================================================

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pay_cycle_type TEXT DEFAULT 'monthly';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS kinsenas_day INTEGER DEFAULT 15;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS katapusan_day INTEGER DEFAULT 30;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS monthly_payday INTEGER DEFAULT 30;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS base_salary NUMERIC;
