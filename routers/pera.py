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
    category_id: str
    transaction_type: str = "income"  # "income" or "expense"
    frequency: str  # "monthly", "bimonthly", "weekly"
    schedule_day: int  # Day of month (1-31) or day of week (0-6)

class RecurringRuleUpdate(BaseModel):
    amount: Optional[float] = None
    description: Optional[str] = None
    category_id: Optional[str] = None
    frequency: Optional[str] = None
    schedule_day: Optional[int] = None
    is_active: Optional[bool] = None

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
    except Exception as e:
        print(f"Ipon Goal Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Goals Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Transaction Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Transactions Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            print(f"Error checking debt count: {e}")

    try:
        utang_data = utang_request.model_dump()
        utang_data['user_id'] = user_id
        
        insert_res = supabase.table('utang').insert(utang_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create utang record.")
            
        return insert_res.data[0]
    except Exception as e:
        print(f"Utang Create Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Utang Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Utang Update Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
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
    except Exception as e:
        print(f"Get Categories Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Create Category Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        
        insert_res = supabase.table('kaban_transactions').insert(tx_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create transaction.")
            
        return insert_res.data[0]
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        print(f"Create Transaction Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Transactions Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
                if k in transaction_update.model_fields_set:
                    update_data[k] = v
            elif v is not None:
                update_data[k] = v
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update.")
        
        update_res = supabase.table('kaban_transactions').update(update_data).eq('id', transaction_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=404, detail="Transaction not found or permission denied.")
            
        return update_res.data[0]
    except Exception as e:
        print(f"Update Transaction Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Delete Transaction Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Summary Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Get Category Stats Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    
    except Exception as e:
        print(f"AI Financial Analysis Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    
    except Exception as e:
        print(f"AI Financial Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
                        
                        print(f"[Recurring] Auto-posted transaction for rule {rule_id} on {scheduled_date}")
                        
    except Exception as e:
        print(f"[Recurring] Error processing pending transactions: {e}")
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
        # Verify category exists
        category_res = supabase.table('expense_categories').select('id').or_(f'user_id.is.null,user_id.eq.{user_id}').eq('id', recurring_request.category_id).execute()
        if not category_res.data:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Check for duplicate rule (same amount, description, category, frequency, schedule_day)
        existing_res = supabase.table('recurring_rules').select('id').eq('user_id', user_id).eq('amount', recurring_request.amount).eq('category_id', recurring_request.category_id).eq('frequency', recurring_request.frequency).eq('schedule_day', recurring_request.schedule_day).eq('is_active', True).execute()
        
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
    except Exception as e:
        print(f"Create Recurring Rule Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kaban/recurring")
async def get_recurring_rules(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all recurring rules for the user - Available to all users"""
    user_id = profile['id']
    
    try:
        rules_res = supabase.table('recurring_rules').select('*, expense_categories(name, emoji)').eq('user_id', user_id).order('created_at', desc=True).execute()
        return rules_res.data
        
    except Exception as e:
        print(f"Get Recurring Rules Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        print(f"Update Recurring Rule Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        
    except Exception as e:
        print(f"Delete Recurring Rule Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
