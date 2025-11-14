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
