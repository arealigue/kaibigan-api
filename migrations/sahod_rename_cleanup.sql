-- ============================================================================
-- Sahod Planner Tables - Rename Migration
-- Renames tables to have "sahod_" prefix for clarity
-- Run this AFTER running cleanup_sahod_user.sql if you have existing data
-- ============================================================================

-- IMPORTANT: This migration assumes fresh install or tables are empty
-- For production with data, use ALTER TABLE ... RENAME TO instead

-- Drop old tables if they exist (for fresh install)
DROP TABLE IF EXISTS public.allocations CASCADE;
DROP TABLE IF EXISTS public.pay_cycle_instances CASCADE;
DROP TABLE IF EXISTS public.pay_cycles CASCADE;
DROP TABLE IF EXISTS public.envelopes CASCADE;

-- Drop old trigger if exists
DROP TRIGGER IF EXISTS trg_update_allocation_spent ON public.kaban_transactions;

-- Drop old column if exists
ALTER TABLE public.kaban_transactions DROP COLUMN IF EXISTS envelope_id;

-- ============================================================================
-- Now run the new sahod_planner.sql with sahod_ prefixed tables
-- ============================================================================
