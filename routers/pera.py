"""
PERA Module Router - Kaibigan Kaban System
Handles all financial management endpoints: Ipon Tracker, Utang Tracker
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Annotated, Optional
from dependencies import get_user_profile, supabase
from openai import OpenAI
import datetime

# Initialize OpenAI client
client = OpenAI()

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

class TransactionRequest(BaseModel):
    category_id: str
    amount: float
    transaction_type: str  # "expense" or "income"
    description: Optional[str] = None
    transaction_date: Optional[datetime.date] = None

class TransactionUpdate(BaseModel):
    category_id: Optional[str] = None
    amount: Optional[float] = None
    transaction_type: Optional[str] = None
    description: Optional[str] = None
    transaction_date: Optional[datetime.date] = None


# --- IPON TRACKER ENDPOINTS ---

@router.post("/ipon/goals")
async def create_ipon_goal(
    request: IponGoalCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new savings goal (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")

    try:
        goal_data = request.model_dump()
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
async def add_ipon_transaction(
    request: TransactionCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Add a transaction to a savings goal (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ipon Tracker is a Pro feature.")
    
    try:
        goal_res = supabase.table('ipon_goals').select('id').eq('id', request.goal_id).eq('user_id', user_id).single().execute()
        if not goal_res.data:
            raise HTTPException(status_code=404, detail="Goal not found or you do not have permission.")

        tx_data = request.model_dump()
        tx_data['user_id'] = user_id
        
        insert_res = supabase.table('transactions').insert(tx_data).execute()
        
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to add transaction.")
        
        return insert_res.data[0]
    except Exception as e:
        print(f"Transaction Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ipon/goals/{goal_id}/transactions")
async def get_goal_transactions(
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
async def create_utang_record(
    request: UtangCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a new debt record (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utang Tracker is a Pro feature.")

    try:
        utang_data = request.model_dump()
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
    """Get all unpaid debts for the user (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utang Tracker is a Pro feature.")

    try:
        utang_res = supabase.table('utang').select('*').eq('user_id', user_id).eq('status', 'unpaid').order('due_date', desc=False).execute()
        return utang_res.data
    except Exception as e:
        print(f"Get Utang Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/utang/debts/{debt_id}")
async def update_utang_status(
    debt_id: str,
    request: UtangUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update debt status (mark as paid/unpaid) (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utang Tracker is a Pro feature.")

    try:
        update_res = supabase.table('utang').update({"status": request.status}).eq('id', debt_id).eq('user_id', user_id).execute()
        
        if not update_res.data:
            raise HTTPException(status_code=404, detail="Utang record not found or permission denied.")
            
        return update_res.data[0]
    except Exception as e:
        print(f"Utang Update Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/utang/generate-message")
async def generate_utang_message(
    request: AICollectorRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Generate AI-powered debt collection message (Pro only)"""
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Collector is a Pro feature.")

    tone_instructions = {
        "Gentle": "a very gentle, friendly, and 'nahihiya' reminder. Start with 'Hi [Name], kumusta?'.",
        "Firm": "a polite but firm and direct reminder that the payment is due.",
        "Final": "a final, urgent, and very serious reminder that the payment is long overdue."
    }
    
    system_prompt = f"""
    You are 'Kaibigan Pera', an AI assistant who helps Filipinos with the awkward task of collecting debt ('maningil').
    Your task is to draft a short, clear, and culturally-appropriate SMS or Messenger message.
    
    TONE: The message must have a {request.tone} tone. Be {tone_instructions.get(request.tone, "a polite tone")}.
    DEBTOR'S NAME: {request.debtor_name}
    AMOUNT: ₱{request.amount:,.2f}
    
    Respond *only* with the message itself. Do not add any extra text or explanation.
    """
    
    try:
        chat_completion = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"message": ai_response}
    except Exception as e:
        return {"error": str(e)}


# --- KAIBIGAN KABAN (EXPENSE TRACKER) ENDPOINTS ---

@router.get("/kaban/categories")
async def get_kaban_categories(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Get all expense categories (default + custom) (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

    try:
        # Get default categories (user_id is NULL) and user's custom categories
        categories_res = supabase.table('expense_categories').select('*').or_(f'user_id.is.null,user_id.eq.{user_id}').order('name', desc=False).execute()
        return categories_res.data
    except Exception as e:
        print(f"Get Categories Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kaban/categories")
async def create_custom_category(
    request: CategoryCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Create a custom expense category (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

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
async def create_kaban_transaction(
    request: TransactionRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Add a new expense or income transaction (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

    try:
        # Verify category exists and user has access to it (default or user's custom)
        category_res = supabase.table('expense_categories').select('id').or_(f'user_id.is.null,user_id.eq.{user_id}').eq('id', request.category_id).execute()
        if not category_res.data or len(category_res.data) == 0:
            raise HTTPException(status_code=404, detail="Category not found or access denied.")

        tx_data = request.model_dump()
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
    """Get all transactions with optional filters (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

    try:
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
async def update_kaban_transaction(
    transaction_id: str,
    request: TransactionUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Update an existing transaction (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

    try:
        # Only update fields that are provided
        update_data = {k: v for k, v in request.model_dump().items() if v is not None}
        
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
async def delete_kaban_transaction(
    transaction_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Delete a transaction (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

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
    """Get monthly income/expense summary (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

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
    """Get spending breakdown by category (Pro only)"""
    tier = profile['tier']
    user_id = profile['id']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kaibigan Kaban is a Pro feature.")

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
