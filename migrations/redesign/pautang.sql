-- =============================================
-- PAUTANG MODULE MIGRATION
-- Replaces old `utang` table with new `pautang` system
-- Date: February 18, 2026
-- =============================================

-- =============================================
-- STEP 1: Create new pautang table (replaces utang)
-- =============================================
CREATE TABLE IF NOT EXISTS pautang (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  borrower_name TEXT NOT NULL,
  amount NUMERIC NOT NULL CHECK (amount > 0),
  date_lent DATE NOT NULL DEFAULT CURRENT_DATE,
  expected_return_date DATE,
  notes TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paid')),
  paid_date DATE,
  reminders_generated JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pautang_user_status ON pautang(user_id, status);
CREATE INDEX IF NOT EXISTS idx_pautang_user_id ON pautang(user_id);

-- RLS
ALTER TABLE pautang ENABLE ROW LEVEL SECURITY;

CREATE POLICY pautang_select ON pautang FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY pautang_insert ON pautang FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY pautang_update ON pautang FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY pautang_delete ON pautang FOR DELETE USING (auth.uid() = user_id);

-- Service role bypass for backend
CREATE POLICY pautang_service_all ON pautang FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- =============================================
-- STEP 2: Create payment history table
-- =============================================
CREATE TABLE IF NOT EXISTS pautang_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pautang_id UUID REFERENCES pautang(id) ON DELETE CASCADE NOT NULL,
  amount NUMERIC NOT NULL CHECK (amount > 0),
  payment_date DATE NOT NULL DEFAULT CURRENT_DATE,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pautang_payments_pautang_id ON pautang_payments(pautang_id);

-- RLS (inherit from parent via join)
ALTER TABLE pautang_payments ENABLE ROW LEVEL SECURITY;

CREATE POLICY pautang_payments_select ON pautang_payments FOR SELECT
  USING (EXISTS (SELECT 1 FROM pautang WHERE pautang.id = pautang_payments.pautang_id AND pautang.user_id = auth.uid()));

CREATE POLICY pautang_payments_insert ON pautang_payments FOR INSERT
  WITH CHECK (EXISTS (SELECT 1 FROM pautang WHERE pautang.id = pautang_payments.pautang_id AND pautang.user_id = auth.uid()));

CREATE POLICY pautang_payments_delete ON pautang_payments FOR DELETE
  USING (EXISTS (SELECT 1 FROM pautang WHERE pautang.id = pautang_payments.pautang_id AND pautang.user_id = auth.uid()));

-- Service role bypass
CREATE POLICY pautang_payments_service_all ON pautang_payments FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- =============================================
-- STEP 3: Create AI reminder usage tracking table
-- =============================================
CREATE TABLE IF NOT EXISTS ai_reminder_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  month_year TEXT NOT NULL,  -- e.g. '2026-02'
  usage_count INTEGER DEFAULT 0,
  UNIQUE(user_id, month_year)
);

CREATE INDEX IF NOT EXISTS idx_ai_reminder_usage_user_month ON ai_reminder_usage(user_id, month_year);

-- RLS
ALTER TABLE ai_reminder_usage ENABLE ROW LEVEL SECURITY;

CREATE POLICY ai_reminder_usage_select ON ai_reminder_usage FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY ai_reminder_usage_insert ON ai_reminder_usage FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY ai_reminder_usage_update ON ai_reminder_usage FOR UPDATE USING (auth.uid() = user_id);

-- Service role bypass
CREATE POLICY ai_reminder_usage_service_all ON ai_reminder_usage FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

-- =============================================
-- STEP 4: Migrate data from old utang table
-- =============================================
-- Only run if utang table exists and has data
INSERT INTO pautang (id, user_id, borrower_name, amount, date_lent, notes, status, created_at, updated_at)
SELECT
  id,
  user_id,
  debtor_name AS borrower_name,
  amount,
  COALESCE(due_date, created_at::date) AS date_lent,
  notes,
  CASE WHEN status = 'unpaid' THEN 'active' ELSE 'paid' END AS status,
  created_at,
  now()
FROM utang
ON CONFLICT (id) DO NOTHING;

-- =============================================
-- STEP 5: Keep old table for 30 days, then drop
-- =============================================
-- DO NOT DROP utang yet.
-- After 30 days (March 20, 2026), run:
-- DROP TABLE IF EXISTS utang;
