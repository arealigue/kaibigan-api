-- Amount Learning: Smart amount suggestions based on user spending patterns
-- Created: January 21, 2026
-- Part of: Quick Transaction Entry Phase 3

-- ==============================================
-- Add columns to track amount suggestions
-- ==============================================
ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS suggested_amount NUMERIC(12,2),
ADD COLUMN IF NOT EXISTS suggestion_shown_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS suggestion_dismissed BOOLEAN DEFAULT false;

-- Add comment for documentation
COMMENT ON COLUMN quick_add_shortcuts.suggested_amount IS 'AI-suggested amount based on user spending median';
COMMENT ON COLUMN quick_add_shortcuts.suggestion_shown_at IS 'When the suggestion was last shown to user';
COMMENT ON COLUMN quick_add_shortcuts.suggestion_dismissed IS 'User dismissed this suggestion, dont show again until amount changes significantly';

-- ==============================================
-- Function: Calculate suggested amount from transactions
-- ==============================================
CREATE OR REPLACE FUNCTION calculate_suggested_amount(
  p_user_id UUID,
  p_category_id UUID,
  p_label TEXT,
  p_min_transactions INTEGER DEFAULT 5
)
RETURNS NUMERIC AS $$
DECLARE
  v_median NUMERIC;
  v_similar_count INTEGER;
BEGIN
  -- First try to find transactions with similar description/label
  WITH similar_transactions AS (
    SELECT amount
    FROM transactions
    WHERE user_id = p_user_id
      AND category_id = p_category_id
      AND type = 'expense'
      AND LOWER(description) LIKE '%' || LOWER(p_label) || '%'
      AND created_at > NOW() - INTERVAL '60 days'
    ORDER BY created_at DESC
    LIMIT 30
  )
  SELECT COUNT(*) INTO v_similar_count FROM similar_transactions;

  -- If we have enough similar transactions, use those
  IF v_similar_count >= p_min_transactions THEN
    WITH similar_transactions AS (
      SELECT amount
      FROM transactions
      WHERE user_id = p_user_id
        AND category_id = p_category_id
        AND type = 'expense'
        AND LOWER(description) LIKE '%' || LOWER(p_label) || '%'
        AND created_at > NOW() - INTERVAL '60 days'
      ORDER BY created_at DESC
      LIMIT 30
    )
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amount)
    INTO v_median
    FROM similar_transactions;
    
    -- Round to nearest 5
    RETURN ROUND(v_median / 5) * 5;
  END IF;

  -- Otherwise, try category-level median
  WITH category_transactions AS (
    SELECT amount
    FROM transactions
    WHERE user_id = p_user_id
      AND category_id = p_category_id
      AND type = 'expense'
      AND created_at > NOW() - INTERVAL '60 days'
    ORDER BY created_at DESC
    LIMIT 30
  )
  SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amount)
  INTO v_median
  FROM category_transactions
  HAVING COUNT(*) >= p_min_transactions;

  IF v_median IS NOT NULL THEN
    -- Round to nearest 5
    RETURN ROUND(v_median / 5) * 5;
  END IF;

  -- Not enough data
  RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
