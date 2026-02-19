"""
Admin Router for KabanKo
Internal dashboard API endpoints with admin-only access.

Endpoints:
- GET /admin/stats/overview - KPI cards data
- GET /admin/stats/signups - Signup trend (last 30 days)
- GET /admin/stats/retention - Retention funnel
- GET /admin/stats/features - Feature usage (last 7 days)
- GET /admin/users/recent - Recent signups with milestones
- GET /admin/health - System health metrics
"""

from fastapi import APIRouter, Depends, HTTPException
from dependencies import get_user_profile, supabase
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================
# Admin Authentication Dependency
# ============================================
async def require_admin(profile=Depends(get_user_profile)):
    """Dependency that verifies the user is an admin."""
    if not profile.get('is_admin', False):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Log admin access
    logger.info(f"Admin dashboard accessed by user {profile.get('id')}")
    return profile


# ============================================
# KPI Overview
# ============================================
@router.get("/stats/overview")
async def get_overview_stats(_admin=Depends(require_admin)):
    """Get KPI cards data: total users, active (7d), new today, PRO threshold."""
    try:
        # Total users
        total_res = supabase.table('profiles').select('id', count='exact').execute()
        total_users = total_res.count or 0
        
        # New today
        today = datetime.now().date().isoformat()
        new_today_res = supabase.table('profiles').select('id', count='exact').gte('created_at', today).execute()
        new_today = new_today_res.count or 0
        
        # Active users (7-day) - distinct users with analytics events
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        active_res = supabase.table('analytics_events').select('user_id').gte('created_at', seven_days_ago).execute()
        active_user_ids = set(row['user_id'] for row in (active_res.data or []))
        active_7d = len(active_user_ids)
        
        return {
            "total_users": total_users,
            "active_7d": active_7d,
            "new_today": new_today,
            "pro_threshold": 500,
        }
    except Exception as e:
        logger.error(f"Error fetching overview stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch overview stats")


# ============================================
# Signup Trend (Last 30 Days)
# ============================================
@router.get("/stats/signups")
async def get_signup_trend(_admin=Depends(require_admin)):
    """Get daily signups for the last 30 days."""
    try:
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        # Get all profiles created in last 30 days
        res = supabase.table('profiles').select('created_at').gte('created_at', thirty_days_ago).execute()
        
        # Group by date
        daily_counts: dict[str, int] = {}
        for row in (res.data or []):
            if row.get('created_at'):
                date_str = row['created_at'][:10]  # YYYY-MM-DD
                daily_counts[date_str] = daily_counts.get(date_str, 0) + 1
        
        # Fill in missing days with 0
        result = []
        for i in range(30):
            date = (datetime.now() - timedelta(days=29-i)).date()
            date_str = date.isoformat()
            result.append({
                "date": date_str,
                "count": daily_counts.get(date_str, 0)
            })
        
        return result
    except Exception as e:
        logger.error(f"Error fetching signup trend: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch signup trend")


# ============================================
# Retention Funnel
# ============================================
@router.get("/stats/retention")
async def get_retention_funnel(_admin=Depends(require_admin)):
    """Get retention funnel metrics for the last 30 days."""
    try:
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        # Signups (from profiles, since signup_completed may not exist for all)
        signups_res = supabase.table('profiles').select('id', count='exact').gte('created_at', thirty_days_ago).execute()
        signups = signups_res.count or 0
        
        # Helper to count distinct users for an event
        def count_event(event_name: str) -> int:
            res = supabase.table('analytics_events').select('user_id').eq('event_name', event_name).gte('created_at', thirty_days_ago).execute()
            return len(set(row['user_id'] for row in (res.data or [])))
        
        first_txn = count_event('first_transaction_logged')
        second_txn = count_event('second_transaction_same_day')
        day_2 = count_event('day_2_return')
        week_1 = count_event('week_1_return')
        
        return {
            "signups": signups,
            "first_txn": first_txn,
            "second_txn": second_txn,
            "day_2_return": day_2,
            "week_1_return": week_1,
            "first_txn_pct": round(first_txn / signups * 100, 1) if signups > 0 else 0,
            "second_txn_pct": round(second_txn / signups * 100, 1) if signups > 0 else 0,
            "day_2_pct": round(day_2 / signups * 100, 1) if signups > 0 else 0,
            "week_1_pct": round(week_1 / signups * 100, 1) if signups > 0 else 0,
        }
    except Exception as e:
        logger.error(f"Error fetching retention funnel: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch retention funnel")


# ============================================
# Feature Usage (Last 7 Days)
# ============================================
@router.get("/stats/features")
async def get_feature_usage(_admin=Depends(require_admin)):
    """Get feature usage metrics for the last 7 days."""
    try:
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        # Get all events in the last 7 days
        res = supabase.table('analytics_events').select('event_name, user_id').gte('created_at', seven_days_ago).execute()
        
        # Count distinct users per event
        event_users: dict[str, set] = {}
        total_users: set = set()
        
        for row in (res.data or []):
            event = row.get('event_name')
            user_id = row.get('user_id')
            if event and user_id:
                if event not in event_users:
                    event_users[event] = set()
                event_users[event].add(user_id)
                total_users.add(user_id)
        
        total_active = len(total_users)
        
        # Map events to feature names for display
        feature_mapping = {
            'first_transaction_logged': 'Kaban Transactions',
            'quick_add_used': 'Quick Add',
            'sahod_setup_completed': 'Sobre Setup',
            'sahod_envelope_created': 'Sobre Envelopes',
            'recurring_rule_created': 'Recurring Rules',
        }
        
        # Count Pautang usage (from utang table)
        pautang_res = supabase.table('utang').select('lender_id', count='exact').gte('created_at', seven_days_ago).execute()
        pautang_users = len(set(row['lender_id'] for row in (pautang_res.data or []))) if pautang_res.data else 0
        
        result = []
        for event_name, display_name in feature_mapping.items():
            count = len(event_users.get(event_name, set()))
            pct = round(count / total_active * 100, 1) if total_active > 0 else 0
            result.append({
                "feature": display_name,
                "event": event_name,
                "count": count,
                "pct": pct,
            })
        
        # Add Pautang separately
        result.append({
            "feature": "Pautang",
            "event": "utang_created",
            "count": pautang_users,
            "pct": round(pautang_users / total_active * 100, 1) if total_active > 0 else 0,
        })
        
        # Sort by count descending
        result.sort(key=lambda x: x['count'], reverse=True)
        
        return {
            "total_active_users": total_active,
            "features": result,
        }
    except Exception as e:
        logger.error(f"Error fetching feature usage: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch feature usage")


# ============================================
# Recent Signups
# ============================================
@router.get("/users/recent")
async def get_recent_signups(_admin=Depends(require_admin)):
    """Get recent signups with milestone completion status."""
    try:
        # Get last 20 profiles
        profiles_res = supabase.table('profiles').select('id, email, created_at, pay_cycle_type, tier').order('created_at', desc=True).limit(20).execute()
        
        # Get first_transaction_logged events to check milestone
        txn_events_res = supabase.table('analytics_events').select('user_id').eq('event_name', 'first_transaction_logged').execute()
        users_with_first_txn = set(row['user_id'] for row in (txn_events_res.data or []))
        
        # Get day_2_return events
        day2_events_res = supabase.table('analytics_events').select('user_id').eq('event_name', 'day_2_return').execute()
        users_with_day2 = set(row['user_id'] for row in (day2_events_res.data or []))
        
        result = []
        for profile in (profiles_res.data or []):
            user_id = profile.get('id')
            email = profile.get('email', '')
            
            # Mask email: j***@gmail.com
            if email and '@' in email:
                local, domain = email.split('@', 1)
                masked_email = f"{local[0]}***@{domain}" if local else f"***@{domain}"
            else:
                masked_email = "***"
            
            # Calculate if "too early" for Day 2 (signed up < 48h ago)
            created_at = profile.get('created_at')
            too_early_for_day2 = False
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    too_early_for_day2 = (datetime.now(created_dt.tzinfo) - created_dt).days < 2
                except:
                    pass
            
            result.append({
                "email_masked": masked_email,
                "created_at": created_at,
                "has_first_txn": user_id in users_with_first_txn,
                "has_day2": user_id in users_with_day2 if not too_early_for_day2 else None,  # None = too early
                "has_pay_cycle": bool(profile.get('pay_cycle_type')),
                "tier": profile.get('tier', 'free'),
            })
        
        return result
    except Exception as e:
        logger.error(f"Error fetching recent signups: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch recent signups")


# ============================================
# System Health
# ============================================
@router.get("/health")
async def get_system_health(_admin=Depends(require_admin)):
    """Get system health metrics."""
    try:
        # API is online if we got here
        api_status = "online"
        
        # Count errors in last 24h (would need error logging table - for now, return placeholder)
        # In production, you'd query an error_logs table or use external monitoring
        
        # DB connection test
        db_status = "online"
        try:
            supabase.table('profiles').select('id').limit(1).execute()
        except:
            db_status = "offline"
        
        return {
            "api_status": api_status,
            "db_status": db_status,
            "avg_response_ms": None,  # Would need middleware logging
            "error_rate_24h": None,   # Would need error tracking
            "checked_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error fetching system health: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch system health")
