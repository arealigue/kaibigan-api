-- ============================================================================
-- CLEAN SLATE: Reset ALL Kaban + Sobre + Pautang data for a specific user
-- ============================================================================
-- ⚠️  WARNING: This will permanently delete ALL financial data for the target user.
--     Tables wiped: kaban_transactions, recurring_rules, ipon_goals,
--                   sahod_allocations, sahod_pay_cycle_instances, sahod_envelopes,
--                   sahod_pay_cycles, pautang_payments, pautang
--
-- Instructions:
--   1. Replace the UUID in target_user_id below
--   2. Run in Supabase SQL Editor
--   3. Verify with the SELECT queries at the bottom
-- ============================================================================

DO $$
DECLARE
  target_user_id UUID := 'REPLACE-WITH-YOUR-USER-ID';
  deleted_count   INT;
BEGIN

  RAISE NOTICE '════════════════════════════════════════════════════════════';
  RAISE NOTICE '  CLEAN SLATE for user: %', target_user_id;
  RAISE NOTICE '════════════════════════════════════════════════════════════';

  -- ══════════════════════════════════════════════════════════════
  -- PHASE 1: UNLINK FK references on kaban_transactions
  -- (Must happen before deleting Sobre tables due to FK constraints)
  -- ══════════════════════════════════════════════════════════════

  -- 1a. Unlink Sobre envelope references
  UPDATE kaban_transactions
  SET sahod_envelope_id = NULL
  WHERE user_id = target_user_id
    AND sahod_envelope_id IS NOT NULL;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [1a] Unlinked sahod_envelope_id from % kaban tx', deleted_count;

  -- 1b. Unlink Sobre instance references
  UPDATE kaban_transactions
  SET sahod_instance_id = NULL
  WHERE user_id = target_user_id
    AND sahod_instance_id IS NOT NULL;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [1b] Unlinked sahod_instance_id from % kaban tx', deleted_count;

  -- ══════════════════════════════════════════════════════════════
  -- PHASE 2: DELETE Sobre (Sahod) data — order matters for FKs
  -- ══════════════════════════════════════════════════════════════

  -- 2a. sahod_allocations → references envelopes + instances
  DELETE FROM sahod_allocations WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [2a] Deleted % sahod_allocations', deleted_count;

  -- 2b. sahod_pay_cycle_instances → references pay_cycles
  DELETE FROM sahod_pay_cycle_instances WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [2b] Deleted % sahod_pay_cycle_instances', deleted_count;

  -- 2c. sahod_envelopes → now safe (allocations + kaban links cleared)
  DELETE FROM sahod_envelopes WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [2c] Deleted % sahod_envelopes', deleted_count;

  -- 2d. sahod_pay_cycles → now safe (instances deleted)
  DELETE FROM sahod_pay_cycles WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [2d] Deleted % sahod_pay_cycles', deleted_count;

  -- ══════════════════════════════════════════════════════════════
  -- PHASE 3: DELETE Kaban data
  -- ══════════════════════════════════════════════════════════════

  -- 3a. kaban_transactions (all income + expense)
  DELETE FROM kaban_transactions WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [3a] Deleted % kaban_transactions', deleted_count;

  -- 3b. recurring_rules (auto-posting rules)
  DELETE FROM recurring_rules WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [3b] Deleted % recurring_rules', deleted_count;

  -- 3c. ipon_goals (savings goals)
  DELETE FROM ipon_goals WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [3c] Deleted % ipon_goals', deleted_count;

  -- ══════════════════════════════════════════════════════════════
  -- PHASE 4: DELETE Pautang data
  -- ══════════════════════════════════════════════════════════════

  -- 4a. pautang_payments → references pautang
  DELETE FROM pautang_payments WHERE pautang_id in (select pautang_id from pautang WHERE user_id = target_user_id);
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [4a] Deleted % pautang_payments', deleted_count;

  -- 4b. pautang (loan records)
  DELETE FROM pautang WHERE user_id = target_user_id;
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RAISE NOTICE '  [4b] Deleted % pautang', deleted_count;

  -- ══════════════════════════════════════════════════════════════
  RAISE NOTICE '════════════════════════════════════════════════════════════';
  RAISE NOTICE '  ✅ CLEAN SLATE complete for user: %', target_user_id;
  RAISE NOTICE '  Profile and auth data are UNTOUCHED.';
  RAISE NOTICE '════════════════════════════════════════════════════════════';

END $$;


-- ============================================================================
-- VERIFY: Confirm all tables are empty for this user
-- Replace the UUID below to match target_user_id above
-- ============================================================================
SELECT table_name, remaining FROM (
  SELECT 'kaban_transactions' AS table_name, COUNT(*) AS remaining
    FROM kaban_transactions WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'recurring_rules', COUNT(*)
    FROM recurring_rules WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'ipon_goals', COUNT(*)
    FROM ipon_goals WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'sahod_pay_cycles', COUNT(*)
    FROM sahod_pay_cycles WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'sahod_pay_cycle_instances', COUNT(*)
    FROM sahod_pay_cycle_instances WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'sahod_envelopes', COUNT(*)
    FROM sahod_envelopes WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'sahod_allocations', COUNT(*)
    FROM sahod_allocations WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'pautang', COUNT(*)
    FROM pautang WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
  UNION ALL
  SELECT 'pautang_payments', COUNT(*)
    FROM pautang_payments WHERE user_id = 'REPLACE-WITH-YOUR-USER-ID'
) AS verification
ORDER BY table_name;
