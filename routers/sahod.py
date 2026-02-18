"""
SAHOD Module Router - Envelope Budgeting System
Handles pay cycles, envelopes, allocations, and dashboard
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Annotated, Optional, List
from dependencies import get_user_profile, supabase, limiter
from openai import AsyncOpenAI
import datetime
import logging

logger = logging.getLogger(__name__)
from dateutil.relativedelta import relativedelta

# Initialize OpenAI client
ai_client = AsyncOpenAI()

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
    candidate_action: Optional[str] = None  # "link" or "skip" — after candidate found
    candidate_tx_id: Optional[str] = None  # Kaban tx ID to link when action="link"


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
        logger.exception("process_rollover_state_update failed")
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
        logger.exception("create_pay_cycle failed")
        raise HTTPException(status_code=500, detail="Failed to create pay cycle")


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_pay_cycles failed")
        raise HTTPException(status_code=500, detail="Failed to load pay cycles")


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
        logger.exception("get_pay_cycle failed")
        raise HTTPException(status_code=500, detail="Failed to load pay cycle")


@router.put("/pay-cycles/{pay_cycle_id}")
@limiter.limit("30/minute")
async def update_pay_cycle(
    request: Request,
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
        logger.exception("update_pay_cycle failed")
        raise HTTPException(status_code=500, detail="Failed to update pay cycle")


@router.delete("/pay-cycles/{pay_cycle_id}")
@limiter.limit("30/minute")
async def delete_pay_cycle(
    request: Request,
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
        logger.exception("delete_pay_cycle failed")
        raise HTTPException(status_code=500, detail="Failed to delete pay cycle")


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
        logger.exception("get_current_instance failed")
        raise HTTPException(status_code=500, detail="Failed to load current instance")


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_pending_instances failed")
        raise HTTPException(status_code=500, detail="Failed to load pending instances")


@router.post("/instances/{instance_id}/confirm")
@limiter.limit("20/minute")
async def confirm_instance(
    request: Request,
    instance_id: str,
    confirm_request: ConfirmInstanceRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Confirm sahod received (Tap to Fund step 1).
    
    Flow (§5.1 Income Reconciliation):
    1. Default call (no candidate_action): Runs smarter dedup check.
       - If candidate income tx found → returns { status: 'candidate_found', candidate: {...} }
       - If no candidate → confirms instance + creates income tx in Kaban
    2. candidate_action='link': Links existing Kaban tx to this instance (user chose 'Yes')
    3. candidate_action='skip': Skips dedup, creates new income tx (user chose 'No')
    """
    user_id = profile['id']
    
    try:
        # Get instance with pay cycle info
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*, sahod_pay_cycles(cycle_name)') \
            .eq('id', instance_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not instance_res.data:
            raise HTTPException(status_code=404, detail="Instance not found")
        
        instance = instance_res.data
        
        # Determine actual amount
        actual_amount = confirm_request.actual_amount if confirm_request.actual_amount is not None else instance['expected_amount']
        
        # ── LINK ACTION: User chose "Yes, link it" ──
        if confirm_request.candidate_action == "link" and confirm_request.candidate_tx_id:
            # Link existing Kaban tx to this Sobre instance
            try:
                supabase.table('kaban_transactions') \
                    .update({'sahod_instance_id': instance_id}) \
                    .eq('id', confirm_request.candidate_tx_id) \
                    .eq('user_id', user_id) \
                    .execute()
                logger.info(f"Linked existing tx {confirm_request.candidate_tx_id} to instance {instance_id}")
            except Exception as link_err:
                logger.warning(f"Failed to link tx {confirm_request.candidate_tx_id}: {link_err}")
            
            # Update instance as confirmed
            update_data = {
                'is_assumed': False,
                'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'actual_amount': actual_amount,
                'requires_manual_reconfirm': False
            }
            result = supabase.table('sahod_pay_cycle_instances') \
                .update(update_data) \
                .eq('id', instance_id) \
                .eq('user_id', user_id) \
                .execute()
            
            if not result.data:
                raise HTTPException(status_code=500, detail="Failed to confirm instance")
            return result.data[0]
        
        # ── SMARTER DEDUP CHECK (default call, no action specified) ──
        if confirm_request.candidate_action is None:
            try:
                pay_date = instance.get('period_start', datetime.date.today().isoformat())
                
                # Find income categories named Salary/Income/Sahod
                salary_categories = supabase.table('expense_categories') \
                    .select('id') \
                    .or_(f'user_id.is.null,user_id.eq.{user_id}') \
                    .eq('type', 'income') \
                    .or_('name.ilike.%salary%,name.ilike.%income%,name.ilike.%sahod%') \
                    .execute()
                
                if salary_categories.data:
                    cat_ids = [c['id'] for c in salary_categories.data]
                    
                    # Date range: pay_date ± 2 days
                    pay_date_obj = datetime.datetime.strptime(pay_date, '%Y-%m-%d').date()
                    date_start = (pay_date_obj - datetime.timedelta(days=2)).isoformat()
                    date_end = (pay_date_obj + datetime.timedelta(days=2)).isoformat()
                    
                    # Amount range: ± 10%
                    amount_low = actual_amount * 0.9
                    amount_high = actual_amount * 1.1
                    
                    # Query for candidate match
                    candidate_query = supabase.table('kaban_transactions') \
                        .select('id, amount, description, transaction_date, expense_categories(name, emoji)') \
                        .eq('user_id', user_id) \
                        .eq('transaction_type', 'income') \
                        .is_('sahod_instance_id', 'null') \
                        .gte('transaction_date', date_start) \
                        .lte('transaction_date', date_end) \
                        .gte('amount', amount_low) \
                        .lte('amount', amount_high) \
                        .in_('category_id', cat_ids) \
                        .limit(1) \
                        .execute()
                    
                    if candidate_query.data:
                        candidate = candidate_query.data[0]
                        cat_info = candidate.get('expense_categories') or {}
                        return {
                            "status": "candidate_found",
                            "candidate": {
                                "id": candidate['id'],
                                "amount": candidate['amount'],
                                "description": candidate.get('description', ''),
                                "transaction_date": candidate['transaction_date'],
                                "category_name": cat_info.get('name', 'Income') if isinstance(cat_info, dict) else 'Income'
                            }
                        }
            except Exception as dedup_err:
                logger.warning(f"Smarter dedup check failed, proceeding with normal flow: {dedup_err}")
        
        # ── NORMAL FLOW: Update instance + create income tx ──
        # (Reached when: no candidate found, or candidate_action='skip')
        
        # Update instance as confirmed
        update_data = {
            'is_assumed': False,
            'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'actual_amount': actual_amount,
            'requires_manual_reconfirm': False
        }
        
        result = supabase.table('sahod_pay_cycle_instances') \
            .update(update_data) \
            .eq('id', instance_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to confirm instance")
        
        # === CREATE INCOME TRANSACTION IN KABAN ===
        try:
            # Get or find a "Salary" income category
            salary_category = supabase.table('expense_categories') \
                .select('id') \
                .or_(f'user_id.is.null,user_id.eq.{user_id}') \
                .eq('type', 'income') \
                .ilike('name', '%salary%') \
                .limit(1) \
                .execute()
            
            if not salary_category.data:
                salary_category = supabase.table('expense_categories') \
                    .select('id') \
                    .or_(f'user_id.is.null,user_id.eq.{user_id}') \
                    .eq('type', 'income') \
                    .limit(1) \
                    .execute()
            
            category_id = salary_category.data[0]['id'] if salary_category.data else None
            
            # Build description
            cycle_name = instance.get('sahod_pay_cycles', {}).get('cycle_name', 'Salary')
            period_start = instance.get('period_start', '')
            description = f'{cycle_name} - {period_start}'
            
            # Existing dedup: check sahod_instance_id or description match
            try:
                existing_tx = supabase.table('kaban_transactions') \
                    .select('id') \
                    .eq('user_id', user_id) \
                    .eq('sahod_instance_id', instance_id) \
                    .eq('transaction_type', 'income') \
                    .limit(1) \
                    .execute()
            except Exception:
                existing_tx = supabase.table('kaban_transactions') \
                    .select('id') \
                    .eq('user_id', user_id) \
                    .eq('description', description) \
                    .eq('transaction_type', 'income') \
                    .eq('amount', actual_amount) \
                    .limit(1) \
                    .execute()
            
            if not existing_tx.data:
                tx_data = {
                    'user_id': user_id,
                    'transaction_type': 'income',
                    'amount': actual_amount,
                    'description': description,
                    'category_id': category_id,
                    'transaction_date': datetime.date.today().isoformat(),
                    'source': 'manual',
                }
                
                try:
                    tx_data['sahod_instance_id'] = instance_id
                    supabase.table('kaban_transactions').insert(tx_data).execute()
                except Exception as insert_error:
                    if 'sahod_instance_id' in str(insert_error):
                        del tx_data['sahod_instance_id']
                        supabase.table('kaban_transactions').insert(tx_data).execute()
                    else:
                        raise insert_error
                        
                logger.info(f"Created income transaction for confirmed sahod instance {instance_id}")
        except Exception as tx_error:
            logger.warning(f"Failed to create income transaction for instance {instance_id}: {tx_error}")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("confirm_instance failed")
        raise HTTPException(status_code=500, detail="Failed to confirm instance")


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_instance_history failed")
        raise HTTPException(status_code=500, detail="Failed to load instance history")


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
    
    try:
        # Check envelope limit (max 7 for all users)
        count_res = supabase.table('sahod_envelopes') \
            .select('id', count='exact') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .execute()
        
        if count_res.count and count_res.count >= 7:
            raise HTTPException(
                status_code=403, 
                detail="Maximum of 7 envelopes allowed."
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
        
        result = supabase.table('sahod_envelopes').insert(data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create envelope")
        
        return result.data[0]
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create_envelope failed")
        raise HTTPException(status_code=500, detail="Failed to create envelope")


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_envelopes failed")
        raise HTTPException(status_code=500, detail="Failed to load envelopes")


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
        logger.exception("get_envelope failed")
        raise HTTPException(status_code=500, detail="Failed to load envelope")


@router.put("/envelopes/{envelope_id}")
@limiter.limit("60/minute")
async def update_envelope(
    request: Request,
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
        logger.exception("update_envelope failed")
        raise HTTPException(status_code=500, detail="Failed to update envelope")


@router.delete("/envelopes/{envelope_id}")
@limiter.limit("60/minute")
async def delete_envelope(
    request: Request,
    envelope_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Soft delete an envelope.
    
    CONSTRAINTS (after period is confirmed/locked):
    1. Cannot delete if envelope has any spent amount
    2. Cannot delete if envelope has any allocated amount
    """
    user_id = profile['id']
    
    try:
        # Get envelope with name for error message
        envelope_res = supabase.table('sahod_envelopes') \
            .select('id, name') \
            .eq('id', envelope_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not envelope_res.data:
            raise HTTPException(status_code=404, detail="Envelope not found")
        
        envelope_name = envelope_res.data.get('name', 'this envelope')
        
        # Check for current period allocation
        # Get current period's allocation for this envelope
        current_alloc = supabase.table('sahod_allocations') \
            .select('allocated_amount, cached_spent') \
            .eq('envelope_id', envelope_id) \
            .eq('user_id', user_id) \
            .order('created_at', desc=True) \
            .limit(1) \
            .execute()
        
        if current_alloc.data:
            alloc = current_alloc.data[0]
            spent_amount = alloc.get('cached_spent', 0) or 0
            allocated_amount = alloc.get('allocated_amount', 0) or 0
            
            # Rule 1: Cannot delete if has spent
            if spent_amount > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot remove '{envelope_name}' - has ₱{spent_amount:,.2f} spent"
                )
            
            # Rule 2: Cannot delete if has allocation
            if allocated_amount > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot remove '{envelope_name}' - has ₱{allocated_amount:,.2f} allocated"
                )
        
        # Safe to soft delete
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
        logger.exception("delete_envelope failed")
        raise HTTPException(status_code=500, detail="Failed to delete envelope")


@router.put("/envelopes/reorder")
@limiter.limit("30/minute")
async def reorder_envelopes(
    request: Request,
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
        logger.exception("reorder_envelopes failed")
        raise HTTPException(status_code=500, detail="Failed to reorder envelopes")


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
        logger.exception("fill_allocations failed")
        raise HTTPException(status_code=500, detail="Failed to fill allocations")


@router.get("/allocations/current")
async def get_current_allocations(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get allocations for current period. Falls back to previous period if none exist."""
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
        
        # If current period has allocations, return them
        if result.data:
            return result.data
        
        # Fallback: Get allocations from the most recent previous period
        prev_instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('id') \
            .eq('user_id', user_id) \
            .lt('period_end', str(today)) \
            .order('period_end', desc=True) \
            .limit(1) \
            .execute()
        
        if prev_instance_res.data:
            prev_result = supabase.table('sahod_allocations') \
                .select('*, sahod_envelopes(name, emoji, color, is_rollover, cookie_jar)') \
                .eq('pay_cycle_instance_id', prev_instance_res.data[0]['id']) \
                .eq('user_id', user_id) \
                .execute()
            
            # Return previous allocations as templates (frontend will use amounts as defaults)
            return prev_result.data if prev_result.data else []
        
        return []
    except Exception as e:
        logger.exception("get_current_allocations failed")
        raise HTTPException(status_code=500, detail="Failed to load allocations")


@router.put("/allocations/{allocation_id}")
@limiter.limit("60/minute")
async def update_allocation(
    request: Request,
    allocation_id: str,
    allocation: AllocationUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Update a single allocation.
    
    CONSTRAINTS (after period is confirmed/locked):
    1. new_amount >= spent_amount (cannot reduce below already spent)
    2. Total allocations must equal total income
    """
    user_id = profile['id']
    
    try:
        update_data = {k: v for k, v in allocation.model_dump().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Get current allocation with envelope and instance info
        current_alloc = supabase.table('sahod_allocations') \
            .select('*, sahod_envelopes(name), sahod_pay_cycle_instances(confirmed_at, actual_amount, expected_amount)') \
            .eq('id', allocation_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not current_alloc.data:
            raise HTTPException(status_code=404, detail="Allocation not found")
        
        alloc_data = current_alloc.data
        instance = alloc_data.get('sahod_pay_cycle_instances', {})
        is_locked = instance.get('confirmed_at') is not None
        
        # VALIDATION: If period is locked and updating allocated_amount
        if is_locked and 'allocated_amount' in update_data:
            new_amount = update_data['allocated_amount']
            spent_amount = alloc_data.get('cached_spent', 0) or 0
            envelope_name = alloc_data.get('sahod_envelopes', {}).get('name', 'this envelope')
            
            # Rule 1: Cannot go below spent amount
            if new_amount < spent_amount:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Cannot set below ₱{spent_amount:,.2f} (already spent in {envelope_name})"
                )
        
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
        logger.exception("update_allocation failed")
        raise HTTPException(status_code=500, detail="Failed to update allocation")


# ============================================================================
# COOKIE JAR / ROLLOVER ENDPOINTS
# ============================================================================

class UseFromCookieJarRequest(BaseModel):
    envelope_id: str
    amount: float  # Amount to withdraw from Cookie Jar


@router.post("/allocations/process-rollover")
@limiter.limit("10/minute")
async def process_rollover(
    request: Request,
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
        logger.exception("process_rollover failed")
        raise HTTPException(status_code=500, detail="Failed to process rollover")


@router.post("/envelopes/{envelope_id}/use-cookie-jar")
@limiter.limit("20/minute")
async def use_from_cookie_jar(
    request: Request,
    envelope_id: str,
    withdraw_request: UseFromCookieJarRequest,
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
    
    if withdraw_request.amount <= 0:
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
        
        if withdraw_request.amount > current_cookie_jar:
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
        new_cookie_jar = current_cookie_jar - withdraw_request.amount
        new_rollover = (allocation.get('rollover_amount', 0) or 0) + withdraw_request.amount
        
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
            "message": f"Withdrew ₱{withdraw_request.amount:,.2f} from Cookie Jar",
            "envelope_id": envelope_id,
            "amount_withdrawn": withdraw_request.amount,
            "new_cookie_jar_balance": new_cookie_jar,
            "new_rollover_amount": new_rollover
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("use_from_cookie_jar failed")
        raise HTTPException(status_code=500, detail="Failed to withdraw from cookie jar")


@router.put("/envelopes/{envelope_id}/toggle-rollover")
@limiter.limit("30/minute")
async def toggle_envelope_rollover(
    request: Request,
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
        logger.exception("toggle_envelope_rollover failed")
        raise HTTPException(status_code=500, detail="Failed to toggle rollover")


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
        requires_reconfirm = instance.get('requires_manual_reconfirm', False)
        is_locked = instance.get('confirmed_at') is not None  # Locked after income confirmation
        
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
                "needs_confirmation": needs_confirmation or requires_reconfirm,
                "requires_manual_reconfirm": requires_reconfirm,
                "is_locked": is_locked,  # True after Confirm ₱X,XXX is clicked
                "payday_type": instance.get('payday_type', 'single')  # kinsenas/katapusan/single
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
        logger.exception("get_dashboard failed")
        raise HTTPException(status_code=500, detail="Failed to load dashboard")


# ============================================================================
# AI INSIGHTS ENDPOINT (PRO Only)
# ============================================================================

class AIInsightRequest(BaseModel):
    """Request model for AI insights - minimal to prevent prompt injection"""
    envelope_id: Optional[str] = None  # Optional: get insight for specific envelope


@router.post("/ai/insights")
@limiter.limit("5/minute")  # Rate limit to prevent abuse
async def get_ai_insights(
    request: Request,
    insight_request: AIInsightRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Generate AI-powered spending insights for Sahod Planner (PRO only).
    
    Returns personalized tips based on:
    - Envelope spending patterns
    - Cookie Jar growth
    - Over/under budget trends
    
    Security considerations:
    - PRO tier locked
    - Rate limited (5/minute)
    - No user input in prompts (data-driven only)
    - Sanitized output
    """
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    
    # PRO Lock
    if tier != 'pro':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="AI Insights is a PRO feature. Upgrade to unlock personalized spending tips!"
        )
    
    today = datetime.date.today()
    
    try:
        # Get current instance
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('*') \
            .eq('user_id', user_id) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .limit(1) \
            .execute()
        
        if not instance_res.data:
            return {"insight": "Set up your Sahod Planner to get personalized insights!", "type": "setup"}
        
        instance = instance_res.data[0]
        period_start = datetime.datetime.strptime(instance['period_start'], '%Y-%m-%d').date()
        period_end = datetime.datetime.strptime(instance['period_end'], '%Y-%m-%d').date()
        days_total = (period_end - period_start).days + 1
        days_elapsed = (today - period_start).days + 1
        days_remaining = (period_end - today).days + 1
        
        # Get envelopes with allocations
        envelopes_res = supabase.table('sahod_envelopes') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .execute()
        
        allocations_res = supabase.table('sahod_allocations') \
            .select('*') \
            .eq('pay_cycle_instance_id', instance['id']) \
            .eq('user_id', user_id) \
            .execute()
        
        # Build envelope summary
        alloc_map = {a['envelope_id']: a for a in allocations_res.data}
        envelope_summaries = []
        total_allocated = 0
        total_spent = 0
        total_cookie_jar = 0
        over_budget_count = 0
        under_budget_count = 0
        
        for env in envelopes_res.data:
            alloc = alloc_map.get(env['id'])
            if alloc:
                allocated = alloc['allocated_amount'] or 0
                rollover = alloc['rollover_amount'] or 0
                spent = alloc['cached_spent'] or 0
                budget = allocated + rollover
                remaining = budget - spent
                percentage_spent = (spent / budget * 100) if budget > 0 else 0
                cookie_jar = env.get('cookie_jar', 0) or 0
                
                total_allocated += allocated
                total_spent += spent
                total_cookie_jar += cookie_jar
                
                if spent > budget:
                    over_budget_count += 1
                elif percentage_spent < 50 and days_elapsed > days_total / 2:
                    under_budget_count += 1
                
                envelope_summaries.append({
                    "name": env['name'],
                    "emoji": env['emoji'],
                    "allocated": allocated,
                    "spent": spent,
                    "remaining": remaining,
                    "percentage_spent": round(percentage_spent, 1),
                    "is_over": spent > budget,
                    "cookie_jar": cookie_jar,
                    "has_rollover": env.get('is_rollover', False)
                })
        
        # Sort by percentage spent (most spent first)
        envelope_summaries.sort(key=lambda x: x['percentage_spent'], reverse=True)
        
        # Get historical data (last 3 periods) for trend analysis
        history_res = supabase.table('sahod_pay_cycle_instances') \
            .select('id, period_start, period_end') \
            .eq('user_id', user_id) \
            .lt('period_end', str(today)) \
            .eq('is_assumed', False) \
            .order('period_end', desc=True) \
            .limit(3) \
            .execute()
        
        historical_context = ""
        if history_res.data:
            historical_context = f"User has {len(history_res.data)} completed pay periods on record."
        
        # Build system prompt (NO user input - data only)
        system_prompt = f"""You are 'Kaibigan Sahod AI', a friendly Filipino financial advisor specializing in envelope budgeting.

CURRENT PAY PERIOD:
- Period: {instance['period_start']} to {instance['period_end']}
- Day {days_elapsed} of {days_total} ({days_remaining} days remaining)
- Total Allocated: ₱{total_allocated:,.0f}
- Total Spent: ₱{total_spent:,.0f}
- Spending Rate: {(total_spent/total_allocated*100) if total_allocated > 0 else 0:.1f}%

ENVELOPE STATUS:
"""
        for env in envelope_summaries[:6]:  # Top 6 envelopes
            status_emoji = "⚠️" if env['is_over'] else "✅" if env['percentage_spent'] < 80 else "⏳"
            system_prompt += f"- {env['emoji']} {env['name']}: ₱{env['spent']:,.0f}/₱{env['allocated']:,.0f} ({env['percentage_spent']}%) {status_emoji}\n"
            if env['cookie_jar'] > 0:
                system_prompt += f"  🍪 Cookie Jar: ₱{env['cookie_jar']:,.0f}\n"

        system_prompt += f"""
SUMMARY:
- Envelopes over budget: {over_budget_count}
- Envelopes under 50% (good pace): {under_budget_count}
- Total Cookie Jar savings: ₱{total_cookie_jar:,.0f}
{historical_context}

YOUR TASK:
Generate ONE short, actionable, friendly insight (2-3 sentences max) in Taglish (mix of Filipino and English).
Focus on:
1. If overspending: Which envelope and how to adjust
2. If underspending: Celebrate discipline, suggest Cookie Jar
3. Cookie Jar growth: Acknowledge savings achievements
4. Pacing: Are they on track for the period?

Be encouraging, specific (use peso amounts), and culturally appropriate.
Do NOT ask questions. Just give the insight.
"""

        # Call OpenAI - using gpt-5-nano for cost-effective short insights
        chat_completion = await ai_client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Give me my spending insight for today."}
            ]
        )
        
        ai_response = chat_completion.choices[0].message.content.strip()
        
        # Determine insight type for UI styling
        insight_type = "neutral"
        if over_budget_count > 0:
            insight_type = "warning"
        elif total_cookie_jar > 0 or under_budget_count > len(envelope_summaries) / 2:
            insight_type = "positive"
        
        return {
            "insight": ai_response,
            "type": insight_type,
            "summary": {
                "days_remaining": days_remaining,
                "total_spent": total_spent,
                "total_allocated": total_allocated,
                "over_budget_count": over_budget_count,
                "cookie_jar_total": total_cookie_jar
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ai_insights failed")
        # Fallback to rule-based insight if AI fails
        return {
            "insight": "Keep tracking your spending! You're doing great. 💪",
            "type": "neutral",
            "error": "AI temporarily unavailable"
        }


# ============================================================================
# EXPORT ENDPOINTS (PRO ONLY)
# ============================================================================

@router.get("/export/csv")
async def export_csv(
    profile: Annotated[dict, Depends(get_user_profile)],
    period: Optional[str] = "current"  # 'current', 'all', or instance_id
):
    """
    Export Sahod data to CSV format.
    PRO users only.
    
    Returns CSV with columns:
    - Envelope, Allocated, Spent, Remaining, Percentage Used, Rollover, Cookie Jar
    """
    user_id = profile['id']
    tier = profile.get('tier', 'free')
    
    if tier != 'pro':
        raise HTTPException(
            status_code=403,
            detail="CSV export is a PRO feature. Upgrade to access."
        )
    
    try:
        import io
        import csv
        from fastapi.responses import StreamingResponse
        
        # Get current instance
        today = datetime.date.today()
        instance_res = supabase.table('sahod_pay_cycle_instances') \
            .select('id, period_start, period_end, expected_amount, actual_amount') \
            .eq('user_id', user_id) \
            .lte('period_start', str(today)) \
            .gte('period_end', str(today)) \
            .limit(1) \
            .execute()
        
        if not instance_res.data:
            raise HTTPException(status_code=404, detail="No active pay period found")
        
        instance = instance_res.data[0]
        instance_id = instance['id']
        
        # Get allocations with envelope info
        alloc_res = supabase.table('sahod_allocations') \
            .select('*, sahod_envelopes(name, emoji, color, is_rollover, cookie_jar)') \
            .eq('pay_cycle_instance_id', instance_id) \
            .eq('user_id', user_id) \
            .execute()
        
        # Build CSV data (spending is cached in sahod_allocations.cached_spent)
        # Use BytesIO with UTF-8 BOM for Excel compatibility
        output = io.BytesIO()
        # Write UTF-8 BOM for Excel to recognize encoding
        output.write(b'\xef\xbb\xbf')
        
        # Wrap in TextIOWrapper for csv.writer
        text_output = io.TextIOWrapper(output, encoding='utf-8', newline='')
        writer = csv.writer(text_output)
        
        # Header (use P instead of ₱ for better compatibility)
        writer.writerow([
            'Envelope',
            'Emoji',
            'Allocated (PHP)',
            'Spent (PHP)',
            'Remaining (PHP)',
            '% Used',
            'Rollover Enabled',
            'Cookie Jar (PHP)'
        ])
        
        total_allocated = 0
        total_spent = 0
        
        for alloc in (alloc_res.data or []):
            env = alloc.get('sahod_envelopes', {})
            allocated = alloc.get('allocated_amount', 0)
            rollover = alloc.get('rollover_amount', 0)
            total_for_env = allocated + rollover
            spent = alloc.get('cached_spent', 0) or 0  # Spending is cached in allocation
            remaining = total_for_env - spent
            pct_used = (spent / total_for_env * 100) if total_for_env > 0 else 0
            
            total_allocated += total_for_env
            total_spent += spent
            
            writer.writerow([
                env.get('name', 'Unknown'),
                env.get('emoji', '📦'),
                f"{total_for_env:.0f}",
                f"{spent:.0f}",
                f"{remaining:.0f}",
                f"{pct_used:.1f}%",
                'Yes' if env.get('is_rollover') else 'No',
                f"{env.get('cookie_jar', 0):.0f}"
            ])
        
        # Add totals row
        writer.writerow([])
        writer.writerow([
            'TOTAL',
            '',
            f"{total_allocated:.0f}",
            f"{total_spent:.0f}",
            f"{total_allocated - total_spent:.0f}",
            f"{(total_spent / total_allocated * 100) if total_allocated > 0 else 0:.1f}%",
            '',
            ''
        ])
        
        # Add metadata
        writer.writerow([])
        writer.writerow(['Period:', f"{instance['period_start']} to {instance['period_end']}"])
        writer.writerow(['Expected Salary:', f"PHP {instance['expected_amount']:.0f}"])
        if instance.get('actual_amount'):
            writer.writerow(['Actual Salary:', f"PHP {instance['actual_amount']:.0f}"])
        writer.writerow(['Exported:', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        
        # Flush TextIOWrapper to BytesIO
        text_output.flush()
        output.seek(0)
        
        # Generate filename
        filename = f"sahod_export_{instance['period_start']}_to_{instance['period_end']}.csv"
        
        return StreamingResponse(
            iter([output.read()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_csv failed")
        raise HTTPException(status_code=500, detail="Failed to export CSV")


# ============================================================================
# DEFAULT SHORTCUTS CREATION
# ============================================================================

@router.post("/create-default-shortcuts")
@limiter.limit("5/minute")
async def create_default_shortcuts(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Create default Quick Add shortcuts for a user based on their envelopes.
    Called after Sahod Wizard completion to populate user's shortcuts with
    proper category_id and sahod_envelope_id mappings.
    
    This replaces the hardcoded DEFAULT_SHORTCUTS in the frontend.
    """
    user_id = profile['id']
    
    try:
        # 1. Get user's active envelopes
        envelopes_res = supabase.table('sahod_envelopes') \
            .select('id, name') \
            .eq('user_id', user_id) \
            .eq('is_active', True) \
            .execute()
        envelopes = envelopes_res.data or []
        
        if not envelopes:
            return {"created": 0, "message": "No envelopes found. Complete Sahod Setup first."}
        
        # 2. Get default shortcut templates (now with direct category_id FK)
        templates_res = supabase.table('default_shortcut_templates') \
            .select('*, expense_categories(id, name)') \
            .eq('is_active', True) \
            .order('display_order') \
            .execute()
        templates = templates_res.data or []
        
        if not templates:
            return {"created": 0, "message": "No default templates found. Run migration first."}
        
        # 3. Check existing shortcuts (to avoid duplicates)
        existing_res = supabase.table('quick_add_shortcuts') \
            .select('label') \
            .eq('user_id', user_id) \
            .execute()
        existing_labels = {s['label'].lower() for s in (existing_res.data or [])}
        
        # 4. Create shortcuts for each template
        created_count = 0
        skipped_duplicate = []
        created_shortcuts = []
        
        for template in templates:
            # Skip if user already has this shortcut
            if template['label'].lower() in existing_labels:
                skipped_duplicate.append(template['label'])
                continue
            
            # category_id comes directly from template (FK to expense_categories)
            # No more string matching needed!
            category_id = template['category_id']
            category_name = template.get('expense_categories', {}).get('name', 'Unknown')
            
            # Find matching envelope by hint (flexible matching with aliases)
            # envelope_hint can be comma-separated aliases like "food,pagkain,kain"
            envelope = find_envelope_flexible(envelopes, template.get('envelope_hint', ''))
            
            # Create shortcut - envelope is OPTIONAL
            shortcut_data = {
                'user_id': user_id,
                'label': template['label'],
                'emoji': template['emoji'],
                'default_amount': float(template['default_amount']),
                'category_id': category_id,  # Direct from template, no matching!
                'sahod_envelope_id': envelope['id'] if envelope else None,
                'is_system_default': True,
                'usage_count': 0
            }
            
            try:
                supabase.table('quick_add_shortcuts').insert(shortcut_data).execute()
                created_count += 1
                created_shortcuts.append({
                    'label': template['label'],
                    'category': category_name,
                    'category_id': category_id,
                    'envelope': envelope['name'] if envelope else None
                })
            except Exception as insert_error:
                logger.warning(f"Failed to create shortcut {template['label']}: {insert_error}")
        
        return {
            "created": created_count,
            "created_shortcuts": created_shortcuts,
            "skipped_duplicate": skipped_duplicate,
            "templates_found": len(templates),
            "envelopes_found": len(envelopes),
            "available_envelopes": [e['name'] for e in envelopes]
        }
        
    except Exception as e:
        logger.exception("create_default_shortcuts failed")
        raise HTTPException(status_code=500, detail=f"Failed to create default shortcuts: {str(e)}")


def find_category_exact(categories: list, category_name: str) -> dict | None:
    """
    Find category by EXACT name match (case-insensitive).
    This is the source of truth - expense_categories has fixed names.
    """
    name_lower = category_name.lower().strip()
    
    for cat in categories:
        if cat.get('name', '').lower().strip() == name_lower:
            return cat
    
    return None


def find_envelope_flexible(envelopes: list, hint_aliases: str) -> dict | None:
    """
    Find envelope by flexible matching with multiple aliases.
    hint_aliases is comma-separated like "food,pagkain,kain,meals"
    
    Envelopes are user-created so we need flexible matching.
    """
    if not envelopes:
        return None
    
    # Parse comma-separated aliases
    aliases = [a.strip().lower() for a in hint_aliases.split(',')]
    
    for envelope in envelopes:
        envelope_name = envelope.get('name', '').lower().strip()
        
        # Check if envelope name matches any alias
        for alias in aliases:
            if alias == envelope_name or alias in envelope_name or envelope_name in alias:
                return envelope
    
    return None


def find_by_hint(items: list, field: str, hint: str) -> dict | None:
    """
    DEPRECATED - use find_category_exact or find_envelope_flexible instead.
    Kept for backward compatibility.
    """
    hint_lower = hint.lower()
    
    for item in items:
        if item.get(field, '').lower() == hint_lower:
            return item
    
    return None