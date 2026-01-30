"""
PERA Module Router - Kaibigan Kaban System
Handles all financial management endpoints: Ipon Tracker, Utang Tracker
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Annotated, Optional, List, Literal
from dependencies import get_user_profile, supabase, limiter
from openai import AsyncOpenAI
import datetime
import logging

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI()

# Router configuration
router = APIRouter(
    prefix="",
    tags=["Pera - Financial Management"],
    responses={401: {"description": "Unauthorized"}}
)

# --- PYDANTIC MODELS ---

class IponGoalCreate(BaseModel):
    name: str
    target_amount: float
    target_date: Optional[datetime.date] = None

class TransactionCreate(BaseModel):
    goal_id: str
    amount: float
    notes: Optional[str] = None

class UtangCreate(BaseModel):
    debtor_name: str
    amount: float
    due_date: Optional[datetime.date] = None
    notes: Optional[str] = None

class UtangUpdate(BaseModel):
    status: str  # "paid" or "unpaid"

class AICollectorRequest(BaseModel):
    debtor_name: str
    amount: float
    tone: str  # "Gentle", "Firm", "Final"

class CategoryCreate(BaseModel):
    name: str
    emoji: Optional[str] = None
    type: str  # "expense" or "income"

class TransactionRequest(BaseModel):
    category_id: str
    amount: float
    transaction_type: str  # "expense" or "income"
    description: Optional[str] = None
    transaction_date: Optional[datetime.date] = None
    sahod_envelope_id: Optional[str] = None  # Link to Sahod Planner envelope

class TransactionUpdate(BaseModel):
    category_id: Optional[str] = None
    amount: Optional[float] = None
    transaction_type: Optional[str] = None
    description: Optional[str] = None
    transaction_date: Optional[datetime.date] = None
    sahod_envelope_id: Optional[str] = None  # Link to Sahod Planner envelope

class CategoryInfo(BaseModel):
    name: str
    emoji: str

class TransactionItem(BaseModel):
    id: str
    amount: float
    description: Optional[str] = None
    transaction_type: str
    transaction_date: str
    expense_categories: CategoryInfo

class FinancialSummary(BaseModel):
    total_income: float
    total_expense: float
    balance: float
    transaction_count: int

class AIFinancialAnalysisRequest(BaseModel):
    analysis_type: Literal["budget", "spending", "savings"]
    summary: FinancialSummary
    transactions: List[TransactionItem]

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class AIFinancialChatRequest(BaseModel):
    message: str
    summary: FinancialSummary
    transactions: List[TransactionItem]
    chat_history: Optional[List[ChatMessage]] = []


# --- RECURRING INCOME MODELS ---

class RecurringRuleCreate(BaseModel):
    amount: float
    description: Optional[str] = None
    category_id: Optional[str] = None  # Made optional - envelope is primary link
    transaction_type: str = "income"  # "income" or "expense"
    frequency: str  # "monthly", "bimonthly", "weekly"
    schedule_day: int  # Day of month (1-31) or day of week (0-6)
    sahod_envelope_id: Optional[str] = None  # Link to Sahod envelope

class RecurringRuleUpdate(BaseModel):
    amount: Optional[float] = None
    description: Optional[str] = None
    category_id: Optional[str] = None
    frequency: Optional[str] = None
    schedule_day: Optional[int] = None
    is_active: Optional[bool] = None
    sahod_envelope_id: Optional[str] = None  # Link to Sahod envelope

# --- IPON TRACKER ENDPOINTS ---

@router.post("/ipon/goals")
@limiter.limit("20/minute")
async def create_ipon_goal(
    request: Request,
    goal_request: IponGoalCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new savings goal (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")

    try:
        goal_data = goal_request.model_dump()
        goal_data['user_id'] = user_id
        
        insert_res = supabase.table('ipon_goals').insert(goal_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create goal.")
            
        return insert_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_ipon_goal failed")
        raise HTTPException(status_code=500, detail="Failed to create goal")


@router.get("/ipon/goals")
async def get_ipon_goals(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all savings goals for the user (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")

    try:
        goals_res = supabase.table('ipon_goals').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
        return goals_res.data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_ipon_goals failed")
        raise HTTPException(status_code=500, detail="Failed to load goals")


@router.post("/ipon/transactions")
@limiter.limit("30/minute")
async def add_ipon_transaction(
    request: Request,
    transaction_request: TransactionCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Add a transaction to a savings goal (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")
    
    try:
        goal_res = supabase.table('ipon_goals').select('id').eq('id', transaction_request.goal_id).eq('user_id', user_id).single().execute()
        if not goal_res.data:
            raise HTTPException(status_code=404, detail="Goal not found or you do not have permission.")

        tx_data = transaction_request.model_dump()
        tx_data['user_id'] = user_id
        
        insert_res = supabase.table('transactions').insert(tx_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to add transaction.")
        
        return insert_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("add_ipon_transaction failed")
        raise HTTPException(status_code=500, detail="Failed to add transaction")


@router.get("/ipon/goals/{goal_id}/transactions")
@limiter.limit("60/minute")
async def get_goal_transactions(
    request: Request,
    goal_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all transactions for a specific goal (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")

    try:
        tx_res = supabase.table('transactions').select('*').eq('user_id', user_id).eq('goal_id', goal_id).order('created_at', desc=True).execute()
        return tx_res.data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_goal_transactions failed")
        raise HTTPException(status_code=500, detail="Failed to load transactions")


# --- UTANG TRACKER ENDPOINTS ---

@router.post("/utang/debts")
@limiter.limit("30/minute")
async def create_utang_record(
    request: Request,
    utang_request: UtangCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new debt record - Free users limited to 1 unpaid debt, Pro users unlimited"""
    tier = profile['tier']
    user_id = profile['id']
    
    # Check debt limit for free users
    if tier != 'pro':
        try:
            unpaid_count_res = supabase.table('utang').select('id', count='exact').eq('user_id', user_id).eq('status', 'unpaid').execute()
            unpaid_count = unpaid_count_res.count if unpaid_count_res.count else 0
            
            if unpaid_count >= 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Free users can only track 1 unpaid debt. Upgrade to Pro for unlimited tracking!"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("create_utang_record: failed to check debt count")

    try:
        utang_data = utang_request.model_dump()
        utang_data['user_id'] = user_id
        
        insert_res = supabase.table('utang').insert(utang_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create utang record.")
            
        return insert_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_utang_record failed")
        raise HTTPException(status_code=500, detail="Failed to create utang record")


@router.get("/utang/debts")
async def get_utang_records(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all unpaid debts for the user - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can view their debts

    try:
        utang_res = supabase.table('utang').select('*').eq('user_id', user_id).eq('status', 'unpaid').order('due_date', desc=False).execute()
        return utang_res.data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_utang_records failed")
        raise HTTPException(status_code=500, detail="Failed to load utang records")


@router.put("/utang/debts/{debt_id}")
@limiter.limit("60/minute")
async def update_utang_status(
    request: Request,
    debt_id: str,
    utang_update: UtangUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update debt status (mark as paid/unpaid) - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can update their debts

    try:
        update_res = supabase.table('utang').update({"status": utang_update.status}).eq('id', debt_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=404, detail="Utang record not found or permission denied.")
            
        return update_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_utang_status failed")
        raise HTTPException(status_code=500, detail="Failed to update utang status")


@router.post("/utang/generate-message")
@limiter.limit("5/minute")
async def generate_utang_message(
    request: Request,
    collector_request: AICollectorRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Generate AI-powered debt collection message (Pro only)"""
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Message Generator is a Pro feature. Upgrade to unlock!")

    tone_instructions = {
        "Gentle": "a very gentle, friendly, and 'nahihiya' reminder. Start with 'Hi [Name], kumusta?'.",
        "Firm": "a polite but firm and direct reminder that the payment is due.",
        "Final": "a final, urgent, and very serious reminder that the payment is long overdue."
    }
    
    system_prompt = f"""
    You are 'Kaibigan Pera', an AI assistant who helps Filipinos with the awkward task of collecting debt ('maningil').
    Your task is to draft a short, clear, and culturally-appropriate SMS or Messenger message.
    
    TONE: The message must have a {collector_request.tone} tone. Be {tone_instructions.get(collector_request.tone, "a polite tone")}.
    DEBTOR'S NAME: {collector_request.debtor_name}
    AMOUNT: ₱{collector_request.amount:,.2f}
    
    Respond *only* with the message itself. Do not add any extra text or explanation.
    """
    
    try:
        chat_completion = await client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"message": ai_response}
    except HTTPException:
        raise
    except Exception:
        logger.exception("generate_utang_message failed")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")


# --- KAIBIGAN KABAN (EXPENSE TRACKER) ENDPOINTS ---

@router.get("/kaban/categories")
async def get_kaban_categories(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all expense categories (default + custom) - Free users see defaults only, Pro users see all"""
    user_id = profile['id']
    # No tier check - all authenticated users can see categories

    try:
        # Get default categories (user_id is NULL) and user's custom categories
        categories_res = supabase.table('expense_categories').select('*').or_(f'user_id.is.null,user_id.eq.{user_id}').order('name', desc=False).execute()
        return categories_res.data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_kaban_categories failed")
        raise HTTPException(status_code=500, detail="Failed to load categories")


@router.post("/kaban/categories")
@limiter.limit("10/minute")
async def create_custom_category(
    request: Request,
    category_request: CategoryCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a custom expense category (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Creating custom categories is a Pro feature. Upgrade to unlock!")

    try:
        category_data = request.model_dump()
        category_data['user_id'] = user_id
        
        insert_res = supabase.table('expense_categories').insert(category_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create category.")
            
        return insert_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_custom_category failed")
        raise HTTPException(status_code=500, detail="Failed to create category")


@router.post("/kaban/transactions")
@limiter.limit("30/minute")
async def create_kaban_transaction(
    request: Request,
    transaction_request: TransactionRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Add a new expense or income transaction - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can create transactions

    try:
        # Verify category exists and user has access to it (default or user's custom)
        category_res = supabase.table('expense_categories').select('id').or_(f'user_id.is.null,user_id.eq.{user_id}').eq('id', transaction_request.category_id).execute()
        if not category_res.data or len(category_res.data) == 0:
            raise HTTPException(status_code=404, detail="Category not found or access denied.")

        tx_data = transaction_request.model_dump()
        tx_data['user_id'] = user_id
        
        # Set transaction_date to today if not provided, and convert to string
        if not tx_data['transaction_date']:
            tx_data['transaction_date'] = str(datetime.date.today())
        else:
            # Convert date to string for JSON serialization
            tx_data['transaction_date'] = str(tx_data['transaction_date'])
        
        # Convert empty string envelope_id to None for proper FK handling
        if 'sahod_envelope_id' in tx_data and not tx_data['sahod_envelope_id']:
            tx_data['sahod_envelope_id'] = None
        
        insert_res = supabase.table('kaban_transactions').insert(tx_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create transaction.")
            
        return insert_res.data[0]
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.exception("create_kaban_transaction failed")
        raise HTTPException(status_code=500, detail="Failed to create transaction")


@router.get("/kaban/transactions")
async def get_kaban_transactions(
    profile: Annotated[dict, Depends(get_user_profile)],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    transaction_type: Optional[str] = None,
    category_id: Optional[str] = None
):
    """Get all transactions with optional filters - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can view their transactions

    try:
        # LAZY EVALUATION: Process any pending recurring transactions first
        await process_pending_recurring_transactions(user_id)
        
        query = supabase.table('kaban_transactions').select('*, expense_categories(name, emoji)').eq('user_id', user_id)
        
        # Apply filters
        if start_date:
            query = query.gte('transaction_date', start_date)
        if end_date:
            query = query.lte('transaction_date', end_date)
        if transaction_type:
            query = query.eq('transaction_type', transaction_type)
        if category_id:
            query = query.eq('category_id', category_id)
        
        tx_res = query.order('transaction_date', desc=True).execute()
        return tx_res.data
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_kaban_transactions failed")
        raise HTTPException(status_code=500, detail="Failed to load transactions")


@router.put("/kaban/transactions/{transaction_id}")
@limiter.limit("60/minute")
async def update_kaban_transaction(
    request: Request,
    transaction_id: str,
    transaction_update: TransactionUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update an existing transaction - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can update their own transactions

    try:
        # Only update fields that are provided (except sahod_envelope_id which can be explicitly null)
        update_data = {}
        for k, v in transaction_update.model_dump().items():
            if k == 'sahod_envelope_id':
                # Always include sahod_envelope_id if it's in the request (can be None to unlink)
                # Also convert empty string to None for proper FK handling
                if k in transaction_update.model_fields_set:
                    update_data[k] = v if v else None  # Empty string becomes None
            elif v is not None:
                update_data[k] = v
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update.")
        
        update_res = supabase.table('kaban_transactions').update(update_data).eq('id', transaction_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=404, detail="Transaction not found or permission denied.")
            
        return update_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_kaban_transaction failed")
        raise HTTPException(status_code=500, detail="Failed to update transaction")


@router.delete("/kaban/transactions/{transaction_id}")
@limiter.limit("60/minute")
async def delete_kaban_transaction(
    request: Request,
    transaction_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Delete a transaction - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can delete their own transactions

    try:
        delete_res = supabase.table('kaban_transactions').delete().eq('id', transaction_id).eq('user_id', user_id).execute()
        
        if not delete_res.data:
            raise HTTPException(status_code=404, detail="Transaction not found or permission denied.")
            
        return {"message": "Transaction deleted successfully", "deleted_id": transaction_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_kaban_transaction failed")
        raise HTTPException(status_code=500, detail="Failed to delete transaction")


@router.get("/kaban/summary")
async def get_kaban_summary(
    profile: Annotated[dict, Depends(get_user_profile)],
    year: Optional[int] = None,
    month: Optional[int] = None
):
    """Get monthly income/expense summary - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can see their summary

    try:
        # Default to current month if not specified
        if not year:
            year = datetime.date.today().year
        if not month:
            month = datetime.date.today().month
        
        # Get start and end dates for the month
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, month + 1, 1)
        
        # Get all transactions for the month
        tx_res = supabase.table('kaban_transactions').select('amount, transaction_type').eq('user_id', user_id).gte('transaction_date', start_date).lt('transaction_date', end_date).execute()
        
        total_income = sum(tx['amount'] for tx in tx_res.data if tx['transaction_type'] == 'income')
        total_expense = sum(tx['amount'] for tx in tx_res.data if tx['transaction_type'] == 'expense')
        balance = total_income - total_expense
        
        return {
            "year": year,
            "month": month,
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": balance,
            "transaction_count": len(tx_res.data)
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_kaban_summary failed")
        raise HTTPException(status_code=500, detail="Failed to load summary")


@router.get("/kaban/stats/category")
async def get_category_stats(
    profile: Annotated[dict, Depends(get_user_profile)],
    year: Optional[int] = None,
    month: Optional[int] = None
):
    """Get spending breakdown by category - Available to all users"""
    user_id = profile['id']
    # No tier check - all authenticated users can see category stats

    try:
        # Default to current month if not specified
        if not year:
            year = datetime.date.today().year
        if not month:
            month = datetime.date.today().month
        
        # Get start and end dates for the month
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, month + 1, 1)
        
        # Get all expense transactions for the month with category info
        tx_res = supabase.table('kaban_transactions').select('amount, category_id, expense_categories(name, emoji)').eq('user_id', user_id).eq('transaction_type', 'expense').gte('transaction_date', start_date).lt('transaction_date', end_date).execute()
        
        # Group by category
        category_totals = {}
        for tx in tx_res.data:
            cat_id = tx['category_id']
            cat_name = tx['expense_categories']['name'] if tx.get('expense_categories') else 'Unknown'
            cat_emoji = tx['expense_categories']['emoji'] if tx.get('expense_categories') else '💰'
            
            if cat_id not in category_totals:
                category_totals[cat_id] = {
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "emoji": cat_emoji,
                    "total": 0,
                    "count": 0
                }
            
            category_totals[cat_id]['total'] += tx['amount']
            category_totals[cat_id]['count'] += 1
        
        # Convert to sorted list
        result = sorted(category_totals.values(), key=lambda x: x['total'], reverse=True)
        
        return {
            "year": year,
            "month": month,
            "categories": result,
            "total_categories": len(result)
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_category_stats failed")
        raise HTTPException(status_code=500, detail="Failed to load category stats")


@router.get("/kaban/export/csv")
async def export_kaban_csv(
    profile: Annotated[dict, Depends(get_user_profile)],
    year: Optional[int] = None,
    month: Optional[int] = None
):
    """
    Export Kaban transactions to CSV format.
    PRO users only.
    
    Returns CSV with columns:
    - Date, Type, Category, Description, Amount, Envelope
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
        
        # Default to current month if not specified
        if not year:
            year = datetime.date.today().year
        if not month:
            month = datetime.date.today().month
        
        # Get start and end dates for the month
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, month + 1, 1)
        
        # Get all transactions for the month with category and envelope info
        tx_res = supabase.table('kaban_transactions') \
            .select('*, expense_categories(name, emoji), sahod_envelopes(name)') \
            .eq('user_id', user_id) \
            .gte('transaction_date', str(start_date)) \
            .lt('transaction_date', str(end_date)) \
            .order('transaction_date', desc=True) \
            .execute()
        
        # Build CSV data
        output = io.BytesIO()
        # Write UTF-8 BOM for Excel compatibility
        output.write(b'\xef\xbb\xbf')
        
        # Wrap in TextIOWrapper for csv.writer
        text_output = io.TextIOWrapper(output, encoding='utf-8', newline='')
        writer = csv.writer(text_output)
        
        # Header
        writer.writerow([
            'Date',
            'Type',
            'Category',
            'Description',
            'Amount (PHP)',
            'Envelope'
        ])
        
        # Data rows
        for tx in tx_res.data:
            category_name = tx.get('expense_categories', {}).get('name', 'Unknown') if tx.get('expense_categories') else 'Unknown'
            envelope_name = tx.get('sahod_envelopes', {}).get('name', '') if tx.get('sahod_envelopes') else ''
            
            writer.writerow([
                tx.get('transaction_date', ''),
                tx.get('transaction_type', '').capitalize(),
                category_name,
                tx.get('description', ''),
                tx.get('amount', 0),
                envelope_name
            ])
        
        # Flush and seek
        text_output.flush()
        output.seek(0)
        
        # Generate filename
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        filename = f"kaban_transactions_{month_names[month-1]}_{year}.csv"
        
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("export_kaban_csv failed")
        raise HTTPException(status_code=500, detail="Failed to export transactions")


# --- AI FINANCIAL ADVISOR ENDPOINTS ---

@router.post("/ai/financial-analysis")
@limiter.limit("5/minute")
async def ai_financial_analysis(
    request: Request,
    analysis_request: AIFinancialAnalysisRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Generate AI-powered financial analysis (Pro only)"""
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Financial Advisor is a Pro feature.")

    try:
        # Build context from transactions
        category_breakdown = {}
        for tx in analysis_request.transactions:
            cat_name = tx.expense_categories.name
            if tx.transaction_type == "expense":
                if cat_name not in category_breakdown:
                    category_breakdown[cat_name] = {"total": 0, "count": 0, "emoji": tx.expense_categories.emoji}
                category_breakdown[cat_name]["total"] += tx.amount
                category_breakdown[cat_name]["count"] += 1
        
        # Sort by total spending
        top_categories = sorted(category_breakdown.items(), key=lambda x: x[1]["total"], reverse=True)[:5]
        
        # Calculate savings rate
        savings_rate = (analysis_request.summary.balance / analysis_request.summary.total_income * 100) if analysis_request.summary.total_income > 0 else 0
        
        # Build analysis prompt based on type
        if analysis_request.analysis_type == "budget":
            # Format spending breakdown
            spending_breakdown_formatted = ""
            for cat_name, cat_data in top_categories:
                percentage = (cat_data["total"] / analysis_request.summary.total_expense * 100) if analysis_request.summary.total_expense > 0 else 0
                spending_breakdown_formatted += f"- {cat_data['emoji']} {cat_name}: ₱{cat_data['total']:,.2f} ({percentage:.1f}%)\n"
            
            system_prompt = f"""
Ikaw si Kaibigan, ang personal financial manager ng user. Ang trabaho mo ay i-analyze ang budget niya at bigyan siya ng actionable "Payo" para maging Masinop.

BRAND VOICE:
- **Tone:** Taglish, Friendly, Direct ("Real Talk").
- **Address:** Call the user "Boss".
- **Style:** Use emojis, bullet points, and short paragraphs. Be specific with peso amounts.
- **Cultural Context:** Understand "Petsa de Peligro", "Tipid", "Ipon", "Sweldo", "Gastos".

USER'S FINANCIAL DATA:
- Monthly Income: ₱{analysis_request.summary.total_income:,.2f}
- Monthly Expenses: ₱{analysis_request.summary.total_expense:,.2f}
- Current Balance: ₱{analysis_request.summary.balance:,.2f}
- Savings Rate: {savings_rate:.1f}%
- Total Transactions: {analysis_request.summary.transaction_count}

SPENDING BREAKDOWN:
{spending_breakdown_formatted}

ANALYSIS STRUCTURE (OUTPUT THIS):

1. **Kamusta ang Cash Flow?**
   - Compare Income vs Expenses.
   - **If Positive:** "✅ Good news, Boss! May natitira ka pa."
   - **If Negative/Tight:** "⚠️ Medyo tight, Boss. Mas malaki ang labas kaysa pasok."

2. **Saan Napunta ang Pera?**
   - List the top 3-4 major categories with peso amount and percentage.
   - Use emojis to make it visual.
   - Call out anything unusually high.

3. **50/30/20 Rule Check**
   - Compare their spending to the ideal budget breakdown:
     - 50% Needs (rent, bills, food essentials)
     - 30% Wants (dining out, entertainment, shopping)
     - 20% Savings
   - Example: "Dapat ₱X ang sa Needs, pero ₱Y ang nagastos mo. Overshoot tayo ng ₱Z."

4. **Payo ni Kaibigan (Actionable Tips)**
   - Give 3-5 specific ways to fix the budget based on THEIR data.
   - Example: "Kung babawasan mo ang Food budget by 10%, may extra ₱X ka for savings."
   - End with encouragement: "Kaya natin 'to, Boss! Adjust lang ng konti."

5. **Take Action (Cross-Sell)**
   - End with this CTA: "Boss, para mamonitor ang progress mo, i-setup na natin ang iyong **Sahod Planner**. Doon mo makikita kung nasusunod ang budget plan na 'to. 📊"

FORMATTING RULES:
- Use **bold** for section headers and key emphasis
- Use emojis at the start of categories and for visual markers
- Use bullet points for lists
- Keep paragraphs short and scannable
- Always show peso amounts with ₱ symbol and proper comma formatting

IMPORTANT: Do NOT end with open-ended questions like "Gusto mo ba...?" — this is a report interface, not a chatbot.
"""
        
        elif analysis_request.analysis_type == "spending":
            # Format spending breakdown with transaction details
            spending_breakdown_formatted = ""
            for cat_name, cat_data in top_categories:
                percentage = (cat_data["total"] / analysis_request.summary.total_expense * 100) if analysis_request.summary.total_expense > 0 else 0
                avg_per_tx = cat_data["total"] / cat_data["count"] if cat_data["count"] > 0 else 0
                spending_breakdown_formatted += f"- {cat_data['emoji']} {cat_name}: ₱{cat_data['total']:,.2f} ({percentage:.1f}%) - {cat_data['count']} transactions (avg ₱{avg_per_tx:,.2f} each)\n"
            
            system_prompt = f"""
Ikaw si Kaibigan, ang personal financial manager ng user. Ang trabaho mo ay i-analyze kung saan napupunta ang pera niya at bigyan siya ng "Tipid Tips" para maging Masinop.

BRAND VOICE:
- **Tone:** Taglish, Friendly, Direct ("Real Talk").
- **Address:** Call the user "Boss".
- **Style:** Use emojis, bullet points, and short paragraphs. Be specific.
- **Cultural Context:** Understand "Budol" (Impulse buy), "Luho" vs "Kailangan", "Petsa de Peligro", delivery culture (GrabFood, Foodpanda).

IMPORTANT RULES:
**Cross-Sell:** If Food spending is high, suggest using the "Kusina" feature of KabanKo.

USER'S FINANCIAL DATA:
- Monthly Income: ₱{analysis_request.summary.total_income:,.2f}
- Monthly Expenses: ₱{analysis_request.summary.total_expense:,.2f}
- Current Balance: ₱{analysis_request.summary.balance:,.2f}
- Total Transactions: {analysis_request.summary.transaction_count}

SPENDING BREAKDOWN:
{spending_breakdown_formatted}

ANALYSIS STRUCTURE (OUTPUT THIS):

1. **Breakdown ng Gastos (Where Did the Money Go?)**
   - List the top 3-4 major categories with peso amount and percentage.
   - Use emojis to make it visual.
   - Example: "🍔 Food & Dining: ₱12,500 (35%) — Malaki 'to, Boss!"

2. **Mga Red Flags at Patterns**
   - Call out high-spending categories directly.
   - **High Food (>30%):** "Mukhang mahilig sa delivery/eat-out? GrabFood/Foodpanda ba 'to? 😅 Try mo gamitin ang 'Kusina' feature natin para makatipid."
   - **High Shopping:** "Maraming 'Add to Cart' moments ah. Budol alert!"
   - **High Entertainment:** "Netflix, Spotify, gaming? Check kung nag-aaccumulate na."
   - **High Bills:** "Fixed expenses are heavy. May subscriptions ba na pwede i-cut?"

3. **Tipid Tips (Actionable Cuts)**
   - Give 3-5 specific ways to reduce spending based on THEIR data.
   - Examples:
     - "Kung ₱12k sa food, try meal prep once a week. Pwede maging ₱8k lang."
     - "Cancel mo muna 'yung isang streaming service. Save ₱300/month."
     - "Limit delivery to weekends lang. Lutuin mo weekdays."

4. **Quick Wins This Month**
   - Suggest 1-2 immediate actions to improve cash flow NOW.
   - Example: "Challenge: No delivery for 1 week. I-compute natin magkano mase-save."

5. **Take Action (Cross-Sell)**
   - End with this CTA: "Boss, para mamonitor natin kung nasusunod ang plano, i-setup na natin ang iyong **Sahod Planner** for next month. Doon natin ilalagay ang targets na 'to. 📊"

FORMATTING RULES:
- Use **bold** for section headers and key emphasis
- Use emojis at the start of categories and for visual markers
- Use bullet points for lists
- Keep paragraphs short and scannable
- Always show peso amounts with ₱ symbol and proper comma formatting

IMPORTANT: Do NOT end with questions like "Gusto mo ba...?" or "Sabihin mo lang" — this is a report interface, not a chatbot. Always end with a clear action step pointing to another feature.
"""
        
        else:  # savings
            emergency_fund_target = analysis_request.summary.total_expense * 6  # 6 months of expenses
            one_month = analysis_request.summary.total_expense
            three_months = analysis_request.summary.total_expense * 3
            six_months = emergency_fund_target
            ideal_savings = analysis_request.summary.total_income * 0.20
            
            # Format top expenses
            top_expenses_formatted = ""
            for cat_name, cat_data in top_categories:
                percentage = (cat_data["total"] / analysis_request.summary.total_expense * 100) if analysis_request.summary.total_expense > 0 else 0
                top_expenses_formatted += f"- {cat_data['emoji']} {cat_name}: ₱{cat_data['total']:,.2f} ({percentage:.1f}%)\n"
            
            system_prompt = f"""
Ikaw si Kaibigan, ang personal financial manager ng user. Ang goal mo ay tulungan siyang mag-ipon ng pera gamit ang practical at Filipino-style strategies.

BRAND VOICE:
- **Tone:** Taglish, Friendly, Encouraging pero Realistic.
- **Address:** Call the user "Boss".
- **Style:** Use emojis, bullet points, and specific peso amounts.
- **Cultural Context:** Understand "Ipon Challenge", "Paluwagan", "Alkansya mentality", Emergency Fund, "Petsa de Peligro".

IMPORTANT RULES:
**Be Realistic:** Don't suggest saving 50% if they are barely surviving. Start small.

USER'S FINANCIAL DATA:
- Monthly Income: ₱{analysis_request.summary.total_income:,.2f}
- Monthly Expenses: ₱{analysis_request.summary.total_expense:,.2f}
- Current Savings This Month: ₱{analysis_request.summary.balance:,.2f}
- Savings Rate: {savings_rate:.1f}%
- Recommended Emergency Fund: ₱{emergency_fund_target:,.2f} (6 months of expenses)

TOP EXPENSES (Opportunities to Save):
{top_expenses_formatted}

ANALYSIS STRUCTURE (OUTPUT THIS):

1. **Savings Rate Check**
   - Evaluate their current savings rate of {savings_rate:.1f}%.
   - **If <10%:** "🚨 Boss, below 10% ang savings rate mo. Delikado 'to pag may emergency."
   - **If 10-20%:** "👍 Okay na, Boss! Good start. Pero pwede pa natin dagdagan para mas mabilis."
   - **If >20%:** "🎉 Solid, Boss! Masinop ka. Mataas ang savings rate mo. Keep it up!"
   - Context: "Ideal target: 20% ng income = ₱{ideal_savings:,.2f}/month."

2. **Emergency Fund Roadmap (Iwas-Stress Fund)**
   - Target: ₱{emergency_fund_target:,.2f} (6 months expenses)
   - Break it down into achievable milestones:
     - "🏁 Step 1: Mag-ipon muna ng 1 month worth = ₱{one_month:,.2f}"
     - "🛡️ Step 2: Build to 3 months = ₱{three_months:,.2f}"
     - "🏰 Step 3: Full 6 months = ₱{six_months:,.2f}"
   - Give a rough timeline estimation based on their current saving speed.

3. **Saan Pwede Mag-Cut (Savings Opportunities)**
   - Look at their Top Expenses. Be specific.
   - Example: "Kung babawasan mo ang Food budget by 20%, may extra ₱X ka na straight sa savings."

4. **Payo ni Kaibigan (Ipon Strategies)**
   - Suggest 2-3 Filipino-style saving methods:
     - "52-Week Ipon Challenge: Start small, palaki nang palaki."
     - "Invisible Ipon (Auto-Debit): Set up auto-transfer every payday. 'Di mo na mararamdaman."
     - "Alkansya Method: Lahat ng barya, hulog agad. Monthly mo buksan."
     - "No-Spend Days: Pick 2 days a week na walang gastos sa labas."
   - End with encouragement: "Kaya mo 'to, Boss! Unti-unti lang, may mararating din."

5. **Take Action Now (Cross-Sell)**
   - End with this CTA: "Boss, huwag na natin patagalin. Pumunta sa **'Pera' (Goals)** tab at i-create ang iyong 'Emergency Fund' goal ngayon na. Ilagay mo ang target na ₱{emergency_fund_target:,.2f} para makita mo ang progress bar mo araw-araw. Simulan na natin! 🎯"

FORMATTING RULES:
- Use **bold** for section headers and key emphasis
- Use emojis at the start of milestones and for visual markers (🏁, 🛡️, 🏰, 🚨, 👍, 🎉)
- Use bullet points for lists
- Keep paragraphs short and scannable
- Always show peso amounts with ₱ symbol and proper comma formatting

IMPORTANT: Do NOT end with questions like "Sabihin mo kung gusto mo..." or open-ended invitations — this is a report interface, not a chatbot. Always end with a clear action step pointing to another feature.
"""
        
        # Call OpenAI with correct model
        tier = profile['tier']
        model_to_use = "gpt-5-mini" if tier == "pro" else "gpt-5-nano"
        user_message = f"Please analyze my finances and provide personalized {analysis_request.analysis_type} insights."
        
        chat_completion = await client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        
        ai_response = chat_completion.choices[0].message.content
        return {"analysis": ai_response}

    except HTTPException:
        raise
    except Exception:
        logger.exception("ai_financial_analysis failed")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")


@router.post("/ai/financial-chat")
@limiter.limit("5/minute")
async def ai_financial_chat(
    request: Request,
    chat_request: AIFinancialChatRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Conversational AI financial assistant (Pro only)"""
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Financial Advisor is a Pro feature.")

    try:
        # Build context from transactions
        category_breakdown = {}
        for tx in chat_request.transactions:
            cat_name = tx.expense_categories.name
            if tx.transaction_type == "expense":
                if cat_name not in category_breakdown:
                    category_breakdown[cat_name] = {"total": 0, "count": 0, "emoji": tx.expense_categories.emoji}
                category_breakdown[cat_name]["total"] += tx.amount
                category_breakdown[cat_name]["count"] += 1
        
        top_categories = sorted(category_breakdown.items(), key=lambda x: x[1]["total"], reverse=True)[:5]
        savings_rate = (chat_request.summary.balance / chat_request.summary.total_income * 100) if chat_request.summary.total_income > 0 else 0
        
        # Format spending breakdown
        spending_breakdown_formatted = ""
        for cat_name, cat_data in top_categories:
            percentage = (cat_data["total"] / chat_request.summary.total_expense * 100) if chat_request.summary.total_expense > 0 else 0
            spending_breakdown_formatted += f"- {cat_data['emoji']} {cat_name}: ₱{cat_data['total']:,.2f} ({percentage:.1f}%) - {cat_data['count']} transactions\n"
        
        # Build system prompt with user's financial context
        system_prompt = f"""
Ikaw si Kaibigan, ang personal financial manager ng user. Ito ay isang chat interface — pwede ka makipag-usap naturally.

BRAND VOICE:
- **Tone:** Taglish, Friendly, Direct ("Real Talk") pero approachable.
- **Address:** Call the user "Boss".
- **Style:** Use emojis sparingly, be conversational. Keep replies short (2-4 paragraphs max unless they ask for details).
- **Cultural Context:** Understand "Budol", "Petsa de Peligro", "Ipon", "Tipid", "Sweldo", "Paluwagan", delivery culture (GrabFood, Foodpanda).

CROSS-SELL (When Relevant):
- If they ask about tracking expenses and income → mention "Kaibigan Kaban" or just "Kaban"
- If they ask about meal planning or food costs → mention "Kusina" feature
- If they ask about budget planning → mention "Sahod Planner"
- If they ask about saving goals → mention "Ipon" or "Kaibigan Ipon" tab

USER'S FINANCIAL DATA:
- Monthly Income: ₱{chat_request.summary.total_income:,.2f}
- Monthly Expenses: ₱{chat_request.summary.total_expense:,.2f}
- Current Balance: ₱{chat_request.summary.balance:,.2f}
- Savings Rate: {savings_rate:.1f}%
- Total Transactions: {chat_request.summary.transaction_count}

TOP SPENDING CATEGORIES:
{spending_breakdown_formatted}

GUIDELINES:
- Always use peso amounts (₱) when discussing money
- Reference their actual transactions and spending patterns when relevant
- Be encouraging pero honest — "Real Talk"
- Kung di ka sure sa sagot, sabihin mo honestly
- Keep responses 100-200 words unless they ask for detailed breakdown
- Use **bold** for emphasis on key points
- Use bullet points for lists

FORMATTING:
- Use markdown formatting: **bold** for headers/emphasis, bullet points for lists
- Keep paragraphs short (2-3 sentences max)
- Use emojis sparingly to add personality
"""
        
        # Build messages list with chat history
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history if provided
        if chat_request.chat_history:
            for msg in chat_request.chat_history:
                messages.append({"role": msg.role, "content": msg.content})
        
        # Add current user message
        messages.append({"role": "user", "content": chat_request.message})
        
        # Call OpenAI with correct model
        tier = profile['tier']
        model_to_use = "gpt-5-mini" if tier == "pro" else "gpt-5-nano"
        
        chat_completion = await client.chat.completions.create(
            model=model_to_use,
            messages=messages
        )
        
        ai_response = chat_completion.choices[0].message.content
        return {"response": ai_response}

    except HTTPException:
        raise
    except Exception:
        logger.exception("ai_financial_chat failed")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")


# --- RECURRING INCOME ENDPOINTS ---

def get_scheduled_dates_for_rule(rule: dict, check_month: int, check_year: int) -> List[datetime.date]:
    """
    Calculate which dates should have transactions for a given rule and month.
    Returns list of dates that are scheduled for that month.
    """
    dates = []
    frequency = rule['frequency']
    schedule_day = rule['schedule_day']
    
    if frequency == 'monthly':
        # Single day per month
        try:
            # Handle months with fewer days (e.g., Feb 30 -> Feb 28)
            last_day = (datetime.date(check_year, check_month + 1, 1) - datetime.timedelta(days=1)).day if check_month < 12 else 31
            actual_day = min(schedule_day, last_day)
            dates.append(datetime.date(check_year, check_month, actual_day))
        except ValueError:
            pass
            
    elif frequency == 'bimonthly':
        # Two days per month: schedule_day and schedule_day + 15
        try:
            last_day = (datetime.date(check_year, check_month + 1, 1) - datetime.timedelta(days=1)).day if check_month < 12 else 31
            
            # First payday
            first_day = min(schedule_day, last_day)
            dates.append(datetime.date(check_year, check_month, first_day))
            
            # Second payday (15 days later, or end of month)
            second_day = min(schedule_day + 15, last_day)
            if second_day != first_day:
                dates.append(datetime.date(check_year, check_month, second_day))
        except ValueError:
            pass
            
    elif frequency == 'weekly':
        # Every week on the specified day (0=Monday, 6=Sunday)
        first_of_month = datetime.date(check_year, check_month, 1)
        last_day = (datetime.date(check_year, check_month + 1, 1) - datetime.timedelta(days=1)).day if check_month < 12 else 31
        
        # Find first occurrence of the weekday in the month
        days_until_target = (schedule_day - first_of_month.weekday()) % 7
        current = first_of_month + datetime.timedelta(days=days_until_target)
        
        while current.month == check_month:
            dates.append(current)
            current += datetime.timedelta(days=7)
    
    return dates


async def process_pending_recurring_transactions(user_id: str):
    """
    Lazy evaluation: Check for pending recurring transactions and insert them.
    Called when user fetches transactions.
    """
    today = datetime.date.today()
    
    try:
        # Get all active recurring rules for this user
        rules_res = supabase.table('recurring_rules').select('*').eq('user_id', user_id).eq('is_active', True).execute()
        
        if not rules_res.data:
            return  # No rules, nothing to do
        
        for rule in rules_res.data:
            rule_id = rule['id']
            last_posted = datetime.date.fromisoformat(rule['last_posted_date']) if rule.get('last_posted_date') else None
            rule_created = datetime.datetime.fromisoformat(rule['created_at'].replace('Z', '+00:00')).date()
            
            # Check current month and previous month (for users who open after month end)
            months_to_check = [
                (today.year, today.month),
            ]
            # Add previous month
            if today.month == 1:
                months_to_check.append((today.year - 1, 12))
            else:
                months_to_check.append((today.year, today.month - 1))
            
            for check_year, check_month in months_to_check:
                scheduled_dates = get_scheduled_dates_for_rule(rule, check_month, check_year)
                
                for scheduled_date in scheduled_dates:
                    # Skip if:
                    # 1. Date is in the future
                    # 2. Date is before rule was created
                    # 3. Date was already posted (check last_posted_date or existing transaction)
                    if scheduled_date > today:
                        continue
                    if scheduled_date < rule_created:
                        continue
                    if last_posted and scheduled_date <= last_posted:
                        continue
                    
                    # Check if transaction already exists for this rule and date (idempotency)
                    existing_res = supabase.table('kaban_transactions').select('id').eq('user_id', user_id).eq('recurring_rule_id', rule_id).eq('transaction_date', str(scheduled_date)).execute()
                    
                    if existing_res.data and len(existing_res.data) > 0:
                        continue  # Already posted, skip
                    
                    # Insert the recurring transaction
                    tx_data = {
                        'user_id': user_id,
                        'category_id': rule['category_id'],
                        'amount': rule['amount'],
                        'description': rule.get('description') or 'Recurring Income',
                        'transaction_type': rule['transaction_type'],
                        'transaction_date': str(scheduled_date),
                        'source': 'recurring',
                        'recurring_rule_id': rule_id
                    }
                    
                    insert_res = supabase.table('kaban_transactions').insert(tx_data).execute()
                    
                    if insert_res.data:
                        # Update last_posted_date on the rule
                        supabase.table('recurring_rules').update({
                            'last_posted_date': str(scheduled_date),
                            'updated_at': datetime.datetime.now().isoformat()
                        }).eq('id', rule_id).execute()
                        
                        logger.info("[Recurring] Auto-posted transaction for rule %s on %s", rule_id, scheduled_date)
                        
    except Exception as e:
        logger.exception("[Recurring] Error processing pending transactions")
        # Don't raise - this should not block the main request


@router.post("/kaban/recurring")
@limiter.limit("30/minute")
async def create_recurring_rule(
    request: Request,
    recurring_request: RecurringRuleCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new recurring income/expense rule - Available to all users"""
    user_id = profile['id']
    
    # Validate schedule_day based on frequency
    if recurring_request.frequency == 'monthly' and not (1 <= recurring_request.schedule_day <= 31):
        raise HTTPException(status_code=400, detail="For monthly frequency, schedule_day must be 1-31")
    if recurring_request.frequency == 'bimonthly' and not (1 <= recurring_request.schedule_day <= 15):
        raise HTTPException(status_code=400, detail="For bimonthly frequency, schedule_day must be 1-15 (second payday is auto-calculated)")
    if recurring_request.frequency == 'weekly' and not (0 <= recurring_request.schedule_day <= 6):
        raise HTTPException(status_code=400, detail="For weekly frequency, schedule_day must be 0-6 (0=Monday, 6=Sunday)")
    
    try:
        # Verify category exists (only if provided)
        if recurring_request.category_id:
            category_res = supabase.table('expense_categories').select('id').or_(f'user_id.is.null,user_id.eq.{user_id}').eq('id', recurring_request.category_id).execute()
            if not category_res.data:
                raise HTTPException(status_code=404, detail="Category not found")
        
        # Check for duplicate rule (same amount, description, frequency, schedule_day)
        existing_query = supabase.table('recurring_rules').select('id').eq('user_id', user_id).eq('amount', recurring_request.amount).eq('frequency', recurring_request.frequency).eq('schedule_day', recurring_request.schedule_day).eq('is_active', True)
        if recurring_request.category_id:
            existing_query = existing_query.eq('category_id', recurring_request.category_id)
        existing_res = existing_query.execute()
        
        if existing_res.data and len(existing_res.data) > 0:
            raise HTTPException(status_code=400, detail="A similar recurring rule already exists. Delete the existing rule first or use different settings.")
        
        rule_data = recurring_request.model_dump()
        rule_data['user_id'] = user_id
        
        insert_res = supabase.table('recurring_rules').insert(rule_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create recurring rule")
        
        return insert_res.data[0]
        
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_recurring_rule failed")
        raise HTTPException(status_code=500, detail="Failed to create recurring rule")


@router.get("/kaban/recurring")
async def get_recurring_rules(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all recurring rules for the user - Available to all users"""
    user_id = profile['id']
    
    try:
        rules_res = supabase.table('recurring_rules').select('*, expense_categories(name, emoji)').eq('user_id', user_id).order('created_at', desc=True).execute()
        return rules_res.data
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_recurring_rules failed")
        raise HTTPException(status_code=500, detail="Failed to load recurring rules")


@router.put("/kaban/recurring/{rule_id}")
@limiter.limit("60/minute")
async def update_recurring_rule(
    request: Request,
    rule_id: str,
    recurring_update: RecurringRuleUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update a recurring rule - Available to all users"""
    user_id = profile['id']
    
    try:
        update_data = {k: v for k, v in recurring_update.model_dump().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        update_data['updated_at'] = datetime.datetime.now().isoformat()
        
        update_res = supabase.table('recurring_rules').update(update_data).eq('id', rule_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=404, detail="Recurring rule not found or permission denied")
        
        return update_res.data[0]
        
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_recurring_rule failed")
        raise HTTPException(status_code=500, detail="Failed to update recurring rule")


@router.patch("/kaban/recurring/{rule_id}/pause")
@limiter.limit("60/minute")
async def toggle_recurring_rule_pause(
    request: Request,
    rule_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Toggle pause/resume for a recurring rule - Available to all users"""
    user_id = profile['id']
    
    try:
        # First, get the current state
        rule_res = supabase.table('recurring_rules').select('is_active').eq('id', rule_id).eq('user_id', user_id).execute()
        
        if not rule_res.data:
            raise HTTPException(status_code=404, detail="Recurring rule not found or permission denied")
        
        current_is_active = rule_res.data[0]['is_active']
        new_is_active = not current_is_active
        
        # Update the is_active status
        update_res = supabase.table('recurring_rules').update({
            'is_active': new_is_active,
            'updated_at': datetime.datetime.now().isoformat()
        }).eq('id', rule_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=500, detail="Failed to update rule status")
        
        action = "resumed" if new_is_active else "paused"
        logger.info("[Recurring] Rule %s %s by user %s", rule_id, action, user_id)
        
        return {
            "message": f"Recurring rule {action} successfully",
            "rule_id": rule_id,
            "is_active": new_is_active,
            "action": action
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("toggle_recurring_rule_pause failed")
        raise HTTPException(status_code=500, detail="Failed to toggle recurring rule pause status")


@router.delete("/kaban/recurring/{rule_id}")
@limiter.limit("60/minute")
async def delete_recurring_rule(
    request: Request,
    rule_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Delete a recurring rule - Available to all users"""
    user_id = profile['id']
    
    try:
        delete_res = supabase.table('recurring_rules').delete().eq('id', rule_id).eq('user_id', user_id).execute()
        
        if not delete_res.data:
            raise HTTPException(status_code=404, detail="Recurring rule not found or permission denied")
        
        return {"message": "Recurring rule deleted successfully", "deleted_id": rule_id}
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_recurring_rule failed")
        raise HTTPException(status_code=500, detail="Failed to delete recurring rule")


# ============================================
# QUICK ADD SHORTCUTS
# ============================================

class QuickAddShortcutCreate(BaseModel):
    emoji: str = "💰"
    label: str
    default_amount: float
    category_id: Optional[str] = None
    sahod_envelope_id: Optional[str] = None  # Link to Sahod envelope

class QuickAddShortcutUpdate(BaseModel):
    emoji: Optional[str] = None
    label: Optional[str] = None
    default_amount: Optional[float] = None
    category_id: Optional[str] = None
    sahod_envelope_id: Optional[str] = None  # Link to Sahod envelope


@router.get("/kaban/shortcuts")
@limiter.limit("60/minute")
async def get_quick_add_shortcuts(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get user's quick-add shortcuts, ordered by usage"""
    user_id = profile['id']
    
    try:
        result = supabase.table('quick_add_shortcuts') \
            .select('*, expense_categories(id, name, emoji, type)') \
            .eq('user_id', user_id) \
            .order('usage_count', desc=True) \
            .order('created_at', desc=False) \
            .execute()
        
        return result.data or []
        
    except Exception:
        logger.exception("get_quick_add_shortcuts failed")
        raise HTTPException(status_code=500, detail="Failed to fetch shortcuts")


@router.post("/kaban/shortcuts")
@limiter.limit("30/minute")
async def create_quick_add_shortcut(
    request: Request,
    shortcut: QuickAddShortcutCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new quick-add shortcut (max 12 per user)"""
    user_id = profile['id']
    
    try:
        # Check for duplicate label (case-insensitive)
        existing_res = supabase.table('quick_add_shortcuts') \
            .select('id, label') \
            .eq('user_id', user_id) \
            .ilike('label', shortcut.label) \
            .execute()
        
        if existing_res.data and len(existing_res.data) > 0:
            # Return existing shortcut instead of creating duplicate
            return existing_res.data[0]
        
        # Check current count
        count_res = supabase.table('quick_add_shortcuts') \
            .select('id', count='exact') \
            .eq('user_id', user_id) \
            .execute()
        
        if count_res.count and count_res.count >= 12:
            raise HTTPException(
                status_code=400, 
                detail="Maximum of 12 shortcuts allowed. Delete one to add a new shortcut."
            )
        
        insert_data = {
            "user_id": user_id,
            "emoji": shortcut.emoji,
            "label": shortcut.label,
            "default_amount": shortcut.default_amount,
            "category_id": shortcut.category_id,
            "sahod_envelope_id": shortcut.sahod_envelope_id,
            "is_system_default": False,
            "usage_count": 0
        }
        
        result = supabase.table('quick_add_shortcuts').insert(insert_data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create shortcut")
        
        return result.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create_quick_add_shortcut failed")
        if "Maximum of 12 shortcuts" in str(e):
            raise HTTPException(status_code=400, detail="Maximum of 12 shortcuts allowed")
        raise HTTPException(status_code=500, detail="Failed to create shortcut")


@router.put("/kaban/shortcuts/{shortcut_id}")
@limiter.limit("30/minute")
async def update_quick_add_shortcut(
    request: Request,
    shortcut_id: str,
    shortcut: QuickAddShortcutUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update a quick-add shortcut"""
    user_id = profile['id']
    
    try:
        update_data = {}
        if shortcut.emoji is not None:
            update_data['emoji'] = shortcut.emoji
        if shortcut.label is not None:
            update_data['label'] = shortcut.label
        if shortcut.default_amount is not None:
            update_data['default_amount'] = shortcut.default_amount
        if shortcut.category_id is not None:
            update_data['category_id'] = shortcut.category_id
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        result = supabase.table('quick_add_shortcuts') \
            .update(update_data) \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Shortcut not found or permission denied")
        
        return result.data[0]
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_quick_add_shortcut failed")
        raise HTTPException(status_code=500, detail="Failed to update shortcut")


@router.delete("/kaban/shortcuts/{shortcut_id}")
@limiter.limit("30/minute")
async def delete_quick_add_shortcut(
    request: Request,
    shortcut_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Delete a quick-add shortcut"""
    user_id = profile['id']
    
    try:
        result = supabase.table('quick_add_shortcuts') \
            .delete() \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Shortcut not found or permission denied")
        
        return {"message": "Shortcut deleted successfully", "deleted_id": shortcut_id}
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_quick_add_shortcut failed")
        raise HTTPException(status_code=500, detail="Failed to delete shortcut")


@router.get("/kaban/shortcuts/auto-suggestions")
@limiter.limit("30/minute")
async def get_auto_shortcut_suggestions(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Analyze user's frequent expense patterns and suggest new shortcuts.
    Returns top 3 frequent expense descriptions that don't have shortcuts yet.
    """
    user_id = profile['id']
    
    try:
        # Get existing shortcuts for this user
        existing = supabase.table('quick_add_shortcuts') \
            .select('label') \
            .eq('user_id', user_id) \
            .execute()
        
        existing_labels = set(
            s.get('label', '').lower() 
            for s in (existing.data or [])
        )
        
        # Count how many shortcuts user already has
        shortcut_count = len(existing.data or [])
        
        # If user has max shortcuts, don't suggest more
        if shortcut_count >= 12:
            return {"suggestions": [], "reason": "max_shortcuts_reached"}
        
        # Get frequent expenses from last 60 days without shortcuts
        sixty_days_ago = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
        ).date().isoformat()
        
        # Query frequent expense patterns
        # Group by description and category to find patterns
        transactions = supabase.table('kaban_transactions') \
            .select('description, category_id, amount, expense_categories(id, name, emoji)') \
            .eq('user_id', user_id) \
            .eq('transaction_type', 'expense') \
            .gte('transaction_date', sixty_days_ago) \
            .not_.is_('description', 'null') \
            .order('transaction_date', desc=True) \
            .limit(500) \
            .execute()
        
        if not transactions.data:
            return {"suggestions": [], "reason": "no_transactions"}
        
        # Aggregate by description (case-insensitive)
        from collections import defaultdict
        patterns = defaultdict(lambda: {
            'count': 0, 
            'total_amount': 0, 
            'amounts': [],
            'category_id': None,
            'category_name': None,
            'category_emoji': None
        })
        
        for tx in transactions.data:
            desc = (tx.get('description') or '').strip()
            if not desc or len(desc) < 2:
                continue
                
            # Normalize description for grouping
            desc_key = desc.lower()
            
            # Skip if already has a shortcut with similar label
            if any(existing_label in desc_key or desc_key in existing_label 
                   for existing_label in existing_labels if existing_label):
                continue
            
            patterns[desc_key]['count'] += 1
            patterns[desc_key]['total_amount'] += tx.get('amount', 0)
            patterns[desc_key]['amounts'].append(tx.get('amount', 0))
            patterns[desc_key]['original_desc'] = desc  # Keep original casing
            
            # Store category info from first occurrence
            if patterns[desc_key]['category_id'] is None:
                patterns[desc_key]['category_id'] = tx.get('category_id')
                cat = tx.get('expense_categories')
                if cat:
                    patterns[desc_key]['category_name'] = cat.get('name')
                    patterns[desc_key]['category_emoji'] = cat.get('emoji')
        
        # Filter patterns with at least 3 occurrences and sort by count
        frequent = [
            (desc, data) for desc, data in patterns.items() 
            if data['count'] >= 3
        ]
        frequent.sort(key=lambda x: x[1]['count'], reverse=True)
        
        # Build suggestions (top 3)
        suggestions = []
        for desc_key, data in frequent[:3]:
            # Calculate median amount
            amounts = sorted(data['amounts'])
            mid = len(amounts) // 2
            if len(amounts) % 2 == 0:
                median = (amounts[mid - 1] + amounts[mid]) / 2
            else:
                median = amounts[mid]
            
            # Round to nearest 5
            suggested_amount = round(median / 5) * 5
            if suggested_amount < 5:
                suggested_amount = 5
            
            # Suggest emoji based on category or generic
            emoji = data.get('category_emoji') or '💸'
            
            suggestions.append({
                "label": data['original_desc'],
                "suggested_amount": suggested_amount,
                "emoji": emoji,
                "category_id": data['category_id'],
                "category_name": data.get('category_name') or 'Other',
                "frequency": data['count'],
                "frequency_text": f"Used {data['count']} times"
            })
        
        return {
            "suggestions": suggestions,
            "current_shortcut_count": shortcut_count,
            "max_shortcuts": 12
        }
        
    except Exception:
        logger.exception("get_auto_shortcut_suggestions failed")
        raise HTTPException(status_code=500, detail="Failed to analyze patterns")


@router.get("/kaban/shortcuts/time-based-order")
@limiter.limit("60/minute")
async def get_time_based_shortcut_order(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Get shortcut IDs ordered by time-of-day relevance.
    Analyzes when each shortcut is typically used and returns them
    sorted by relevance to the current hour.
    
    Time slots:
    - Morning (6-10): Breakfast, coffee, commute
    - Lunch (11-14): Meals
    - Afternoon (14-17): Snacks, meryenda
    - Evening (17-21): Dinner, groceries
    - Night (21-6): Late night, entertainment
    """
    user_id = profile['id']
    
    try:
        # Get user's shortcuts
        shortcuts = supabase.table('quick_add_shortcuts') \
            .select('id, label') \
            .eq('user_id', user_id) \
            .execute()
        
        if not shortcuts.data:
            return {"ordered_ids": [], "current_slot": "unknown"}
        
        shortcut_ids = [s['id'] for s in shortcuts.data]
        
        # Get current hour (Philippine Time, UTC+8)
        import pytz
        ph_tz = pytz.timezone('Asia/Manila')
        current_hour = datetime.datetime.now(ph_tz).hour
        
        # Define time slot
        if 6 <= current_hour < 11:
            time_slot = "morning"
            slot_hours = list(range(6, 11))
        elif 11 <= current_hour < 14:
            time_slot = "lunch"
            slot_hours = list(range(11, 14))
        elif 14 <= current_hour < 17:
            time_slot = "afternoon"
            slot_hours = list(range(14, 17))
        elif 17 <= current_hour < 21:
            time_slot = "evening"
            slot_hours = list(range(17, 21))
        else:
            time_slot = "night"
            slot_hours = list(range(21, 24)) + list(range(0, 6))
        
        # Query transactions with timestamps to analyze usage patterns
        # Get last 60 days of transactions linked to shortcuts
        sixty_days_ago = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
        ).date().isoformat()
        
        transactions = supabase.table('kaban_transactions') \
            .select('shortcut_id, created_at') \
            .eq('user_id', user_id) \
            .eq('transaction_type', 'expense') \
            .not_.is_('shortcut_id', 'null') \
            .gte('transaction_date', sixty_days_ago) \
            .execute()
        
        if not transactions.data:
            # No transaction data, return default order (by usage)
            return {
                "ordered_ids": shortcut_ids,
                "current_slot": time_slot,
                "reason": "no_transaction_data"
            }
        
        # Count usage per shortcut per time slot
        from collections import defaultdict
        slot_usage = defaultdict(lambda: defaultdict(int))
        
        for tx in transactions.data:
            shortcut_id = tx.get('shortcut_id')
            created_at = tx.get('created_at')
            
            if not shortcut_id or not created_at:
                continue
            
            # Parse timestamp and get hour
            try:
                # created_at is typically ISO format
                tx_time = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                tx_hour = tx_time.astimezone(ph_tz).hour
                
                # Determine which slot this transaction belongs to
                if 6 <= tx_hour < 11:
                    tx_slot = "morning"
                elif 11 <= tx_hour < 14:
                    tx_slot = "lunch"
                elif 14 <= tx_hour < 17:
                    tx_slot = "afternoon"
                elif 17 <= tx_hour < 21:
                    tx_slot = "evening"
                else:
                    tx_slot = "night"
                
                slot_usage[shortcut_id][tx_slot] += 1
            except (ValueError, AttributeError):
                continue
        
        # Score each shortcut based on current time slot usage
        scores = []
        for shortcut_id in shortcut_ids:
            usage_in_slot = slot_usage[shortcut_id].get(time_slot, 0)
            total_usage = sum(slot_usage[shortcut_id].values())
            
            # Score = usage in current slot + small bonus for overall usage
            score = (usage_in_slot * 10) + (total_usage * 0.1)
            scores.append((shortcut_id, score, usage_in_slot))
        
        # Sort by score (highest first)
        scores.sort(key=lambda x: x[1], reverse=True)
        
        ordered_ids = [s[0] for s in scores]
        
        return {
            "ordered_ids": ordered_ids,
            "current_slot": time_slot,
            "current_hour": current_hour,
            "slot_data": {
                s[0]: {"slot_usage": s[2], "score": round(s[1], 1)}
                for s in scores[:5]  # Return top 5 for debugging
            }
        }
        
    except Exception:
        logger.exception("get_time_based_shortcut_order failed")
        raise HTTPException(status_code=500, detail="Failed to get time-based order")


@router.post("/kaban/shortcuts/{shortcut_id}/use")
@limiter.limit("120/minute")
async def increment_shortcut_usage(
    request: Request,
    shortcut_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Increment usage count when a shortcut is used"""
    user_id = profile['id']
    
    try:
        # Get current usage count
        current = supabase.table('quick_add_shortcuts') \
            .select('usage_count') \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not current.data:
            raise HTTPException(status_code=404, detail="Shortcut not found")
        
        new_count = (current.data.get('usage_count') or 0) + 1
        
        result = supabase.table('quick_add_shortcuts') \
            .update({
                'usage_count': new_count,
                'last_used_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }) \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .execute()
        
        return {"usage_count": new_count}
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("increment_shortcut_usage failed")
        raise HTTPException(status_code=500, detail="Failed to update usage count")


@router.get("/kaban/shortcuts/{shortcut_id}/suggested-amount")
@limiter.limit("30/minute")
async def get_suggested_amount(
    request: Request,
    shortcut_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    Get AI-suggested amount for a shortcut based on user's spending patterns.
    Returns suggested amount if user has 5+ similar transactions in last 60 days.
    """
    user_id = profile['id']
    
    try:
        # Get the shortcut details
        shortcut = supabase.table('quick_add_shortcuts') \
            .select('id, label, category_id, default_amount, suggested_amount, suggestion_dismissed') \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not shortcut.data:
            raise HTTPException(status_code=404, detail="Shortcut not found")
        
        shortcut_data = shortcut.data
        
        # If suggestion was dismissed, don't recalculate unless significant time passed
        if shortcut_data.get('suggestion_dismissed'):
            return {
                "has_suggestion": False,
                "current_amount": shortcut_data['default_amount'],
                "reason": "suggestion_dismissed"
            }
        
        category_id = shortcut_data.get('category_id')
        label = shortcut_data.get('label', '')
        current_amount = shortcut_data.get('default_amount', 0)
        
        if not category_id:
            return {
                "has_suggestion": False,
                "current_amount": current_amount,
                "reason": "no_category"
            }
        
        # Calculate suggested amount using database function
        # First try with label-matching transactions
        sixty_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)).date().isoformat()
        
        # Get transactions matching category and optionally label
        similar_txs = supabase.table('kaban_transactions') \
            .select('amount, description') \
            .eq('user_id', user_id) \
            .eq('category_id', category_id) \
            .eq('transaction_type', 'expense') \
            .gte('transaction_date', sixty_days_ago) \
            .order('transaction_date', desc=True) \
            .limit(30) \
            .execute()
        
        transactions = similar_txs.data or []
        
        # Filter by label if we have enough
        label_lower = label.lower()
        label_matching = [t for t in transactions if t.get('description') and label_lower in t.get('description', '').lower()]
        
        if len(label_matching) >= 5:
            amounts = sorted([t['amount'] for t in label_matching])
        elif len(transactions) >= 5:
            amounts = sorted([t['amount'] for t in transactions])
        else:
            return {
                "has_suggestion": False,
                "current_amount": current_amount,
                "reason": "insufficient_data",
                "transaction_count": len(transactions)
            }
        
        # Calculate median
        mid = len(amounts) // 2
        if len(amounts) % 2 == 0:
            median = (amounts[mid - 1] + amounts[mid]) / 2
        else:
            median = amounts[mid]
        
        # Round to nearest 5
        suggested = round(median / 5) * 5
        
        # Only suggest if difference is significant (>10%)
        diff_percent = abs(suggested - current_amount) / current_amount if current_amount > 0 else 1
        
        if diff_percent < 0.10:
            return {
                "has_suggestion": False,
                "current_amount": current_amount,
                "reason": "no_significant_difference"
            }
        
        # Update the suggested amount in database
        supabase.table('quick_add_shortcuts') \
            .update({
                'suggested_amount': suggested,
                'suggestion_shown_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
            }) \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .execute()
        
        return {
            "has_suggestion": True,
            "current_amount": current_amount,
            "suggested_amount": suggested,
            "based_on_transactions": len(label_matching) if len(label_matching) >= 5 else len(transactions),
            "diff_percent": round(diff_percent * 100, 1)
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_suggested_amount failed")
        raise HTTPException(status_code=500, detail="Failed to calculate suggested amount")


class AcceptSuggestionRequest(BaseModel):
    accept: bool  # True to accept, False to dismiss


@router.post("/kaban/shortcuts/{shortcut_id}/suggested-amount")
@limiter.limit("30/minute")
async def respond_to_suggestion(
    request: Request,
    shortcut_id: str,
    body: AcceptSuggestionRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Accept or dismiss a suggested amount for a shortcut"""
    user_id = profile['id']
    
    try:
        # Get current shortcut
        shortcut = supabase.table('quick_add_shortcuts') \
            .select('id, default_amount, suggested_amount') \
            .eq('id', shortcut_id) \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not shortcut.data:
            raise HTTPException(status_code=404, detail="Shortcut not found")
        
        shortcut_data = shortcut.data
        suggested = shortcut_data.get('suggested_amount')
        
        if body.accept and suggested:
            # Accept: update default_amount to suggested
            result = supabase.table('quick_add_shortcuts') \
                .update({
                    'default_amount': suggested,
                    'suggested_amount': None,
                    'suggestion_dismissed': False
                }) \
                .eq('id', shortcut_id) \
                .eq('user_id', user_id) \
                .execute()
            
            return {
                "message": "Amount updated successfully",
                "new_amount": suggested
            }
        else:
            # Dismiss: mark as dismissed
            result = supabase.table('quick_add_shortcuts') \
                .update({
                    'suggestion_dismissed': True,
                    'suggested_amount': None
                }) \
                .eq('id', shortcut_id) \
                .eq('user_id', user_id) \
                .execute()
            
            return {
                "message": "Suggestion dismissed",
                "current_amount": shortcut_data.get('default_amount')
            }
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("respond_to_suggestion failed")
        raise HTTPException(status_code=500, detail="Failed to process suggestion response")