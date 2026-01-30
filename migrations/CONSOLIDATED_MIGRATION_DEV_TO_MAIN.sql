-- ==============================================
-- CONSOLIDATED MIGRATION: dev → main
-- ==============================================
-- Generated: Based on comparison of dev vs main branches
-- Purpose: All database changes needed for "Kaban is TRUTH, Sahod is PLAN" architecture
-- 
-- Run this script on production (main) database to bring it up to date with dev
-- ==============================================

-- PART 1: COOKIE JAR TABLES
-- =========================================
-- The Cookie Jar stores surplus funds and rollover amounts

CREATE TABLE IF NOT EXISTS cookie_jar (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  current_balance NUMERIC(12,2) DEFAULT 0 CHECK (current_balance >= 0),
  goal_amount NUMERIC(12,2) DEFAULT NULL,
  goal_name VARCHAR(100) DEFAULT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE cookie_jar IS 
'Stores user surplus funds - leftover from envelopes, income surplus, manual savings';

-- Cookie Jar Transactions
CREATE TABLE IF NOT EXISTS cookie_jar_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  type TEXT NOT NULL CHECK (type IN ('deposit', 'withdrawal')),
  source TEXT NOT NULL CHECK (source IN (
    'envelope_rollover',
    'income_surplus',
    'manual',
    'cover_overspend'
  )),
  description TEXT,
  related_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL,
  pay_cycle_instance_id UUID REFERENCES sahod_pay_cycle_instances(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for cookie jar
CREATE INDEX IF NOT EXISTS idx_cookie_jar_user ON cookie_jar(user_id);
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_user ON cookie_jar_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_cookie_jar_tx_created ON cookie_jar_transactions(user_id, created_at DESC);

-- RLS for cookie_jar
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

-- RLS for cookie_jar_transactions
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


-- PART 2: ENVELOPE TRANSFERS TABLE
-- =========================================
-- Track transfers between envelopes (for overspend handling)

CREATE TABLE IF NOT EXISTS envelope_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  from_envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
  to_envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  reason TEXT CHECK (reason IN (
    'manual_transfer',
    'overspend_cover',
    'rebalance'
  )) DEFAULT 'manual_transfer',
  pay_cycle_instance_id UUID REFERENCES sahod_pay_cycle_instances(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT different_envelopes CHECK (from_envelope_id != to_envelope_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_envelope_transfers_user ON envelope_transfers(user_id);
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


-- PART 3: LINK QUICK ADD & RECURRING TO ENVELOPES
-- =========================================

-- Add sahod_envelope_id to recurring_rules
ALTER TABLE recurring_rules 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_recurring_rules_envelope ON recurring_rules(sahod_envelope_id);

-- Add sahod_envelope_id to quick_add_shortcuts
ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_quick_add_shortcuts_envelope ON quick_add_shortcuts(sahod_envelope_id);

-- Add is_system_default flag for template-created shortcuts
ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS is_system_default BOOLEAN DEFAULT FALSE;


-- PART 4: UPDATE KABAN TRANSACTIONS SOURCE ENUM
-- =========================================

ALTER TABLE kaban_transactions 
DROP CONSTRAINT IF EXISTS kaban_transactions_source_check;

ALTER TABLE kaban_transactions 
ADD CONSTRAINT kaban_transactions_source_check 
CHECK (source IN ('manual', 'recurring', 'quick_add'));


-- PART 5: DEFAULT SHORTCUT TEMPLATES
-- =========================================
-- System-level templates that get instantiated per-user

DROP TABLE IF EXISTS default_shortcut_templates;

CREATE TABLE default_shortcut_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label VARCHAR(50) NOT NULL,
    label_en VARCHAR(50) NOT NULL,
    emoji VARCHAR(10) NOT NULL,
    default_amount NUMERIC(10,2) NOT NULL,
    category_id UUID NOT NULL REFERENCES expense_categories(id),
    envelope_hint VARCHAR(200),
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE default_shortcut_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Anyone can read default templates" ON default_shortcut_templates;
CREATE POLICY "Anyone can read default templates" ON default_shortcut_templates
    FOR SELECT USING (true);

-- Seed default templates (adjust UUIDs to match your expense_categories)
-- You need to replace these UUIDs with actual values from your database
INSERT INTO default_shortcut_templates (label, label_en, emoji, default_amount, category_id, envelope_hint, display_order) VALUES
('Jeep', 'Jeep Fare', '🚌', 15, 'a022a637-707c-418d-919a-6aedd013e393', 'transpo,transportation', 1),
('Grab', 'Grab/Angkas', '🚗', 100, 'a022a637-707c-418d-919a-6aedd013e393', 'transpo,transportation', 5),
('Kape', 'Coffee', '☕', 50, 'd6afbf65-64ff-47b5-8791-135c2c7fd121', 'food,pagkain', 2),
('Lunch', 'Lunch', '🍚', 100, 'a1c32020-5100-4333-9b2f-0f243b925e56', 'food,pagkain', 3),
('Milk Tea', 'Milk Tea', '🧋', 120, 'd6afbf65-64ff-47b5-8791-135c2c7fd121', 'food,pagkain', 6),
('Load', 'Mobile Load', '📱', 50, 'aceb231f-bbe3-4591-8dbb-d157307fa0e9', 'bills,bayarin', 4);


-- PART 6: ENVELOPE-CATEGORY MAPPINGS
-- =========================================
-- Links categories to envelopes for automatic expense routing

CREATE TABLE IF NOT EXISTS envelope_category_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES expense_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, category_id)
);

ALTER TABLE envelope_category_mappings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can view own mappings" ON envelope_category_mappings
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can create own mappings" ON envelope_category_mappings
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can update own mappings" ON envelope_category_mappings
    FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can delete own mappings" ON envelope_category_mappings
    FOR DELETE USING (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_envelope_category_mappings_user ON envelope_category_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_envelope_category_mappings_envelope ON envelope_category_mappings(envelope_id);


-- PART 7: ADD DEFAULT ENVELOPE HINT TO CATEGORIES
-- =========================================

ALTER TABLE expense_categories
ADD COLUMN IF NOT EXISTS default_envelope_hint VARCHAR(100);

UPDATE expense_categories SET default_envelope_hint = 'Transportation' WHERE name = 'Transportation' AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Food' WHERE name IN ('Food Delivery', 'Groceries', 'Milk Tea') AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Bills' WHERE name IN ('Bills (Kuryente/Tubig)', 'Load') AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Entertainment' WHERE name = 'Entertainment' AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Health' WHERE name = 'Medicine' AND user_id IS NULL;


-- PART 8: HELPER FUNCTIONS
-- =========================================

-- Function: Update cookie jar balance atomically
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
  INSERT INTO cookie_jar (user_id, current_balance)
  VALUES (p_user_id, 0)
  ON CONFLICT (user_id) DO NOTHING;
  
  IF p_type = 'deposit' THEN
    UPDATE cookie_jar 
    SET current_balance = current_balance + p_amount, updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING current_balance INTO v_new_balance;
  ELSIF p_type = 'withdrawal' THEN
    IF (SELECT current_balance FROM cookie_jar WHERE user_id = p_user_id) < p_amount THEN
      RAISE EXCEPTION 'Insufficient cookie jar balance';
    END IF;
    UPDATE cookie_jar 
    SET current_balance = current_balance - p_amount, updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING current_balance INTO v_new_balance;
  ELSE
    RAISE EXCEPTION 'Invalid type: must be deposit or withdrawal';
  END IF;
  
  INSERT INTO cookie_jar_transactions (
    user_id, amount, type, source, description, related_envelope_id, pay_cycle_instance_id
  ) VALUES (
    p_user_id, p_amount, p_type, p_source, p_description, p_envelope_id, p_instance_id
  );
  
  RETURN v_new_balance;
END;
$$ LANGUAGE plpgsql;


-- PART 9: INITIALIZE COOKIE JAR FOR EXISTING USERS
-- =========================================

INSERT INTO cookie_jar (user_id, current_balance, goal_amount)
SELECT DISTINCT 
  e.user_id,
  0::NUMERIC(12,2),
  NULL::NUMERIC(12,2)
FROM sahod_envelopes e
WHERE NOT EXISTS (
  SELECT 1 FROM cookie_jar cj WHERE cj.user_id = e.user_id
)
ON CONFLICT (user_id) DO NOTHING;


-- ==============================================
-- VERIFICATION QUERIES
-- ==============================================
-- Run these to verify migration success:
-- 
-- SELECT 'cookie_jar' AS table_name, COUNT(*) FROM cookie_jar
-- UNION ALL SELECT 'cookie_jar_transactions', COUNT(*) FROM cookie_jar_transactions
-- UNION ALL SELECT 'envelope_transfers', COUNT(*) FROM envelope_transfers
-- UNION ALL SELECT 'envelope_category_mappings', COUNT(*) FROM envelope_category_mappings
-- UNION ALL SELECT 'default_shortcut_templates', COUNT(*) FROM default_shortcut_templates;
--
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name = 'quick_add_shortcuts' AND column_name IN ('sahod_envelope_id', 'is_system_default');
--
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name = 'recurring_rules' AND column_name = 'sahod_envelope_id';

-- ==============================================
-- MIGRATION COMPLETE!
-- ==============================================
