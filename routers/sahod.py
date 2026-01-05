"""
SAHOD Module Router - Envelope Budgeting System
Handles pay cycles, envelopes, allocations, and dashboard
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Annotated, Optional, List
from dependencies import get_user_profile, supabase, limiter
import datetime
from dateutil.relativedelta import relativedelta

# Router configuration
router = APIRouter(
    prefix="/sahod",
    tags=["Sahod - Envelope Budgeting"],
    responses={401: {"description": "Unauthorized"}}
)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class PayCycleCreate(BaseModel):
    cycle_name: Optional[str] = "My Salary"
    expected_amount: float
    frequency: str  # 'monthly', 'bimonthly', 'weekly'
    pay_day_1: Optional[int] = None  # 1-31 for monthly/bimonthly
    pay_day_2: Optional[int] = None  # 1-31 for bimonthly (katapusan)
    pay_day_of_week: Optional[int] = None  # 1-7 for weekly (Mon=1)


class PayCycleUpdate(BaseModel):
    cycle_name: Optional[str] = None
    expected_amount: Optional[float] = None
    frequency: Optional[str] = None
    pay_day_1: Optional[int] = None
    pay_day_2: Optional[int] = None
    pay_day_of_week: Optional[int] = None
    is_active: Optional[bool] = None


class EnvelopeCreate(BaseModel):
    name: str
    emoji: Optional[str] = "📦"
    color: Optional[str] = "#6366f1"
    target_amount: Optional[float] = None
    is_rollover: Optional[bool] = False


class EnvelopeUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    color: Optional[str] = None
    target_amount: Optional[float] = None
    is_rollover: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class EnvelopeReorder(BaseModel):
    envelope_ids: List[str]  # Ordered list of envelope IDs


class AllocationItem(BaseModel):
    envelope_id: str
    allocated_amount: float
    target_percentage: Optional[float] = None


class FillAllocationsRequest(BaseModel):
    pay_cycle_instance_id: str
    allocations: List[AllocationItem]


class ConfirmInstanceRequest(BaseModel):
    actual_amount: Optional[float] = None  # If different from expected


class AllocationUpdate(BaseModel):
    allocated_amount: Optional[float] = None
    target_percentage: Optional[float] = None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_period_for_date(frequency: str, pay_day_1: int, pay_day_2: Optional[int], target_date: datetime.date) -> tuple:
    """
    Calculate period_start, period_end, expected_pay_date, and payday_type for a given date.
    Returns (period_start, period_end, expected_pay_date, payday_type)
    
    payday_type: 'single' for monthly/weekly, 'kinsenas' or 'katapusan' for bimonthly
    """
    payday_type = 'single'  # Default for monthly/weekly
    
    if frequency == 'monthly':
        # Period: pay_day_1 of current month to pay_day_1 of next month - 1
        if target_date.day >= pay_day_1:
            period_start = target_date.replace(day=min(pay_day_1, _last_day_of_month(target_date)))
            next_month = target_date + relativedelta(months=1)
            period_end = next_month.replace(day=min(pay_day_1, _last_day_of_month(next_month))) - datetime.timedelta(days=1)
        else:
            prev_month = target_date - relativedelta(months=1)
            period_start = prev_month.replace(day=min(pay_day_1, _last_day_of_month(prev_month)))
            period_end = target_date.replace(day=min(pay_day_1, _last_day_of_month(target_date))) - datetime.timedelta(days=1)
        expected_pay_date = period_start
        
    elif frequency == 'bimonthly':
        # Two periods per month: pay_day_1 to pay_day_2-1, pay_day_2 to pay_day_1-1 (next month)
        day1 = min(pay_day_1, _last_day_of_month(target_date))
        day2 = min(pay_day_2, _last_day_of_month(target_date))
        
        if target_date.day >= day2:
            # In second half (katapusan period)
            period_start = target_date.replace(day=day2)
            next_month = target_date + relativedelta(months=1)
            period_end = next_month.replace(day=min(pay_day_1, _last_day_of_month(next_month))) - datetime.timedelta(days=1)
            expected_pay_date = period_start
            payday_type = 'katapusan'
        elif target_date.day >= day1:
            # In first half (kinsenas period)
            period_start = target_date.replace(day=day1)
            period_end = target_date.replace(day=day2) - datetime.timedelta(days=1)
            expected_pay_date = period_start
            payday_type = 'kinsenas'
        else:
            # Before first payday - in previous katapusan period
            prev_month = target_date - relativedelta(months=1)
            day2_prev = min(pay_day_2, _last_day_of_month(prev_month))
            period_start = prev_month.replace(day=day2_prev)
            period_end = target_date.replace(day=day1) - datetime.timedelta(days=1)
            expected_pay_date = period_start
            payday_type = 'katapusan'
    else:
        # Weekly - not implemented in MVP UI but schema-ready
        raise HTTPException(status_code=400, detail="Weekly frequency not yet supported in MVP")
    
    return period_start, period_end, expected_pay_date, payday_type


def _last_day_of_month(date: datetime.date) -> int:
    """Get last day of the month for a given date."""
    next_month = date.replace(day=28) + datetime.timedelta(days=4)
    return (next_month - datetime.timedelta(days=next_month.day)).day


def calculate_safe_daily_spend(remaining_budget: float, days_left: int) -> float:
    """
    Calculate safe daily spend with edge case handling.
    Rules:
    1. If days_left <= 0 → 0 (period ended)
    2. If remaining_budget <= 0 → 0 (stop spending)
    3. Else → remaining_budget / days_left
    """
    if days_left <= 0:
        return 0.0
    if remaining_budget <= 0:
        return 0.0
    return round(remaining_budget / days_left, 2)


def process_completed_period_rollover(user_id: str, completed_instance_id: str):
    """
    Process rollover for a completed period.
    Called automatically when a new period starts and the previous period
    hasn't been processed yet.
    
    For each envelope with is_rollover=true:
    - Calculate remaining = (allocated + rollover) - spent
    - Add remaining to envelope's cookie_jar
    - Mark the instance as rollover_processed
    """
    try:
        # Check if already processed
        instance_check = supabase.table('sahod_pay_cycle_instances') \
            .select('rollover_processed') \
            .eq('id', completed_instance_id) \
            .single() \
            .execute()
        
        if instance_check.data and instance_check.data.get('rollover_processed'):
            return  # Already processed, skip
        
        # Get allocations for this completed period with envelope info
        allocations = supabase.table('sahod_allocations') \
            .select('*, sahod_envelopes(id, name, is_rollover, cookie_jar)') \
            .eq('pay_cycle_instance_id', completed_instance_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not allocations.data:
            return
        
        for alloc in allocations.data:
            envelope = alloc.get('sahod_envelopes', {})
            
            # Only process envelopes with is_rollover enabled
            if not envelope.get('is_rollover', False):
                continue
            
            # Calculate remaining
            allocated = alloc.get('allocated_amount', 0) or 0
            rollover = alloc.get('rollover_amount', 0) or 0
            spent = alloc.get('cached_spent', 0) or 0
            remaining = (allocated + rollover) - spent
            
            # Only add positive remainders to cookie jar
            if remaining > 0:
                current_cookie_jar = envelope.get('cookie_jar', 0) or 0
                new_cookie_jar = current_cookie_jar + remaining
                
                # Update the envelope's cookie_jar
                supabase.table('sahod_envelopes') \
                    .update({'cookie_jar': new_cookie_jar}) \
                    .eq('id', envelope['id']) \
                    .eq('user_id', user_id) \
                    .execute()
        
        # Mark instance as processed
        supabase.table('sahod_pay_cycle_instances') \
            .update({'rollover_processed': True}) \
            .eq('id', completed_instance_id) \
            .execute()
            
    except Exception as e:
        print(f"Process Rollover Error: {e}")
        # Don't raise - this is a best-effort operation


# ============================================================================
# PAY CYCLES ENDPOINTS (Templates)
# ============================================================================

@router.post("/pay-cycles")
@limiter.limit("10/minute")
async def create_pay_cycle(
    request: Request,
    pay_cycle: PayCycleCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new pay cycle template."""
    user_id = profile['id']
    
    # Validate frequency-specific fields
    if pay_cycle.frequency in ('monthly', 'bimonthly'):
        if not pay_cycle.pay_day_1:
            raise HTTPException(status_code=400, detail="pay_day_1 is required for monthly/bimonthly frequency")
        if pay_cycle.frequency == 'bimonthly' and not pay_cycle.pay_day_2:
            raise HTTPException(status_code=400, detail="pay_day_2 is required for bimonthly frequency")
    elif pay_cycle.frequency == 'weekly':
        if not pay_cycle.pay_day_of_week:
            raise HTTPException(status_code=400, detail="pay_day_of_week is required for weekly frequency")
    else:
        raise HTTPException(status_code=400, detail="Invalid frequency. Use 'monthly', 'bimonthly', or 'weekly'")
    
    try:
        data = pay_cycle.model_dump()
        data['user_id'] = user_id
        
        result = supabase.table('sahod_pay_cycles').insert(data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create pay cycle")
        
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        print(f"Create Pay Cycle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pay-cycles")
async def get_pay_cycles(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """List all pay cycle templates for the user."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_pay_cycles') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .order('created_at', desc=True) \
            .execute()
        
        return result.data
    except Exception as e:
        print(f"Get Pay Cycles Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pay-cycles/{pay_cycle_id}")
async def get_pay_cycle(
    pay_cycle_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get a single pay cycle template."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_pay_cycles') \
            .select('*') \
            .eq('id', pay_cycle_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Pay cycle not found")
        
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get Pay Cycle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/pay-cycles/{pay_cycle_id}")
async def update_pay_cycle(
    pay_cycle_id: str,
    pay_cycle: PayCycleUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update a pay cycle template."""
    user_id = profile['id']
    
    try:
        update_data = {k: v for k, v in pay_cycle.model_dump().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        update_data['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Check if pay_day fields are being updated - if so, invalidate unconfirmed instances
        pay_day_fields = ['pay_day_1', 'pay_day_2', 'frequency']
        if any(field in update_data for field in pay_day_fields):
            # Delete unconfirmed instances for this pay cycle so they get recalculated
            supabase.table('sahod_pay_cycle_instances') \
                .delete() \
                .eq('pay_cycle_id', pay_cycle_id) \
                .eq('user_id', user_id) \
                .eq('is_assumed', True) \
                .is_('confirmed_at', 'null') \
                .execute()
        
        result = supabase.table('sahod_pay_cycles') \
            .update(update_data) \
            .eq('id', pay_cycle_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Pay cycle not found")
        
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update Pay Cycle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pay-cycles/{pay_cycle_id}")
async def delete_pay_cycle(
    pay_cycle_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Soft delete a pay cycle template."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_pay_cycles') \
            .update({'is_active': False, 'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}) \
            .eq('id', pay_cycle_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Pay cycle not found")
        
        return {"message": "Pay cycle deleted"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Delete Pay Cycle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PAY CYCLE INSTANCES ENDPOINTS (Events)
# ============================================================================

@router.get("/instances/current")
async def get_current_instance(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Get current period instance. Creates one if it doesn't exist (assumed).
    Returns the instance for the period containing today's date.
    """
    user_id = profile['id']
    today = datetime.date.today()
    
    try:
        # First, get user's active pay cycle
        cycle_res = supabase.table('sahod_pay_cycles') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .limit(1) \
            .execute()
        
        if not cycle_res.data:
            return {"instance": None, "needs_setup": True}
        
        pay_cycle = cycle_res.data[0]
        
        # Calculate what the period SHOULD be based on current pay cycle settings
        correct_period_start, correct_period_end, correct_expected_pay_date, correct_payday_type = get_period_for_date(
            pay_cycle['frequency'],
            pay_cycle['pay_day_1'],
            pay_cycle.get('pay_day_2'),
            today
        )
        
        # Check for existing instance containing today
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('pay_cycle_id', pay_cycle['id']) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .limit(1) \
            .execute()
        
        if instance_res.data:
            instance = instance_res.data[0]
            
            # Check if existing instance matches the correct period (pay_day may have changed)
            # If dates mismatch and instance is unconfirmed, delete and recreate
            if (instance['is_assumed'] and 
                instance.get('confirmed_at') is None and
                (instance['period_start'] != str(correct_period_start) or 
                 instance['period_end'] != str(correct_period_end))):
                # Delete mismatched instance
                supabase.table('sahod_pay_cycle_instances') \
                    .delete() \
                    .eq('id', instance['id']) \
                    .execute()
                instance = None  # Force recreation below
        else:
            instance = None
            
        if instance is None:
            # Before creating new instance, process rollover for completed periods
            # Find the most recent completed (confirmed) period that hasn't been processed
            completed_periods = supabase.table('sahod_pay_cycle_instances') \
                .select('id, period_end, rollover_processed') \
                .eq('user_id', user_id) \
                .eq('pay_cycle_id', pay_cycle['id']) \
                .lt('period_end', str(today)) \
                .eq('is_assumed', False) \
                .order('period_end', desc=True) \
                .limit(1) \
                .execute()
            
            if completed_periods.data:
                last_period = completed_periods.data[0]
                if not last_period.get('rollover_processed'):
                    process_completed_period_rollover(user_id, last_period['id'])
            
            # Create new instance for current period
            new_instance = {
                'user_id': user_id,
                'pay_cycle_id': pay_cycle['id'],
                'expected_amount': pay_cycle['expected_amount'],
                'period_start': str(correct_period_start),
                'period_end': str(correct_period_end),
                'expected_pay_date': str(correct_expected_pay_date),
                'payday_type': correct_payday_type,  # NEW: Track kinsenas/katapusan
                'is_assumed': True
            }
            
            create_res = supabase.table('sahod_pay_cycle_instances').insert(new_instance).execute()
            
            if not create_res.data:
                raise HTTPException(status_code=500, detail="Failed to create pay cycle instance")
            
            instance = create_res.data[0]
        
        # Calculate days remaining
        period_end = datetime.datetime.strptime(instance['period_end'], '%Y-%m-%d').date()
        days_remaining = (period_end - today).days + 1  # Include today
        
        return {
            "instance": instance,
            "days_remaining": max(0, days_remaining),
            "needs_setup": False,
            "pay_cycle": pay_cycle
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get Current Instance Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instances/pending")
async def get_pending_instances(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all pending (assumed) instances that need confirmation."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_pay_cycle_instances') \
            .select('*, sahod_sahod_pay_cycles(cycle_name, frequency)') \
            .eq('user_id', user_id) \
            .eq('is_assumed', True) \
            .order('period_start', desc=True) \
            .execute()
        
        return result.data
    except Exception as e:
        print(f"Get Pending Instances Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/instances/{instance_id}/confirm")
@limiter.limit("20/minute")
async def confirm_instance(
    request: Request,
    instance_id: str,
    confirm_request: ConfirmInstanceRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Confirm sahod received (Tap to Fund step 1)."""
    user_id = profile['id']
    
    try:
        # Get instance
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('id', instance_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not instance_res.data:
            raise HTTPException(status_code=404, detail="Instance not found")
        
        instance = instance_res.data
        
        update_data = {
            'is_assumed': False,
            'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        if confirm_request.actual_amount is not None:
            update_data['actual_amount'] = confirm_request.actual_amount
        else:
            update_data['actual_amount'] = instance['expected_amount']
        
        result = supabase.table('sahod_pay_cycle_instances') \
            .update(update_data) \
            .eq('id', instance_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to confirm instance")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Confirm Instance Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instances/history")
async def get_instance_history(
    profile: Annotated[dict, Depends(get_user_profile)],
    limit: int = 10
):
    """Get past pay cycle instances."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_pay_cycle_instances') \
            .select('*, sahod_pay_cycles(cycle_name)') \
            .eq('user_id', user_id) \
            .order('period_start', desc=True) \
            .limit(limit) \
            .execute()
        
        return result.data
    except Exception as e:
        print(f"Get Instance History Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENVELOPES ENDPOINTS
# ============================================================================

@router.post("/envelopes")
@limiter.limit("20/minute")
async def create_envelope(
    request: Request,
    envelope: EnvelopeCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new envelope."""
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    
    try:
        # Check envelope limit for free users
        if tier != 'pro':
            count_res = supabase.table('sahod_envelopes') \
                .select('id', count='exact') \
                .eq('user_id', user_id) \
                .eq('is_active', True) \
                .execute()
            
            if count_res.count and count_res.count >= 5:
                raise HTTPException(
                    status_code=403, 
                    detail="Free users can create up to 5 envelopes. Upgrade to PRO for unlimited."
                )
        
        # Get max sort_order
        max_order_res = supabase.table('sahod_envelopes') \
            .select('sort_order') \
            .eq('user_id', user_id) \
            .order('sort_order', desc=True) \
            .limit(1) \
            .execute()
        
        next_order = (max_order_res.data[0]['sort_order'] + 1) if max_order_res.data else 0
        
        data = envelope.model_dump()
        data['user_id'] = user_id
        data['sort_order'] = next_order
        
        # Only PRO users can enable rollover
        if tier != 'pro':
            data['is_rollover'] = False
        
        result = supabase.table('sahod_envelopes').insert(data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create envelope")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Create Envelope Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/envelopes")
async def get_envelopes(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """List user's envelopes (base info only)."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_envelopes') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .order('sort_order') \
            .execute()
        
        return result.data
    except Exception as e:
        print(f"Get Envelopes Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/envelopes/{envelope_id}")
async def get_envelope(
    envelope_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get single envelope with transactions for current period."""
    user_id = profile['id']
    today = datetime.date.today()
    
    try:
        # Get envelope
        envelope_res = supabase.table('sahod_envelopes') \
            .select('*') \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not envelope_res.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        envelope = envelope_res.data
        
        # Get current instance
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('user_id', user_id) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .limit(1) \
            .execute()
        
        allocation = None
        transactions = []
        
        if instance_res.data:
            instance = instance_res.data[0]
            
            # Get allocation for this envelope in current period
            alloc_res = supabase.table('sahod_allocations') \
                .select('*') \
                .eq('pay_cycle_instance_id', instance['id']) \
                .eq('envelope_id', envelope_id) \
                .limit(1) \
                .execute()
            
            if alloc_res.data:
                allocation = alloc_res.data[0]
            
            # Get transactions for this envelope in current period
            tx_res = supabase.table('kaban_transactions') \
                .select('*, expense_categories(name, emoji)') \
                .eq('user_id', user_id) \
                .eq('sahod_envelope_id', envelope_id) \
                .gte('transaction_date', instance['period_start']) \
                .lte('transaction_date', instance['period_end']) \
                .order('transaction_date', desc=True) \
                .execute()
            
            transactions = tx_res.data
        
        return {
            "envelope": envelope,
            "allocation": allocation,
            "transactions": transactions
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get Envelope Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/envelopes/{envelope_id}")
async def update_envelope(
    envelope_id: str,
    envelope: EnvelopeUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update an envelope."""
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    
    try:
        update_data = {k: v for k, v in envelope.model_dump().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Only PRO users can enable rollover
        if 'is_rollover' in update_data and update_data['is_rollover'] and tier != 'pro':
            raise HTTPException(status_code=403, detail="Rollover is a PRO feature")
        
        update_data['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        result = supabase.table('sahod_envelopes') \
            .update(update_data) \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update Envelope Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/envelopes/{envelope_id}")
async def delete_envelope(
    envelope_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Soft delete an envelope."""
    user_id = profile['id']
    
    try:
        result = supabase.table('sahod_envelopes') \
            .update({
                'is_active': False, 
                'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }) \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        return {"message": "Envelope deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Delete Envelope Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/envelopes/reorder")
async def reorder_envelopes(
    reorder: EnvelopeReorder,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update sort order for envelopes."""
    user_id = profile['id']
    
    try:
        for idx, envelope_id in enumerate(reorder.envelope_ids):
            supabase.table('sahod_envelopes') \
                .update({'sort_order': idx}) \
                .eq('id', envelope_id) \
                .eq('user_id', user_id) \
                .execute()
        
        return {"message": "Envelopes reordered"}
    except Exception as e:
        print(f"Reorder Envelopes Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ALLOCATIONS ENDPOINTS
# ============================================================================

@router.post("/allocations/fill")
@limiter.limit("10/minute")
async def fill_allocations(
    request: Request,
    fill_request: FillAllocationsRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Fill envelopes for current instance (Tap to Fund step 2).
    Creates allocation records with frozen amounts.
    """
    user_id = profile['id']
    
    try:
        # Verify instance belongs to user
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('id', fill_request.pay_cycle_instance_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not instance_res.data:
            raise HTTPException(status_code=404, detail="Instance not found")
        
        instance = instance_res.data
        
        # Delete existing allocations for this instance (allows re-fill before confirmation)
        supabase.table('sahod_allocations') \
            .delete() \
            .eq('pay_cycle_instance_id', instance['id']) \
            .eq('user_id', user_id) \
            .execute()
        
        # Create new allocations
        created = []
        for alloc in fill_request.allocations:
            # Verify envelope belongs to user
            env_check = supabase.table('sahod_envelopes') \
                .select('id, is_rollover, cookie_jar') \
                .eq('id', alloc.envelope_id) \
                .eq('user_id', user_id) \
                .single() \
                .execute()
            
            if not env_check.data:
                continue  # Skip invalid envelopes
            
            envelope = env_check.data
            
            # Calculate rollover from previous period (PRO only)
            rollover_amount = 0.0
            if envelope.get('is_rollover'):
                # Get previous instance
                prev_instance = supabase.table('sahod_pay_cycle_instances') \
                    .select('id') \
                    .eq('user_id', user_id) \
                    .lt('period_start', instance['period_start']) \
                    .order('period_start', desc=True) \
                    .limit(1) \
                    .execute()
                
                if prev_instance.data:
                    prev_alloc = supabase.table('sahod_allocations') \
                        .select('allocated_amount, cached_spent, rollover_amount') \
                        .eq('pay_cycle_instance_id', prev_instance.data[0]['id']) \
                        .eq('envelope_id', alloc.envelope_id) \
                        .single() \
                        .execute()
                    
                    if prev_alloc.data:
                        prev = prev_alloc.data
                        remaining = (prev['allocated_amount'] + prev['rollover_amount']) - prev['cached_spent']
                        rollover_amount = max(0, remaining)
            
            alloc_data = {
                'user_id': user_id,
                'pay_cycle_instance_id': instance['id'],
                'envelope_id': alloc.envelope_id,
                'allocated_amount': alloc.allocated_amount,
                'target_percentage': alloc.target_percentage,
                'rollover_amount': rollover_amount,
                'cached_spent': 0
            }
            
            result = supabase.table('sahod_allocations').insert(alloc_data).execute()
            if result.data:
                created.append(result.data[0])
        
        return {"allocations": created, "count": len(created)}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Fill Allocations Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/allocations/current")
async def get_current_allocations(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get allocations for current period."""
    user_id = profile['id']
    today = datetime.date.today()
    
    try:
        # Get current instance
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('id') \
            .eq('user_id', user_id) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .limit(1) \
            .execute()
        
        if not instance_res.data:
            return []
        
        instance_id = instance_res.data[0]['id']
        
        result = supabase.table('sahod_allocations') \
            .select('*, sahod_envelopes(name, emoji, color, is_rollover, cookie_jar)') \
            .eq('pay_cycle_instance_id', instance_id) \
            .eq('user_id', user_id) \
            .execute()
        
        return result.data
    except Exception as e:
        print(f"Get Current Allocations Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/allocations/{allocation_id}")
async def update_allocation(
    allocation_id: str,
    allocation: AllocationUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update a single allocation."""
    user_id = profile['id']
    
    try:
        update_data = {k: v for k, v in allocation.model_dump().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        result = supabase.table('sahod_allocations') \
            .update(update_data) \
            .eq('id', allocation_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Allocation not found")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update Allocation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COOKIE JAR / ROLLOVER ENDPOINTS
# ============================================================================

class UseFromCookieJarRequest(BaseModel):
    envelope_id: str
    amount: float  # Amount to withdraw from Cookie Jar


@router.post("/allocations/process-rollover")
async def process_rollover(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Process rollover for a completed period.
    Called when a period ends to:
    1. Calculate remaining amount for each envelope with is_rollover=true
    2. Add to the envelope's cookie_jar (lifetime accumulation)
    
    This should be called automatically when:
    - User views dashboard after period ends
    - Or via cron job at period end
    """
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    today = datetime.date.today()
    
    try:
        # Find the most recent COMPLETED period (period_end < today)
        completed_instance = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('user_id', user_id) \
            .lt('period_end', str(today)) \
            .eq('is_assumed', False) \
            .order('period_end', desc=True) \
            .limit(1) \
            .execute()
        
        if not completed_instance.data:
            return {"message": "No completed period to process", "processed": 0}
        
        instance = completed_instance.data[0]
        
        # Check if already processed (simple flag could be added later)
        # For now, we'll process and update cookie_jar (idempotent via cookie jar logic)
        
        # Get allocations for this completed period
        allocations = supabase.table('sahod_allocations') \
            .select('*, sahod_envelopes(id, name, is_rollover, cookie_jar)') \
            .eq('pay_cycle_instance_id', instance['id']) \
            .eq('user_id', user_id) \
            .execute()
        
        if not allocations.data:
            return {"message": "No allocations found for completed period", "processed": 0}
        
        processed_envelopes = []
        
        for alloc in allocations.data:
            envelope = alloc.get('sahod_envelopes', {})
            
            # Only process envelopes with is_rollover enabled
            if not envelope.get('is_rollover', False):
                continue
            
            # Calculate remaining
            allocated = alloc['allocated_amount'] or 0
            rollover = alloc['rollover_amount'] or 0
            spent = alloc['cached_spent'] or 0
            remaining = (allocated + rollover) - spent
            
            # Only add positive remainders to cookie jar
            if remaining > 0:
                current_cookie_jar = envelope.get('cookie_jar', 0) or 0
                new_cookie_jar = current_cookie_jar + remaining
                
                # Update the envelope's cookie_jar
                supabase.table('sahod_envelopes') \
                    .update({'cookie_jar': new_cookie_jar}) \
                    .eq('id', envelope['id']) \
                    .eq('user_id', user_id) \
                    .execute()
                
                processed_envelopes.append({
                    "envelope_id": envelope['id'],
                    "envelope_name": envelope.get('name', 'Unknown'),
                    "remaining_added": remaining,
                    "new_cookie_jar": new_cookie_jar
                })
        
        return {
            "message": f"Processed rollover for period {instance['period_start']} to {instance['period_end']}",
            "processed": len(processed_envelopes),
            "envelopes": processed_envelopes
        }
    
    except Exception as e:
        print(f"Process Rollover Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/envelopes/{envelope_id}/use-cookie-jar")
async def use_from_cookie_jar(
    envelope_id: str,
    request: UseFromCookieJarRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    PRO ONLY: Withdraw from Cookie Jar to current period's allocation.
    This allows PRO users to use their accumulated savings.
    """
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    today = datetime.date.today()
    
    # PRO gate
    if tier != 'pro':
        raise HTTPException(
            status_code=403, 
            detail="Cookie Jar withdrawal is a PRO feature. Upgrade to access your savings!"
        )
    
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    
    try:
        # Get the envelope and verify ownership
        envelope_res = supabase.table('sahod_envelopes') \
            .select('*') \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not envelope_res.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        envelope = envelope_res.data
        current_cookie_jar = envelope.get('cookie_jar', 0) or 0
        
        if request.amount > current_cookie_jar:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient Cookie Jar balance. Available: ₱{current_cookie_jar:,.2f}"
            )
        
        # Get current period instance
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('id') \
            .eq('user_id', user_id) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .single() \
            .execute()
        
        if not instance_res.data:
            raise HTTPException(status_code=400, detail="No active period found")
        
        instance_id = instance_res.data['id']
        
        # Get current allocation for this envelope
        alloc_res = supabase.table('sahod_allocations') \
            .select('*') \
            .eq('pay_cycle_instance_id', instance_id) \
            .eq('envelope_id', envelope_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not alloc_res.data:
            raise HTTPException(status_code=400, detail="No allocation found for this envelope in current period")
        
        allocation = alloc_res.data
        
        # Update: Deduct from cookie_jar, add to rollover_amount
        new_cookie_jar = current_cookie_jar - request.amount
        new_rollover = (allocation.get('rollover_amount', 0) or 0) + request.amount
        
        # Update envelope cookie_jar
        supabase.table('sahod_envelopes') \
            .update({'cookie_jar': new_cookie_jar}) \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .execute()
        
        # Update allocation rollover_amount
        supabase.table('sahod_allocations') \
            .update({'rollover_amount': new_rollover}) \
            .eq('id', allocation['id']) \
            .eq('user_id', user_id) \
            .execute()
        
        return {
            "success": True,
            "message": f"Withdrew ₱{request.amount:,.2f} from Cookie Jar",
            "envelope_id": envelope_id,
            "amount_withdrawn": request.amount,
            "new_cookie_jar_balance": new_cookie_jar,
            "new_rollover_amount": new_rollover
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Use Cookie Jar Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/envelopes/{envelope_id}/toggle-rollover")
async def toggle_envelope_rollover(
    envelope_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Toggle the is_rollover flag on an envelope.
    When enabled, unused amounts accumulate in Cookie Jar.
    """
    user_id = profile['id']
    
    try:
        # Get current state
        envelope_res = supabase.table('sahod_envelopes') \
            .select('id, is_rollover') \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not envelope_res.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        current_value = envelope_res.data.get('is_rollover', False)
        new_value = not current_value
        
        # Update
        supabase.table('sahod_envelopes') \
            .update({'is_rollover': new_value}) \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .execute()
        
        return {
            "envelope_id": envelope_id,
            "is_rollover": new_value,
            "message": f"Cookie Jar {'enabled' if new_value else 'disabled'} for this envelope"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Toggle Rollover Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DASHBOARD ENDPOINT (Single Call for UI)
# ============================================================================

@router.get("/dashboard")
async def get_dashboard(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Full dashboard data in a single call.
    Returns current instance, summary, envelopes with allocations, and next payday.
    """
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    today = datetime.date.today()
    
    try:
        # Get active pay cycle
        cycle_res = supabase.table('sahod_pay_cycles') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .limit(1) \
            .execute()
        
        if not cycle_res.data:
            return {
                "needs_setup": True,
                "current_instance": None,
                "next_payday": None,
                "summary": None,
                "envelopes": []
            }
        
        pay_cycle = cycle_res.data[0]
        
        # Get or create current instance
        current_instance_response = await get_current_instance(profile)
        
        if current_instance_response.get('needs_setup'):
            return {
                "needs_setup": True,
                "current_instance": None,
                "next_payday": None,
                "summary": None,
                "envelopes": []
            }
        
        instance = current_instance_response['instance']
        days_remaining = current_instance_response['days_remaining']
        
        # Get all envelopes with their allocations for this instance
        envelopes_res = supabase.table('sahod_envelopes') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .order('sort_order') \
            .execute()
        
        allocations_res = supabase.table('sahod_allocations') \
            .select('*') \
            .eq('pay_cycle_instance_id', instance['id']) \
            .eq('user_id', user_id) \
            .execute()
        
        # Map allocations by envelope_id
        alloc_map = {a['envelope_id']: a for a in allocations_res.data}
        
        # Build envelope response with computed fields
        envelopes = []
        total_allocated = 0.0
        total_spent = 0.0
        total_remaining = 0.0
        
        for env in envelopes_res.data:
            alloc = alloc_map.get(env['id'])
            
            if alloc:
                allocated = alloc['allocated_amount']
                rollover = alloc['rollover_amount']
                spent = alloc['cached_spent']
                remaining = (allocated + rollover) - spent
                percentage_spent = round((spent / (allocated + rollover)) * 100, 1) if (allocated + rollover) > 0 else 0
            else:
                allocated = 0
                rollover = 0
                spent = 0
                remaining = 0
                percentage_spent = 0
            
            total_allocated += allocated
            total_spent += spent
            total_remaining += remaining
            
            envelopes.append({
                "id": env['id'],
                "name": env['name'],
                "emoji": env['emoji'],
                "color": env['color'],
                "allocated": allocated,
                "rollover": rollover,
                "spent": spent,
                "remaining": remaining,
                "percentage_spent": percentage_spent,
                "is_over_budget": spent > (allocated + rollover),
                # Show cookie_jar to ALL users (PRO lock on withdrawal, not visibility)
                "cookie_jar": env.get('cookie_jar', 0) or 0,
                "is_rollover": env.get('is_rollover', False)
            })
        
        # Calculate safe daily spend
        safe_daily_spend = calculate_safe_daily_spend(total_remaining, days_remaining)
        
        # Calculate next payday
        period_end = datetime.datetime.strptime(instance['period_end'], '%Y-%m-%d').date()
        next_pay_date = period_end + datetime.timedelta(days=1)
        days_until_next = (next_pay_date - today).days
        
        # Determine instance state for UI
        needs_confirmation = instance.get('is_assumed', True)
        
        return {
            "needs_setup": False,
            "current_instance": {
                "id": instance['id'],
                "period_start": instance['period_start'],
                "period_end": instance['period_end'],
                "days_remaining": days_remaining,
                "expected_amount": instance['expected_amount'],
                "actual_amount": instance.get('actual_amount'),
                "is_assumed": instance.get('is_assumed', True),
                "confirmed_at": instance.get('confirmed_at'),
                "auto_confirmed_at": instance.get('auto_confirmed_at'),
                "needs_confirmation": needs_confirmation
            },
            "next_payday": {
                "date": str(next_pay_date),
                "days_until": max(0, days_until_next),
                "is_today": days_until_next == 0
            },
            "summary": {
                "total_allocated": total_allocated,
                "total_spent": total_spent,
                "total_remaining": total_remaining,
                "safe_daily_spend": safe_daily_spend,
                "allocation_percentage": round((total_allocated / (instance.get('actual_amount') or instance['expected_amount'])) * 100, 1) if instance.get('actual_amount') or instance['expected_amount'] else 0
            },
            "envelopes": envelopes,
            "pay_cycle": {
                "id": pay_cycle['id'],
                "cycle_name": pay_cycle['cycle_name'],
                "frequency": pay_cycle['frequency']
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get Dashboard Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))




