import json
import os
from fastapi import FastAPI
from pydantic import BaseModel # New import
from openai import OpenAI       # New import
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware 

# Load keys from .env file
load_dotenv()

# --- Initialize the OpenAI Client ---
# Connection to the AI.
# It automatically reads the OPENAI_API_KEY from the .env file.
client = OpenAI() 

app = FastAPI(
    title="Kaibigan API",
    description="The AI backend for KaibiganGPT.",
    version="0.1.0"
)


app = FastAPI(
    # ... your existing title/description ...
)

# --- ADD THIS BLOCK ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows ALL origins (for now, to fix dev instantly)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)
# ----------------------



# --- "Single Source of Truth" for budgets ---
BUDGET_MAP = {
    "Low": "₱100-₱250 per day",
    "Medium": "₱251-₱500 per day",
    "High": "₱501+ per day"
}

# --- "Single Source of Truth" for Gov't Assistance ---
GOV_PROGRAMS_DB = [
    {
        "id": "sss_sickness",
        "agency": "SSS",
        "name": "SSS Sickness Benefit",
        "summary": "A daily cash allowance paid for the number of days a member is unable to work due to sickness or injury.",
        "who_can_apply": "All SSS members (Employed, Self-Employed, OFW, Voluntary) who have paid at least 3 months of contributions within the 12-month period before the semester of sickness."
    },
    {
        "id": "pagibig_housing",
        "agency": "Pag-IBIG",
        "name": "Pag-IBIG Housing Loan",
        "summary": "Financing for the purchase of a residential lot, a house and lot, or for house construction or improvement.",
        "who_can_apply": "Active Pag-IBIG members with at least 24 monthly contributions. OFWs can also apply."
    },
    {
        "id": "dswd_aics",
        "agency": "DSWD",
        "name": "DSWD AICS Program",
        "summary": "Assistance in Crisis Situations (AICS) provides medical, burial, educational, and food assistance to individuals or families in crisis.",
        "who_can_apply": "Individuals/families who are poor, disadvantaged, or vulnerable and are facing a crisis, as assessed by a social worker."
    },
    {
        "id": "owwa_education",
        "agency": "OWWA",
        "name": "OWWA Educational Assistance (EDSP)",
        "summary": "An educational grant of ₱60,000 per year for a 4-5 year course for a qualified dependent of an active OFW member.",
        "who_can_apply": "Qualified dependents of active OWWA members who have passed the qualifying exam and are enrolled in a CHED-accredited university."
    }
    # Add more to this database later
]

# --- Define the User's Input ---
# This tells FastAPI: "When a user sends data to this endpoint,
# it must be a JSON object with one field called 'prompt'."
class ChatRequest(BaseModel):
    prompt: str
    tier: str = "free"

# --- Define the Meal Plan Input ---
class MealPlanRequest(BaseModel):
    # --- FREE & PRO ---
    family_size: int = 2
    budget_range: str = "Medium" # "Low", "Medium", "High"
    location: str = "Philippines"

    # --- PRO-ONLY ---
    days: int = 1  # Override this in the endpoint
    skill_level: str = "Home Cook" # "Beginner", "Home Cook"
    restrictions: list[str] = [] # e.g., ["Keto", "Vegan"]
    allergies: list[str] = [] # e.g., ["peanuts", "shellfish"]
    time_limit: int = 0 # 0 = no limit, 30 = 30 minutes
    
    # --- Keep this for the freemium logic ---
    tier: str = "free"

# --- Define the Loan Calculator Input ---
class LoanCalculatorRequest(BaseModel):
    loan_amount: float  # e.g., 3000000
    interest_rate: float # e.g., 6.25 (annual percentage)
    loan_term_years: int # e.g., 30


# --- Define the Assistance Advisor Input (PRO FEATURE) ---
class AssistanceAdvisorRequest(BaseModel):
    # User's personal context
    employment_status: str  # e.g., "Employed", "OFW", "Self-Employed", "Unemployed"
    situation_description: str # e.g., "I lost my job," "My father is sick"
    has_sss: bool = True
    has_pagibig: bool = True
    
    # Default to "pro" since this is a pro-only endpoint
    tier: str = "pro"

# --- Define the Loan Advisor Input (PRO FEATURE) ---
class LoanAdvisorRequest(BaseModel):
    # From the calculator
    loan_amount: float
    monthly_payment: float
    total_interest: float
    loan_term_years: int
    
    # User's personal context
    monthly_income: float
    
    # Default to "pro" since this is a pro-only endpoint
    tier: str = "pro"


# --- Original "Alive" Endpoint ---
@app.get("/")
def read_root():
    """
    Root endpoint. Just to check if the API is alive.
    """
    return {"status": "Kaibigan API is alive and well!"}


# --- NEW AI Chat Endpoint ---
@app.post("/chat")
async def chat_with_ai(request: ChatRequest):
    """
    A simple endpoint that takes a user's prompt
    and returns a response from the AI.
    
    This endpoint is TIER-AWARE.
    """
    try:
        # --- NEW BUSINESS LOGIC FOR TIERS ---
        model_to_use = "gpt-5-nano"  # Default model

        if request.tier == "pro":
            model_to_use = "gpt-5-mini"  # Better model
        # -------------------------------------------

        # This is the call to the AI
        chat_completion = client.chat.completions.create(
            model=model_to_use,  # Use the dynamically selected model
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful Filipino assistant."
                },
                {
                    "role": "user",
                    "content": request.prompt # This is the user's message
                }
            ]
        )
        
        # Get the AI's reply
        ai_response = chat_completion.choices[0].message.content
        return {"response": ai_response}

    except Exception as e:
        # Return an error if something goes wrong
        return {"error": str(e)}



# --- Placeholder for Meal Plan Endpoint ---
@app.post("/generate-meal-plan")
async def generate_meal_plan(request: MealPlanRequest):
    """
    Generates a Filipino meal plan based on user inputs.
    This endpoint is TIER-AWARE.
    """

    # --- 1. Set the AI Model ---
    model_to_use = "gpt-5-nano"  # Default to free
    day_count = 1                # Default to free

    if request.tier == "pro":
        model_to_use = "gpt-5-mini"
        day_count = request.days  # Pro users get their requested days!

    # --- 2. Craft the Prompts ---

    # Map the budget range to its definition
    # We default to Medium if something goes wrong.
    budget_definition = BUDGET_MAP.get(request.budget_range, "₱251-₱500 per day")


    system_prompt = f"""
    You are 'Kaibigan Kusinero', an expert Filipino meal planner.
    Your task is to create a {day_count}-day meal plan (Breakfast, Lunch, Dinner, Snacks).
    
    STRICT RULES:
    1.  Cuisine: Filipino recipes by default.
    2.  Audience: Plan is for {request.family_size} people.
    3.  Budget: Adhere *strictly* to a '{budget_definition}'.
    4.  Location: User is in '{request.location}'. Use local ingredients or substitutes.
    """
        
    # --- 3. PRO-ONLY RULES ---
    if request.tier == "pro":
        system_prompt += "\n    --- PRO USER RULES ---"
        
        if request.restrictions:
            system_prompt += f"\n    5. Dietary Restrictions: Must be {', '.join(request.restrictions)}."
        
        if request.allergies:
            system_prompt += f"\n    6. Allergies: MUST NOT contain {', '.join(request.allergies)}."
        
        system_prompt += f"\n    7. Skill Level: Recipes must be for a '{request.skill_level}' cook."
        
        if request.time_limit > 0:
            system_prompt += f"\n    8. Time Limit: All recipes must be doable in {request.time_limit} minutes or less."

    system_prompt += "\n\n    Respond ONLY with the meal plan in a clean, simple format. Start with 'Here is your {day_count}-day meal plan:' and include a shopping list."

    user_prompt = f"Please generate the {day_count}-day meal plan for me."

    # --- 4. Call the AI ---
    try:
        chat_completion = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        ai_response = chat_completion.choices[0].message.content
        return {"meal_plan": ai_response, "prompt_debug": system_prompt} # Prompt for debugging

    except Exception as e:
        return {"error": str(e)}


# --- (Math-Based) Loan Calculator Endpoint ---
@app.post("/calculate-loan")
def calculate_loan(request: LoanCalculatorRequest):
    """
    Calculates the monthly loan payment using a standard
    formula. This is a FREE endpoint (no AI cost).
    """
    try:
        # 1. Get the inputs
        principal = request.loan_amount
        annual_rate = request.interest_rate / 100.0
        loan_term_months = request.loan_term_years * 12

        # 2. Handle edge case
        if annual_rate == 0:
            if loan_term_months == 0:
                return {"monthly_payment": principal} # Pay all at once
            monthly_payment = principal / loan_term_months
        else:
            # 3. This is the magic formula
            monthly_rate = annual_rate / 12.0
            r_plus_1_to_n = (1 + monthly_rate) ** loan_term_months
            
            monthly_payment = principal * (
                (monthly_rate * r_plus_1_to_n) / (r_plus_1_to_n - 1)
            )

        total_payment = monthly_payment * loan_term_months
        total_interest = total_payment - principal

        # 4. Return the clean JSON response
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


# --- AI Loan Advisor Endpoint (PRO FEATURE) ---
@app.post("/analyze-loan")
async def analyze_loan(request: LoanAdvisorRequest):
    """
    Analyzes a loan's affordability and provides advice.
    This is a PRO-TIER AI endpoint.
    """

    # --- 1. Set AI Model ---
    # Pro feature, so use the better model.
    model_to_use = "gpt-5-mini" 

    if request.tier != "pro":
        # A quick "guard clause"
        return {"error": "This feature is for Pro members only."}

    # --- 2. Calculate Key Financial Ratios ---
    # Do simple math *before* calling the AI to save tokens
    # and give the AI better data.
    
    # Debt-to-Income Ratio (DTI) for this loan only
    dti_ratio = (request.monthly_payment / request.monthly_income) * 100
    
    # --- 3. Build the "Secret Sauce" Prompt ---
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
    1.  **Affordability:** The user's Debt-to-Income (DTI) ratio for this loan is {dti_ratio:.2f}%.
        - If DTI < 10%: Call it 'Very Affordable'.
        - If 10% <= DTI < 20%: Call it 'Affordable'.
        - If 20% <= DTI < 30%: Call it 'Manageable, but tight'.
        - If DTI >= 30%: Call it 'High Risk / Not Recommended'.
    2.  **The "So What?"**: Briefly explain *what this means* for their budget.
    3.  **Interest Analysis**: Comment on the ₱{request.total_interest:,.2f} in total interest. Is it a lot compared to the principal?
    4.  **Actionable Advice**: Give 2-3 bullet points of "Next Steps" or "Things to Consider" (e.g., "Check Pag-IBIG housing loans," "Try to add 10% to your down payment," "Make sure you have an emergency fund.").
    
    Respond in a clear, friendly, and helpful tone. Start with a greeting.
    """
    
    user_prompt = "Here is my loan and my income. Can you please analyze it for me?"

    # --- 4. Call the AI ---
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
    


# --- 11. Gov't Assistance Search Endpoint (FREE) ---
@app.get("/search-assistance")
def search_assistance(keyword: str = ""):
    """
    Searches the "Tulong" database for government programs.
    This is a FREE endpoint (no AI cost).
    
    If no keyword is given, it returns all programs.
    """
    
    # If no keyword, return the whole database
    if not keyword:
        return {"programs": GOV_PROGRAMS_DB}
    
    # If there is a keyword, search for it (case-insensitive)
    search_term = keyword.lower()
    results = []
    
    for program in GOV_PROGRAMS_DB:
        if (search_term in program["name"].lower() or
            search_term in program["agency"].lower() or
            search_term in program["summary"].lower()):
            
            results.append(program)
            
    return {"programs": results}



# --- 13. AI Assistance Advisor Endpoint (PRO FEATURE) ---
@app.post("/analyze-assistance")
async def analyze_assistance(request: AssistanceAdvisorRequest):
    """
    Analyzes a user's situation against the known
    database of government programs.
    This is a PRO-TIER AI endpoint.
    """

    # --- 1. Set AI Model ---
    model_to_use = "gpt-5-mini" # Pro feature = better model

    if request.tier != "pro":
        return {"error": "This feature is for Pro members only."}

    # --- 2. Prepare the "Context" ---
    # Convert Python database into a JSON string
    # so the AI can read it as clean "context".
    programs_context = json.dumps(GOV_PROGRAMS_DB, indent=2)

    # --- 3. Build the "Secret Sauce" Prompt ---
    system_prompt = f"""
    You are 'Kaibigan Tulong', an expert advisor on
    Philippine government assistance programs.
    
    You have access to the following database of programs:
    --- DATABASE START ---
    {programs_context}
    --- DATABASE END ---

    A user needs help. Here is their situation:
    - Employment Status: {request.employment_status}
    - Has SSS: {request.has_sss}
    - Has Pag-IBIG: {request.has_pagibig}
    - Their Situation: "{request.situation_description}"

    YOUR TASK:
    1.  Analyze the user's situation.
    2.  Cross-reference it *ONLY* with the programs in the database provided.
    3.  Create a "Personalized Assistance Report" for the user.
    4.  For each program in the database, state EITHER:
        - "You are likely eligible for..." (and explain *why*).
        - "You are likely *not* eligible for..." (and explain *why not*).
        - "You *might* be eligible for..." (and explain *what to check*).
    5.  Be empathetic, clear, and direct. Start with a greeting.
    """
    
    user_prompt = "Based on my situation, what help can I get?"

    # --- 4. Call the AI ---
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
    

# This is the line that runs your app
# (Keep it commented out, you run this in the terminal)
# @app.post("/generate-meal-plan")
# async def generate_meal_plan():
#    pass