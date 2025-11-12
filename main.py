import os
import json
import hmac
import hashlib
import base64
from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from typing import Annotated, List, Optional
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware 
import datetime

# --- 1. SETUP ---
load_dotenv()
client = OpenAI() 

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
if not supabase_url or not supabase_key:
     raise Exception("Supabase URL and Service Key must be set in environment variables.")
supabase: Client = create_client(supabase_url, supabase_key)

app = FastAPI(
    title="Kaibigan API",
    description="The AI backend for KaibiganGPT.",
    version="0.1.0"
)

# --- 2. MIDDLEWARE (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "https://kaibigan-web.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 3. "SINGLE SOURCE OF TRUTH" DATA ---
BUDGET_MAP = {
    "Low": "₱100-₱250 per day",
    "Medium": "₱251-₱500 per day",
    "High": "₱501+ per day"
}
try:
    with open('gov_programs.json', 'r', encoding='utf-8') as f:
        GOV_PROGRAMS_DB = json.load(f)
except FileNotFoundError:
    GOV_PROGRAMS_DB = []
    print("WARNING: gov_programs.json not found.")

# --- 4. REQUEST MODELS (PYDANTIC) ---
class ChatRequest(BaseModel):
    prompt: str

class MealPlanRequest(BaseModel):
    family_size: int = 2
    budget_range: str = "Medium"
    location: str = "Philippines"
    days: int = 1
    skill_level: str = "Home Cook"
    restrictions: List[str] = []
    allergies: List[str] = []
    time_limit: int = 0

class LoanCalculatorRequest(BaseModel):
    loan_amount: float
    interest_rate: float
    loan_term_years: int

class LoanAdvisorRequest(BaseModel):
    loan_amount: float
    monthly_payment: float
    total_interest: float
    loan_term_years: int
    monthly_income: float

class AssistanceAdvisorRequest(BaseModel):
    employment_status: str
    situation_description: str
    has_sss: bool = True
    has_pagibig: bool = True

class RecipeNotesRequest(BaseModel):
    recipe_name: str
    notes: str

class IponGoalCreate(BaseModel):
    name: str
    target_amount: float
    target_date: Optional[datetime.date] = None

class TransactionCreate(BaseModel):
    goal_id: str
    amount: float
    notes: Optional[str] = None

# --- NEW: UTANG TRACKER MODELS ---
class UtangCreate(BaseModel):
    debtor_name: str
    amount: float
    due_date: Optional[datetime.date] = None
    notes: Optional[str] = None

class UtangUpdate(BaseModel):
    status: str # "paid" or "unpaid"

class AICollectorRequest(BaseModel):
    debtor_name: str
    amount: float
    tone: str # "Gentle", "Firm", "Final"
# ---------------------------------


# --- 5. THE "BOUNCER" (Security Dependency) ---
async def get_user_profile(authorization: Annotated[str | None, Header()] = None):
    # ... (existing bouncer code, no changes) ...
# ... (existing get_user_profile function) ...
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    
    token_type, _, token = authorization.partition(' ')
    if token_type.lower() != 'bearer' or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    try:
        user_res = supabase.auth.get_user(token)
        user = user_res.user
        if not user:
            raise Exception("Invalid token")
        
        profile_res = supabase.table('profiles').select('*').eq('id', user.id).single().execute()
        profile = profile_res.data
        if not profile:
            raise Exception("Profile not found")
        
        return profile
    
    except Exception as e:
        print(f"Auth Error: {e}") 
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Authentication error")


# --- 6. PUBLIC/FREE ENDPOINTS ---
@app.get("/")
def read_root():
# ... (existing root endpoint) ...
    return {"status": "Kaibigan API is alive and well!"}

@app.post("/calculate-loan")
def calculate_loan(request: LoanCalculatorRequest):
# ... (existing loan calculator endpoint) ...
    try:
        principal = request.loan_amount
        annual_rate = request.interest_rate / 100.0
        loan_term_months = request.loan_term_years * 12

        if loan_term_months == 0:
            return {"monthly_payment": principal, "total_payment": principal, "total_interest": 0, **request.model_dump()}

        if annual_rate == 0:
            monthly_payment = principal / loan_term_months
        else:
            monthly_rate = annual_rate / 12.0
            r_plus_1_to_n = (1 + monthly_rate) ** loan_term_months
            monthly_payment = principal * ((monthly_rate * r_plus_1_to_n) / (r_plus_1_to_n - 1))
        
        total_payment = monthly_payment * loan_term_months
        total_interest = total_payment - principal

        return {
            "monthly_payment": round(monthly_payment, 2),
            "total_payment": round(total_payment, 2),
            "total_interest": round(total_interest, 2),
            "loan_amount": principal,
            "interest_rate": request.interest_rate,
            "loan_term_years": request.loan_term_years
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/search-assistance")
def search_assistance(keyword: str = ""):
# ... (existing assistance search endpoint) ...
    if not keyword:
        return {"programs": GOV_PROGRAMS_DB}
    search_term = keyword.lower()
    results = [p for p in GOV_PROGRAMS_DB if 
               search_term in p["name"].lower() or 
               search_term in p["agency"].lower() or 
               search_term in p["summary"].lower()]
    return {"programs": results}


# --- 7. SECURE ENDPOINTS (Requires Auth) ---
@app.post("/chat")
async def chat_with_ai(
# ... (existing chat endpoint) ...
    request: ChatRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier'] 
    model_to_use = "gpt-5-mini" if tier == "pro" else "gpt-5-nano"

    try:
        chat_completion = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": "You are a helpful Filipino assistant."},
                {"role": "user", "content": request.prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"response": ai_response}
    except Exception as e:
        return {"error": str(e)}

@app.post("/generate-meal-plan")
async def generate_meal_plan(
# ... (existing meal plan endpoint) ...
    request: MealPlanRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier'] 
    model_to_use = "gpt-5-nano"
    day_count = 1

    if tier == 'pro':
        model_to_use = "gpt-5-mini"
        day_count = request.days
    else:
        request.restrictions = []
        request.allergies = []
        request.skill_level = "Home Cook"
        request.time_limit = 0
        day_count = 1

    budget_definition = BUDGET_MAP.get(request.budget_range, "₱251-₱500 per day")
    
    system_prompt = f"""
    You are 'Kaibigan Kusinero', an expert Filipino meal planner.
    Your task is to create a {day_count}-day meal plan (Breakfast, Lunch, Dinner, Snacks).
    STRICT RULES:
    1. Cuisine: Filipino recipes by default.
    2. Audience: Plan is for {request.family_size} people.
    3. Budget: Adhere *strictly* to a '{budget_definition}'.
    4. Location: User is in '{request.location}'. Use local ingredients or substitutes.
    """
    
    if tier == "pro":
        system_prompt += "\n    --- PRO USER RULES ---"
        if request.restrictions:
            system_prompt += f"\n    5. Dietary Restrictions: Must be {', '.join(request.restrictions)}."
        if request.allergies:
            system_prompt += f"\n    6. Allergies: MUST NOT contain {', '.join(request.allergies)}."
        system_prompt += f"\n    7. Skill Level: Recipes must be for a '{request.skill_level}' cook."
        if request.time_limit > 0:
            system_prompt += f"\n    8. Time Limit: All recipes must be doable in {request.time_limit} minutes or less."

    system_prompt += "\n\n    Respond ONLY with the meal plan in a clean, simple format."
    user_prompt = f"Please generate the {day_count}-day meal plan for me."

    try:
        chat_completion = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"meal_plan": ai_response}
    except Exception as e:
        return {"error": str(e)}

@app.post("/analyze-loan")
async def analyze_loan(
# ... (existing loan analysis endpoint) ...
    request: LoanAdvisorRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature is for Pro members only.")
    
    model_to_use = "gpt-5-mini"

    try:
        dti_ratio = (request.monthly_payment / request.monthly_income) * 100
    except ZeroDivisionError:
        dti_ratio = 0
    
    system_prompt = f"""
    You are 'Kaibigan Pera', an expert Filipino financial advisor.
    You are friendly, empathetic, but give clear, practical advice.
    Your task is to analyze a loan for a user.
    USER'S FINANCIALS:
    - Monthly Income: ₱{request.monthly_income:,.2f}
    LOAN DETAILS:
    - Loan Amount: ₱{request.loan_amount:,.2f}
    - Monthly Payment: ₱{request.monthly_payment:,.2f}
    - Loan Term: {request.loan_term_years} years
    - Total Interest Paid: ₱{request.total_interest:,.2f}

    YOUR ANALYSIS (MUST INCLUDE):
    1. **Affordability:** The user's Debt-to-Income (DTI) ratio for this loan is {dti_ratio:.2f}%.
       - If DTI < 10%: Call it 'Very Affordable'.
       - If 10% <= DTI < 20%: Call it 'Affordable'.
       - If 20% <= DTI < 30%: Call it 'Manageable, but tight'.
       - If DTI >= 30%: Call it 'High Risk / Not Recommended'.
    2. **The "So What?"**: Briefly explain *what this means* for their budget.
    3. **Interest Analysis**: Comment on the ₱{request.total_interest:,.2f} in total interest.
    4. **Actionable Advice**: Give 2-3 bullet points of "Next Steps".
    
    Respond in a clear, friendly, and helpful tone. Start with a greeting.
    """
    
    user_prompt = "Here is my loan and my income. Can you please analyze it for me?"

    try:
        chat_completion = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"analysis": ai_response, "prompt_debug": system_prompt}
    except Exception as e:
        return {"error": str(e)}

@app.post("/analyze-assistance")
async def analyze_assistance(
# ... (existing assistance analysis endpoint) ...
    request: AssistanceAdvisorRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature is for Pro members only.")

    model_to_use = "gpt-5-mini"
    programs_context = json.dumps(GOV_PROGRAMS_DB, indent=2)

    system_prompt = f"""
    You are 'Kaibigan Tulong', an expert advisor on Philippine government programs.
    You have access to the following database:
    {programs_context}
    
    A user needs help. Their situation:
    - Employment: {request.employment_status}
    - Has SSS: {request.has_sss}
    - Has Pag-IBIG: {request.has_pagibig}
    - Their Situation: "{request.situation_description}"

    YOUR TASK:
    1. Analyze their situation.
    2. Cross-reference it *ONLY* with the programs in the database.
    3. Create a "Personalized Assistance Report".
    4. For each program, state EITHER:
       - "You are likely eligible for..." (and *why*).
       - "You are likely *not* eligible for..." (and *why not*).
       - "You *might* be eligible for..." (and *what to check*).
    5. Be empathetic, clear, and direct. Start with a greeting.
    """
    
    user_prompt = "Based on my situation, what help can I get?"

    try:
        chat_completion = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"analysis": ai_response, "prompt_debug": system_prompt}
    except Exception as e:
        return {"error": str(e)}

@app.post("/recipes/create-from-notes")
async def create_recipe_from_notes(
# ... (existing recipe AI endpoint) ...
    request: RecipeNotesRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier']
    user_id = profile['id']

    if tier != 'pro':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="The 'Luto ni Nanay' Recipe Bank is a Pro feature. Please upgrade to save your recipes."
        )

    system_prompt = f"""
    You are an expert Filipino recipe formatter. A user is providing their
    messy, informal notes for a recipe. Your ONLY job is to convert
    this into a clean, structured JSON object.

    The JSON object MUST have these exact fields:
    - "ingredients": An array of strings.
    - "instructions": A single string. You can use newline characters (\\n) for steps.
    - "servings": An integer.
    - "prep_time_minutes": An integer.

    USER'S NOTES for "{request.recipe_name}":
    ---
    {request.notes}
    ---

    Now, return ONLY the valid JSON object. Do not add any conversational text.
    """

    try:
        print(f"Calling GPT-5-Mini for user {user_id}...")
        chat_completion = client.chat.completions.create(
            model="gpt-5-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        
        ai_response_json = chat_completion.choices[0].message.content
        
        recipe_data = json.loads(ai_response_json)
        recipe_data['user_id'] = user_id
        recipe_data['name'] = request.recipe_name
        recipe_data['original_notes'] = request.notes

        print(f"Saving recipe '{request.recipe_name}' to Supabase...")
        insert_res = supabase.table('recipes').insert(recipe_data).execute()

        if not insert_res.data:
             raise HTTPException(status_code=500, detail="Failed to save recipe to database.")

        return insert_res.data[0] 

    except Exception as e:
        print(f"AI Chef Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI formatting error: {e}")

@app.post("/ipon/goals")
async def create_ipon_goal(
# ... (existing ipon goal endpoint) ...
    request: IponGoalCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
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

@app.get("/ipon/goals")
async def get_ipon_goals(
# ... (existing get ipon goals endpoint) ...
    profile: Annotated[dict, Depends(get_user_profile)]
):
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

@app.post("/ipon/transactions")
async def add_ipon_transaction(
# ... (existing add ipon transaction endpoint) ...
    request: TransactionCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
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

@app.get("/ipon/goals/{goal_id}/transactions")
async def get_goal_transactions(
# ... (existing get transactions endpoint) ...
    goal_id: str,
    profile: Annotated[dict, Depends(get_user_profile)]
):
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


# --- 8. NEW "UTANG TRACKER" ENDPOINTS (PRO) ---

@app.post("/utang/debts")
async def create_utang_record(
    request: UtangCreate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    (PRO FEATURE) Creates a new utang (debt owed to user) record.
    """
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

@app.get("/utang/debts")
async def get_utang_records(
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    (PRO FEATURE) Gets all 'unpaid' utang records for the user.
    """
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

@app.put("/utang/debts/{debt_id}")
async def update_utang_status(
    debt_id: str,
    request: UtangUpdate,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    (PRO FEATURE) Marks an utang as 'paid' or 'unpaid'.
    """
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

@app.post("/utang/generate-message")
async def generate_utang_message(
    request: AICollectorRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """
    (PRO FEATURE) Uses AI to generate a "paningil" message.
    """
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Collector is a Pro feature.")

    # Define the tone of the message
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
            model="gpt-5-mini", # Use pro model
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"message": ai_response}
    except Exception as e:
        return {"error": str(e)}


# --- 9. WEBHOOK ENDPOINT (THE "CASH REGISTER") ---
@app.post("/webhook-lemonsqueezy")
async def webhook_lemonsqueezy(request: Request):
# ... (existing webhook endpoint) ...
    try:
        secret = os.environ.get("LEMONSQUEEZY_SIGNING_SECRET")
        if not secret:
            print("WEBHOOK ERROR: LEMONSQUEEZY_SIGNING_SECRET is not set.")
            raise HTTPException(status_code=500, detail="Webhook not configured")
            
        signature = request.headers.get("X-Signature", "")
        payload = await request.body()
        
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        computed_signature = base64.b64encode(digest).decode()

        if not hmac.compare_digest(computed_signature, signature):
            print("WEBHOOK ERROR: Invalid signature")
            raise HTTPException(status_code=400, detail="Invalid signature")

        data = json.loads(payload.decode())
        event_name = data.get("meta", {}).get("event_name")
        
        user_email = data.get("data", {}).get("attributes", {}).get("user_email")
        
        if not user_email:
            print(f"WEBHOOK: No user email in event '{event_name}'")
            return {"status": "ok", "message": "No email, but webhook received."}

        status_val = data.get("data", {}).get("attributes", {}).get("status")
        new_tier = "free"
        
        if event_name in ["subscription_created", "subscription_updated"] and status_val == "active":
            new_tier = "pro"
        
        print(f"WEBHOOK: Attempting to set {user_email} to '{new_tier}'...")
        update_res = supabase.table("profiles").update({"tier": new_tier}).eq("email", user_email).execute()
        
        if not update_res.data:
            print(f"WEBHOOK ERROR: No profile found for {user_email}")
            return {"status": "error", "message": "Profile not found"}

        print(f"WEBHOOK SUCCESS: User {user_email} is now '{new_tier}'")
        return {"status": "success"}

    except Exception as e:
        print(f"WEBHOOK EXCEPTION: {e}")
        return {"error": str(e)}