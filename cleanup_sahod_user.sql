-- ============================================================================
-- CLEANUP SAHOD DATA FOR SPECIFIC USER
-- User ID: 9f6eb51a-a916-4cf3-99ab-224970b8ea86
-- Run this in Supabase SQL Editor to reset Sahod Planner for this user
-- ============================================================================

BEGIN;

-- 1. Delete sahod_allocations (depends on envelopes and instances)
DELETE FROM sahod_allocations 
WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';

-- 2. Delete sahod_envelopes
DELETE FROM sahod_envelopes 
WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';

-- 3. Delete sahod_pay_cycle_instances (depends on pay_cycles)
DELETE FROM sahod_pay_cycle_instances 
WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';

-- 4. Delete sahod_pay_cycles
DELETE FROM sahod_pay_cycles 
WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';

-- 5. Optional: Unlink any Kaban transactions from Sahod envelopes
UPDATE kaban_transactions 
SET sahod_envelope_id = NULL 
WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86' 
  AND sahod_envelope_id IS NOT NULL;

COMMIT;

-- Verify cleanup
SELECT 'sahod_pay_cycles' as table_name, COUNT(*) as remaining 
FROM sahod_pay_cycles WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_pay_cycle_instances', COUNT(*) 
FROM sahod_pay_cycle_instances WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_envelopes', COUNT(*) 
FROM sahod_envelopes WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_allocations', COUNT(*) 
FROM sahod_allocations WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';
