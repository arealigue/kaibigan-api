-- Quick Add Shortcuts: User-customizable transaction shortcuts
-- Created: January 21, 2026
-- Part of: Quick Transaction Entry Phase 2

-- ==============================================
-- Table: quick_add_shortcuts
-- ==============================================
CREATE TABLE IF NOT EXISTS quick_add_shortcuts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  emoji TEXT NOT NULL DEFAULT '💰',
  label TEXT NOT NULL,
  default_amount NUMERIC(12,2) NOT NULL CHECK (default_amount > 0),
  category_id UUID REFERENCES expense_categories(id) ON DELETE SET NULL,
  is_system_default BOOLEAN DEFAULT false,
  usage_count INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Index for fast user-specific queries
CREATE INDEX IF NOT EXISTS idx_quick_add_shortcuts_user_id 
  ON quick_add_shortcuts(user_id);

-- Index for ordering by usage
CREATE INDEX IF NOT EXISTS idx_quick_add_shortcuts_usage 
  ON quick_add_shortcuts(user_id, usage_count DESC);

-- ==============================================
-- Row Level Security
-- ==============================================
ALTER TABLE quick_add_shortcuts ENABLE ROW LEVEL SECURITY;

-- Users can only see their own shortcuts
CREATE POLICY "Users can view their own shortcuts"
  ON quick_add_shortcuts
  FOR SELECT
  USING (auth.uid() = user_id);

-- Users can only insert their own shortcuts
CREATE POLICY "Users can create their own shortcuts"
  ON quick_add_shortcuts
  FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- Users can only update their own shortcuts
CREATE POLICY "Users can update their own shortcuts"
  ON quick_add_shortcuts
  FOR UPDATE
  USING (auth.uid() = user_id);

-- Users can only delete their own shortcuts
CREATE POLICY "Users can delete their own shortcuts"
  ON quick_add_shortcuts
  FOR DELETE
  USING (auth.uid() = user_id);

-- ==============================================
-- Function: Update timestamp on update
-- ==============================================
CREATE OR REPLACE FUNCTION update_quick_add_shortcut_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_quick_add_shortcut_timestamp
  BEFORE UPDATE ON quick_add_shortcuts
  FOR EACH ROW
  EXECUTE FUNCTION update_quick_add_shortcut_timestamp();

-- ==============================================
-- Function: Limit shortcuts per user (max 12)
-- ==============================================
CREATE OR REPLACE FUNCTION check_max_shortcuts()
RETURNS TRIGGER AS $$
BEGIN
  IF (SELECT COUNT(*) FROM quick_add_shortcuts WHERE user_id = NEW.user_id) >= 12 THEN
    RAISE EXCEPTION 'Maximum of 12 shortcuts allowed per user';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_check_max_shortcuts
  BEFORE INSERT ON quick_add_shortcuts
  FOR EACH ROW
  EXECUTE FUNCTION check_max_shortcuts();
