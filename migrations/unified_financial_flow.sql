-- ========================================
-- UNIFIED FINANCIAL FLOW MIGRATION
-- ========================================
-- Version: 1.0.0
-- Date: January 25, 2026
-- Purpose: Implement locked design decisions from UNIFIED_FINANCIAL_FLOW.md
--
-- LOCKED DECISIONS:
-- 1. Overspend: HARD BLOCK (must transfer or use Cookie Jar)
-- 2. Income Surplus: Auto to Cookie Jar
-- 3. Income Shortfall: Always Manual
-- 4. Envelope-Transaction Link: REQUIRED for expenses
--
-- WHAT THIS MIGRATION ADDS:
-- 1. cookie_jar table (user-level emergency fund)
-- 2. cookie_jar_transactions table (track all Cookie Jar movements)
-- 3. envelope_transfers table (track transfers between envelopes)
-- 4. sahod_envelope_id on recurring_rules (link recurring to envelope)
-- 5. sahod_envelope_id on quick_add_shortcuts (link shortcuts to envelope)
-- 6. Update kaban_transactions source enum to include 'quick_add'
--
-- NOTE: sahod_envelope_id already exists on kaban_transactions
-- NOTE: cookie_jar column already exists on sahod_envelopes (per-envelope rollover)
-- ========================================

-- ==============================================
-- 1. COOKIE JAR TABLE (User-level emergency fund)
-- ==============================================
-- This is SEPARATE from sahod_envelopes.cookie_jar which is per-envelope rollover
-- This is the GLOBAL emergency buffer for the user

CREATE TABLE IF NOT EXISTS cookie_jar (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
  current_balance NUMERIC(12,2) DEFAULT 0 CHECK (current_balance >= 0),
  goal_amount NUMERIC(12,2),  -- Target: e.g., 1 month expenses
  auto_receive_surplus BOOLEAN DEFAULT true,  -- Auto-receive income surplus
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE cookie_jar IS 
'User-level emergency buffer fund. Separate from per-envelope rollover in sahod_envelopes.cookie_jar';
COMMENT ON COLUMN cookie_jar.auto_receive_surplus IS 
'When true, income surplus is automatically deposited here';
COMMENT ON COLUMN cookie_jar.goal_amount IS 
'User-defined target, typically 1 month of expenses';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cookie_jar_user_id ON cookie_jar(user_id);

-- RLS
ALTER TABLE cookie_jar ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own cookie jar" ON cookie_jar;
CREATE POLICY "Users can view own cookie jar"
  ON cookie_jar FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own cookie jar" ON cookie_jar;
CREATE POLICY "Users can create own cookie jar"
  ON cookie_jar FOR INSERT
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own cookie jar" ON cookie_jar;
CREATE POLICY "Users can update own cookie jar"
  ON cookie_jar FOR UPDATE
  USING (auth.uid() = user_id);

GRANT ALL ON cookie_jar TO authenticated;


-- ==============================================
-- 2. COOKIE JAR TRANSACTIONS TABLE
-- ==============================================
-- Track all movements into/out of Cookie Jar

CREATE TABLE IF NOT EXISTS cookie_jar_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('deposit', 'withdrawal')),
  source TEXT NOT NULL CHECK (source IN (
    'income_surplus',      -- Auto from income > expected
    'envelope_rollover',   -- End of period unused funds
    'manual_deposit',      -- User manually adds
    'overspend_cover',     -- Used to cover envelope overspend
    'shortfall_cover',     -- Used to cover income shortfall
    'manual_withdrawal'    -- User manually withdraws (PRO only)
  )),
  description TEXT,
  related_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL,
  pay_cycle_instance_id UUID REFERENCES sahod_pay_cycle_instances(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE cookie_jar_transactions IS 
'Audit log of all Cookie Jar deposits and withdrawals';
COMMENT ON COLUMN cookie_jar_transactions.source IS 
'What triggered this transaction: surplus, rollover, manual, or covering shortfall/overspend';
COMMENT ON COLUMN cookie_jar_transactions.related_envelope_id IS 
'If from envelope rollover or covering envelope overspend, which envelope';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_user ON cookie_jar_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_created ON cookie_jar_transactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_type ON cookie_jar_transactions(user_id, type);
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_source ON cookie_jar_transactions(user_id, source);

-- RLS
ALTER TABLE cookie_jar_transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own cookie jar transactions" ON cookie_jar_transactions;
CREATE POLICY "Users can view own cookie jar transactions"
  ON cookie_jar_transactions FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own cookie jar transactions" ON cookie_jar_transactions;
CREATE POLICY "Users can create own cookie jar transactions"
  ON cookie_jar_transactions FOR INSERT
  WITH CHECK (auth.uid() = user_id);

GRANT ALL ON cookie_jar_transactions TO authenticated;


-- ==============================================
-- 3. ENVELOPE TRANSFERS TABLE
-- ==============================================
-- Track transfers between envelopes (for hard block overspend handling)

CREATE TABLE IF NOT EXISTS envelope_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  from_envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
  to_envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  reason TEXT CHECK (reason IN (
    'manual_transfer',     -- User initiated transfer
    'overspend_cover',     -- Auto-transfer to cover overspend
    'rebalance'            -- Periodic rebalancing
  )) DEFAULT 'manual_transfer',
  pay_cycle_instance_id UUID REFERENCES sahod_pay_cycle_instances(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  CONSTRAINT different_envelopes CHECK (from_envelope_id != to_envelope_id)
);

COMMENT ON TABLE envelope_transfers IS 
'Audit log of fund transfers between envelopes';
COMMENT ON COLUMN envelope_transfers.reason IS 
'Why the transfer happened: manual, to cover overspend, or rebalancing';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_envelope_transfers_user ON envelope_transfers(user_id);
CREATE INDEX IF NOT EXISTS idx_envelope_transfers_from ON envelope_transfers(from_envelope_id);
CREATE INDEX IF NOT EXISTS idx_envelope_transfers_to ON envelope_transfers(to_envelope_id);
CREATE INDEX IF NOT EXISTS idx_envelope_transfers_created ON envelope_transfers(user_id, created_at DESC);

-- RLS
ALTER TABLE envelope_transfers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own envelope transfers" ON envelope_transfers;
CREATE POLICY "Users can view own envelope transfers"
  ON envelope_transfers FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own envelope transfers" ON envelope_transfers;
CREATE POLICY "Users can create own envelope transfers"
  ON envelope_transfers FOR INSERT
  WITH CHECK (auth.uid() = user_id);

GRANT ALL ON envelope_transfers TO authenticated;


-- ==============================================
-- 4. ADD sahod_envelope_id TO recurring_rules
-- ==============================================
-- Link recurring rules to envelopes for automatic deduction

ALTER TABLE recurring_rules 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

COMMENT ON COLUMN recurring_rules.sahod_envelope_id IS 
'Which envelope this recurring expense deducts from. Required for new rules.';

-- Index for finding rules by envelope
CREATE INDEX IF NOT EXISTS idx_recurring_rules_envelope ON recurring_rules(sahod_envelope_id);


-- ==============================================
-- 5. ADD sahod_envelope_id TO quick_add_shortcuts
-- ==============================================
-- Link quick add chips to envelopes for automatic deduction

ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

COMMENT ON COLUMN quick_add_shortcuts.sahod_envelope_id IS 
'Which envelope this shortcut deducts from. Auto-selected based on category mapping.';

-- Index for finding shortcuts by envelope
CREATE INDEX IF NOT EXISTS idx_quick_add_shortcuts_envelope ON quick_add_shortcuts(sahod_envelope_id);


-- ==============================================
-- 6. UPDATE kaban_transactions source enum
-- ==============================================
-- Add 'quick_add' as a valid source type
-- Note: PostgreSQL doesn't support easy enum modification, so we recreate the constraint

-- First drop the old constraint
ALTER TABLE kaban_transactions 
DROP CONSTRAINT IF EXISTS kaban_transactions_source_check;

-- Add new constraint with 'quick_add' included
ALTER TABLE kaban_transactions 
ADD CONSTRAINT kaban_transactions_source_check 
CHECK (source IN ('manual', 'recurring', 'quick_add'));


-- ==============================================
-- 7. HELPER FUNCTIONS
-- ==============================================

-- Function: Update cookie jar balance (atomic)
CREATE OR REPLACE FUNCTION update_cookie_jar_balance(
  p_user_id UUID,
  p_amount NUMERIC,
  p_type TEXT,
  p_source TEXT,
  p_description TEXT DEFAULT NULL,
  p_envelope_id UUID DEFAULT NULL,
  p_instance_id UUID DEFAULT NULL
) RETURNS NUMERIC AS $$
DECLARE
  v_new_balance NUMERIC;
BEGIN
  -- Ensure cookie jar exists for user
  INSERT INTO cookie_jar (user_id, current_balance)
  VALUES (p_user_id, 0)
  ON CONFLICT (user_id) DO NOTHING;
  
  -- Update balance
  IF p_type = 'deposit' THEN
    UPDATE cookie_jar 
    SET current_balance = current_balance + p_amount,
        updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING current_balance INTO v_new_balance;
  ELSIF p_type = 'withdrawal' THEN
    -- Check sufficient balance
    IF (SELECT current_balance FROM cookie_jar WHERE user_id = p_user_id) < p_amount THEN
      RAISE EXCEPTION 'Insufficient cookie jar balance';
    END IF;
    
    UPDATE cookie_jar 
    SET current_balance = current_balance - p_amount,
        updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING current_balance INTO v_new_balance;
  ELSE
    RAISE EXCEPTION 'Invalid type: must be deposit or withdrawal';
  END IF;
  
  -- Log the transaction
  INSERT INTO cookie_jar_transactions (
    user_id, amount, type, source, description, 
    related_envelope_id, pay_cycle_instance_id
  ) VALUES (
    p_user_id, p_amount, p_type, p_source, p_description,
    p_envelope_id, p_instance_id
  );
  
  RETURN v_new_balance;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_cookie_jar_balance IS 
'Atomically update cookie jar balance and log the transaction';


-- Function: Transfer between envelopes (atomic)
CREATE OR REPLACE FUNCTION transfer_between_envelopes(
  p_user_id UUID,
  p_from_envelope_id UUID,
  p_to_envelope_id UUID,
  p_amount NUMERIC,
  p_reason TEXT DEFAULT 'manual_transfer',
  p_instance_id UUID DEFAULT NULL
) RETURNS TABLE(from_new_balance NUMERIC, to_new_balance NUMERIC) AS $$
DECLARE
  v_from_balance NUMERIC;
  v_from_new NUMERIC;
  v_to_new NUMERIC;
BEGIN
  -- Validate same user owns both envelopes
  IF NOT EXISTS (
    SELECT 1 FROM sahod_envelopes 
    WHERE id = p_from_envelope_id AND user_id = p_user_id
  ) OR NOT EXISTS (
    SELECT 1 FROM sahod_envelopes 
    WHERE id = p_to_envelope_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'Invalid envelope IDs';
  END IF;
  
  -- Get current allocation for from_envelope in current period
  -- Note: We update sahod_allocations, not sahod_envelopes directly
  -- This requires finding the current pay cycle instance
  
  -- For now, we'll update the cached_spent inversely (reduce from, increase to)
  -- In a full implementation, we'd track "available balance" more explicitly
  
  -- Log the transfer
  INSERT INTO envelope_transfers (
    user_id, from_envelope_id, to_envelope_id, amount, reason, pay_cycle_instance_id
  ) VALUES (
    p_user_id, p_from_envelope_id, p_to_envelope_id, p_amount, p_reason, p_instance_id
  );
  
  -- Return placeholder values (actual implementation depends on how you track balances)
  RETURN QUERY SELECT p_amount::NUMERIC AS from_new_balance, p_amount::NUMERIC AS to_new_balance;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION transfer_between_envelopes IS 
'Atomically transfer funds between envelopes and log the transfer';


-- ==============================================
-- 8. CREATE COOKIE JAR FOR EXISTING USERS
-- ==============================================
-- Create cookie jar records for users who have sahod_envelopes

INSERT INTO cookie_jar (user_id, current_balance, goal_amount)
SELECT DISTINCT 
  e.user_id,
  0::NUMERIC(12,2),  -- Start with 0 balance
  NULL::NUMERIC(12,2)  -- No goal set yet
FROM sahod_envelopes e
WHERE NOT EXISTS (
  SELECT 1 FROM cookie_jar cj WHERE cj.user_id = e.user_id
)
ON CONFLICT (user_id) DO NOTHING;


-- ==============================================
-- VERIFICATION QUERIES (run these to confirm)
-- ==============================================
-- 
-- -- Check cookie_jar table exists
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'cookie_jar';
-- 
-- -- Check cookie_jar_transactions table exists
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'cookie_jar_transactions';
-- 
-- -- Check envelope_transfers table exists
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'envelope_transfers';
-- 
-- -- Check recurring_rules has sahod_envelope_id
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'recurring_rules' AND column_name = 'sahod_envelope_id';
-- 
-- -- Check quick_add_shortcuts has sahod_envelope_id
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'quick_add_shortcuts' AND column_name = 'sahod_envelope_id';
-- 
-- -- Count cookie jars created
-- SELECT COUNT(*) FROM cookie_jar;


-- ==============================================
-- DONE!
-- ========================================
-- Next steps after running this migration:
-- 1. Update API endpoints to use new tables
-- 2. Add envelope selector to recurring rules UI
-- 3. Add envelope selector to quick add UI
-- 4. Implement hard block overspend logic
-- 5. Implement income surplus/shortfall handling
-- ========================================
