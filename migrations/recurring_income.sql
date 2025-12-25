-- =====================================================
-- RECURRING INCOME MIGRATION
-- Run this in Supabase SQL Editor
-- =====================================================

-- 1. Create recurring_rules table
CREATE TABLE IF NOT EXISTS recurring_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Transaction details (what to insert)
    amount DECIMAL(12,2) NOT NULL,
    description TEXT,
    category_id UUID REFERENCES expense_categories(id),
    transaction_type TEXT NOT NULL DEFAULT 'income' CHECK (transaction_type IN ('income', 'expense')),
    
    -- Schedule configuration
    frequency TEXT NOT NULL CHECK (frequency IN ('monthly', 'bimonthly', 'weekly')),
    -- For monthly: day of month (1-31). For bimonthly: stores first day (second is calculated as +15)
    -- For weekly: day of week (0=Sunday, 1=Monday, etc.)
    schedule_day INTEGER NOT NULL,
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    
    -- Tracking
    last_posted_date DATE,  -- Last date a transaction was auto-posted for this rule
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Add columns to kaban_transactions for tracking source
ALTER TABLE kaban_transactions 
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'recurring'));

ALTER TABLE kaban_transactions 
ADD COLUMN IF NOT EXISTS recurring_rule_id UUID REFERENCES recurring_rules(id) ON DELETE SET NULL;

-- 3. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_recurring_rules_user_id ON recurring_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_recurring_rules_active ON recurring_rules(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_kaban_transactions_recurring ON kaban_transactions(recurring_rule_id);
CREATE INDEX IF NOT EXISTS idx_kaban_transactions_source ON kaban_transactions(source);

-- 4. Enable RLS
ALTER TABLE recurring_rules ENABLE ROW LEVEL SECURITY;

-- 5. RLS Policies for recurring_rules
DROP POLICY IF EXISTS "Users can view own recurring rules" ON recurring_rules;
CREATE POLICY "Users can view own recurring rules" ON recurring_rules
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own recurring rules" ON recurring_rules;
CREATE POLICY "Users can create own recurring rules" ON recurring_rules
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own recurring rules" ON recurring_rules;
CREATE POLICY "Users can update own recurring rules" ON recurring_rules
    FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own recurring rules" ON recurring_rules;
CREATE POLICY "Users can delete own recurring rules" ON recurring_rules
    FOR DELETE USING (auth.uid() = user_id);

-- 6. Grant access to authenticated users
GRANT ALL ON recurring_rules TO authenticated;

-- =====================================================
-- DONE! 
-- After running this, deploy the backend changes.
-- =====================================================
