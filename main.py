import os
import json
import hmac
import hashlib
import base64
from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import Annotated, List, Optional
from fastapi.middleware.cors import CORSMiddleware 
import datetime
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import shared dependencies and routers
from dependencies import get_user_profile, supabase, limiter
from routers import pera, sahod

# --- 1. SETUP ---
load_dotenv()
client = AsyncOpenAI() 

# Version info
API_VERSION = "1.0.0"
BUILD_DATE = "2025-12-17"

app = FastAPI(
    title="KabanKo API",
    description="The AI backend for KabanKo - Ikaw ang Boss, Si Kaban ang Manager.",
    version=API_VERSION
)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://kaibigan-web.vercel.app",
    "https://kabanko.app",
    "https://kaibigan-test-five.vercel.app",
]

# --- 2. MIDDLEWARE (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiter to app state
app.state.limiter = limiter

# Custom rate limit error handler with CORS headers
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    response = _rate_limit_exceeded_handler(request, exc)
    # Add CORS headers to rate limit response
    origin = request.headers.get("origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# --- 2.5. INCLUDE ROUTERS ---
app.include_router(pera.router)
app.include_router(sahod.router)

# --- 3. "SINGLE SOURCE OF TRUTH" DATA ---
# Budget ranges per head (internal calculations)
BUDGET_PER_HEAD = {
    "Ultra Budget": {"min": 40, "max": 80, "meals": 3},  # No snacks
    "Budget-Friendly": {"min": 81, "max": 150, "meals": 4},  # Includes snacks
    "Comfortable": {"min": 151, "max": 300, "meals": 4}  # Includes snacks
}

# Static cooking tips for ALL users (always included)
STATIC_COOKING_TIPS = [
    "Prep ingredients the night before to save time.",
    "Buy rice and cooking oil in bulk to reduce costs.",
    "Use leftover rice for breakfast to minimize waste."
]

def get_budget_definition(budget_range: str, family_size: int):
    """
    Calculate total daily budget based on per-head rates and family size.
    Auto-upgrades Ultra Budget to Budget-Friendly for families of 7+.
    """
    # Validate budget_range and provide default if invalid
    valid_budgets = ["Ultra Budget", "Budget-Friendly", "Comfortable"]
    if budget_range not in valid_budgets:
        budget_range = "Budget-Friendly"  # Default to Budget-Friendly if invalid
    
    # Auto-upgrade logic for large families
    original_budget = budget_range
    if family_size >= 7 and budget_range == "Ultra Budget":
        budget_range = "Budget-Friendly"
    
    per_head = BUDGET_PER_HEAD[budget_range]
    total_min = per_head["min"] * family_size
    total_max = per_head["max"] * family_size
    
    # Format with comma for thousands
    if total_max >= 1000:
        total_range = f"₱{total_min:,}-₱{total_max:,} per day"
    else:
        total_range = f"₱{total_min}-₱{total_max} per day"
    
    per_head_range = f"₱{per_head['min']}-₱{per_head['max']} per person"
    
    return {
        "budget_range": budget_range,  # May be upgraded
        "original_budget": original_budget,
        "total_range": total_range,
        "per_head_range": per_head_range,
        "total_min": total_min,
        "total_max": total_max,
        "per_head_min": per_head["min"],
        "per_head_max": per_head["max"],
        "includes_snacks": per_head["meals"] == 4,
        "was_upgraded": budget_range != original_budget
    }

try:
    with open('gov_programs.json', 'r', encoding='utf-8') as f:
        GOV_PROGRAMS_DB = json.load(f)
except FileNotFoundError:
    GOV_PROGRAMS_DB = []
    print("WARNING: gov_programs.json not found.")

# --- 4. REQUEST MODELS (PYDANTIC) ---
# ... (All your existing models: ChatRequest, MealPlanRequest, etc. No changes.)
class ChatRequest(BaseModel):
    prompt: str

class MealPlanRequest(BaseModel):
    family_size: int = 2
    budget_range: str = "Budget-Friendly"
    location: str = "Philippines"
    days: int = 1
    skill_level: str = "Home Cook"
    restrictions: List[str] = []
    allergies: List[str] = []
    time_limit: int = 0
    include_grocery_list: bool = True  # Toggle for grocery list
    include_nutrition: bool = False     # Toggle for nutritional info (PRO feature)

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


# --- 5. PUBLIC/FREE ENDPOINTS ---
@app.get("/")
def read_root():
    return {"status": "KabanKo API is alive and well!"}

@app.get("/health")
def health_check():
    """
    Health check endpoint for monitoring and load balancing.
    Used by Render for automatic health checks and restart detection.
    """
    return {
        "status": "healthy",
        "service": "KabanKo API",
        "version": API_VERSION,
        "build_date": BUILD_DATE,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

@app.post("/calculate-loan")
@limiter.limit("60/minute")
def calculate_loan(request: Request, loan_request: LoanCalculatorRequest):
    try:
        principal = loan_request.loan_amount
        annual_rate = loan_request.interest_rate / 100.0
        loan_term_months = loan_request.loan_term_years * 12

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
            "interest_rate": loan_request.interest_rate,
            "loan_term_years": loan_request.loan_term_years
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/search-assistance")
@limiter.limit("60/minute")
def search_assistance(request: Request, keyword: str = "", category: str = ""):
    """
    Search government assistance programs with optional keyword and category filters.
    Both filters work as AND condition when provided.
    """
    results = GOV_PROGRAMS_DB
    
    # Filter by category first (if provided and not "All")
    if category and category.lower() != "all":
        results = [p for p in results if p.get("category", "").lower() == category.lower()]
    
    # Then filter by keyword (if provided)
    if keyword:
        search_term = keyword.lower()
        results = [p for p in results if 
                   search_term in p["name"].lower() or 
                   search_term in p["agency"].lower() or 
                   search_term in p["summary"].lower() or
                   search_term in p.get("category", "").lower() or
                   search_term in p.get("who_can_apply", "").lower()]
    
    return {
        "programs": results,
        "total_count": len(GOV_PROGRAMS_DB),
        "filtered_count": len(results),
        "filters": {
            "keyword": keyword,
            "category": category
        }
    }


# --- 6. PRIVACY CONSENT ENDPOINTS ---
@app.post("/user/consent")
@limiter.limit("60/minute")
async def record_privacy_consent(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Record user's privacy policy consent with timestamp"""
    user_id = profile['id']
    
    try:
        # Update user's profile with consent
        consent_data = {
            'privacy_consent': True,
            'privacy_consent_date': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        supabase.table('profiles').update(consent_data).eq('id', user_id).execute()
        
        return {
            "success": True,
            "message": "Privacy consent recorded",
            "consent_date": consent_data['privacy_consent_date']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record consent: {str(e)}")


@app.get("/user/consent-status")
@limiter.limit("60/minute")
async def get_consent_status(
    request: Request,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    """Check if user has consented to privacy policy"""
    return {
        "has_consented": profile.get('privacy_consent', False),
        "consent_date": profile.get('privacy_consent_date')
    }


# --- 7. SECURE ENDPOINTS (Requires Auth) ---
# ... (All your existing secure endpoints: /chat, /generate-meal-plan, /analyze-loan, etc. No changes.)
@app.post("/chat")
@limiter.limit("5/minute")
async def chat_with_ai(
    request: Request,
    chat_request: ChatRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier'] 
    model_to_use = "gpt-5-mini" if tier == "pro" else "gpt-5-nano"

    try:
        chat_completion = await client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": "You are a helpful Filipino assistant."},
                {"role": "user", "content": chat_request.prompt}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return {"response": ai_response}
    except Exception as e:
        return {"error": str(e)}

@app.post("/generate-meal-plan")
@limiter.limit("5/minute")
async def generate_meal_plan(
    request: Request,
    meal_plan_request: MealPlanRequest,
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier'] 
    model_to_use = "gpt-5-nano"
    day_count = 1

    if tier == 'pro':
        model_to_use = "gpt-5-mini"
        day_count = meal_plan_request.days
    else:
        # Free tier limitations
        meal_plan_request.restrictions = []
        meal_plan_request.allergies = []
        meal_plan_request.skill_level = "Home Cook"
        meal_plan_request.time_limit = 0
        meal_plan_request.include_nutrition = False  # Nutrition is PRO only
        day_count = 1

    # Get budget definition with auto-upgrade logic
    budget_info = get_budget_definition(meal_plan_request.budget_range, meal_plan_request.family_size)
    budget_definition = budget_info["total_range"]
    includes_snacks = budget_info["includes_snacks"]
    
    # Build the JSON schema for consistent output
    meals_structure = {
        "breakfast": {"name": "Recipe name", "estimated_cost": 100},
        "lunch": {"name": "Recipe name", "estimated_cost": 150},
        "dinner": {"name": "Recipe name", "estimated_cost": 150}
    }
    
    # Add snacks only for Budget-Friendly and Comfortable
    if includes_snacks:
        meals_structure["snacks"] = {"name": "Snack name", "estimated_cost": 50}
    
    json_structure = {
        "days": [
            {
                "day_number": 1,
                "meals": meals_structure,
                "daily_total": 450 if includes_snacks else 400
            }
        ],
        "total_cost_estimate": 450 if includes_snacks else 400
    }
    
    # Add optional fields based on toggles
    if meal_plan_request.include_grocery_list:
        json_structure["grocery_list"] = [
            {"item": "ingredient name", "quantity": "amount"}
        ]
        json_structure["grocery_total_estimate"] = 450
    
    # Cooking tips structure (Pro users will get 2 AI-generated tips added to the 3 static ones)
    if tier == "pro":
        json_structure["ai_cooking_tips"] = [
            "AI-generated tip 1",
            "AI-generated tip 2"
        ]
    
    # OFW Ingredient Substitutions (when location is "Abroad")
    if meal_plan_request.location == "Abroad":
        json_structure["ofw_substitutions"] = [
            {"filipino_ingredient": "Patis (Fish Sauce)", "substitute": "Thai fish sauce or Vietnamese nuoc mam", "notes": "Available in most Asian groceries"},
            {"filipino_ingredient": "Calamansi", "substitute": "1:1 mix of lime and lemon juice", "notes": "Closest flavor match"}
        ]
    
    if meal_plan_request.include_nutrition and tier == "pro":
        # Add nutrition_summary to ALL days, not just first one
        for i in range(day_count):
            if i < len(json_structure["days"]):
                json_structure["days"][i]["nutrition_summary"] = {
                    "calories": 2000,
                    "protein_g": 80,
                    "carbs_g": 250,
                    "fat_g": 65
                }
            else:
                # For multi-day plans, add more day examples
                json_structure["days"].append({
                    "day_number": i + 1,
                    "meals": {
                        "breakfast": {"name": "Recipe name", "estimated_cost": 100},
                        "lunch": {"name": "Recipe name", "estimated_cost": 150},
                        "dinner": {"name": "Recipe name", "estimated_cost": 150},
                        "snacks": {"name": "Snack name", "estimated_cost": 50}
                    },
                    "daily_total": 450,
                    "nutrition_summary": {
                        "calories": 2000,
                        "protein_g": 80,
                        "carbs_g": 250,
                        "fat_g": 65
                    }
                })
    
    # Determine meal structure based on budget
    meal_structure = "breakfast, lunch, and dinner ONLY (NO snacks)" if not includes_snacks else "breakfast, lunch, dinner, and snacks"
    
    system_prompt = f"""
    You are 'Kaibigan Kusinero', an expert Filipino meal planner.
    Your task is to create a {day_count}-day meal plan in JSON format.
    
    STRICT RULES:
    1. Cuisine: Filipino recipes by default.
    2. Audience: Plan is for {meal_plan_request.family_size} people.
    3. Budget: Adhere *strictly* to a '{budget_definition}' (₱{budget_info['per_head_min']}-₱{budget_info['per_head_max']} per person).
    4. Location: User is in '{meal_plan_request.location}'. Use local ingredients or substitutes.
    5. Meals: Include {meal_structure}.
    6. ALWAYS include estimated_cost for EVERY meal in Philippine Pesos (₱).
    7. Calculate daily_total and total_cost_estimate accurately.
    """
    
    # Add budget tier context
    if budget_info["budget_range"] == "Ultra Budget":
        system_prompt += """
    
    ⚠️ ULTRA BUDGET MODE:
    - Focus on affordable Filipino staples: rice, eggs, dried fish, monggo, vegetables
    - Maximize filling meals with minimal cost
    - Use budget-stretching techniques (one ulam shared, rice as filler)
    - NO SNACKS - 3 main meals only
    """
    
    if budget_info["was_upgraded"]:
        system_prompt += f"""
    
    📢 NOTE: Budget was auto-upgraded from {budget_info['original_budget']} to {budget_info['budget_range']} 
    for a family of {meal_plan_request.family_size} to ensure adequate nutrition.
    """
    
    if tier == "pro":
        system_prompt += "\n    --- PRO USER RULES ---"
        if meal_plan_request.restrictions:
            system_prompt += f"\n    7. Dietary Restrictions: Must be {', '.join(meal_plan_request.restrictions)}."
        if meal_plan_request.allergies:
            system_prompt += f"\n    8. Allergies: MUST NOT contain {', '.join(meal_plan_request.allergies)}."
        system_prompt += f"\n    9. Skill Level: Recipes must be for a '{meal_plan_request.skill_level}' cook."
        if meal_plan_request.time_limit > 0:
            system_prompt += f"\n    10. Time Limit: All recipes must be doable in {meal_plan_request.time_limit} minutes or less."
    
    # Add OFW-specific prompt when user is abroad
    if meal_plan_request.location == "Abroad":
        system_prompt += """
    
    🌏 OFW INGREDIENT SUBSTITUTIONS (USER IS ABROAD) 🌏
    The user is an OFW (Overseas Filipino Worker) and may not have access to authentic Filipino ingredients.
    
    YOU MUST include an "ofw_substitutions" array in your JSON response with 5-8 ingredient substitutions.
    Each substitution must have:
    - "filipino_ingredient": The original Filipino ingredient name
    - "substitute": What they can use instead (available in most countries)
    - "notes": Brief tips on finding it or adjusting the recipe
    
    Common substitutions to consider:
    - Patis (fish sauce) → Thai fish sauce, Vietnamese nuoc mam
    - Calamansi → Equal parts lime and lemon juice
    - Banana leaves → Aluminum foil or parchment paper (for wrapping)
    - Achuete (annatto) → Paprika + turmeric mix
    - Bagoong → Shrimp paste (Malaysian/Thai) or anchovy paste
    - Kamias → Green mango or tamarind
    - Kangkong → Spinach or water spinach if available
    - Tamarind concentrate → Tamarind paste from Asian stores
    - Gata (coconut milk) → Canned coconut milk (widely available)
    - Siling labuyo → Thai bird's eye chili
    - Kesong puti → Feta cheese or paneer
    - Longganisa → Chorizo or Italian sausage with added garlic
    
    Focus on ingredients that ARE used in the recipes you're suggesting.
    """
    
    system_prompt += f"""

    OUTPUT FORMAT (JSON):
    {json.dumps(json_structure, indent=2)}
    
    IMPORTANT:
    - Create {day_count} day(s) of meal plans
    - Each meal MUST have an estimated_cost
    - grocery_list is {"REQUIRED" if meal_plan_request.include_grocery_list else "NOT required"}
    - If grocery_list is included: Do NOT add individual prices per item. Instead, provide grocery_total_estimate.
    - grocery_total_estimate should be the total estimated cost for ALL groceries needed.
    - nutrition_summary is {"REQUIRED for EVERY day (Pro feature)" if meal_plan_request.include_nutrition and tier == "pro" else "NOT required"}"""
    
    if tier == "pro":
        system_prompt += """
    - ai_cooking_tips: Provide exactly 2 unique, advanced cooking tips specific to THIS meal plan (ingredient substitutions, cooking techniques, Filipino culinary hacks)"""
    
    # Add OFW substitutions requirement
    if meal_plan_request.location == "Abroad":
        system_prompt += """
    - ofw_substitutions: REQUIRED - Include 5-8 ingredient substitutions for Filipino ingredients used in this meal plan"""
    
    system_prompt += """
    - Return ONLY valid JSON, no additional text
    """
    
    # Add extra emphasis for nutrition if requested
    if meal_plan_request.include_nutrition and tier == "pro":
        system_prompt += f"""
    
    🔴 CRITICAL: NUTRITION DATA MANDATORY 🔴
    Every single day in your response MUST include a nutrition_summary object with these exact fields:
    - calories: integer (total daily calories)
    - protein_g: integer (total daily protein in grams)
    - carbs_g: integer (total daily carbohydrates in grams)
    - fat_g: integer (total daily fat in grams)
    
    Base these calculations on typical Filipino ingredient portions for {meal_plan_request.family_size} people.
    """
    
    # Add AI cooking tips requirement only for Pro users
    if tier == "pro":
        system_prompt += """
    
    💡 AI COOKING TIPS REQUIREMENT (PRO FEATURE) 💡
    Provide exactly 2 advanced, personalized cooking tips in the ai_cooking_tips array.
    These should be:
    - Specific to the recipes in THIS meal plan
    - Advanced techniques (not basic tips)
    - Filipino cooking hacks or regional variations
    - Ingredient substitutions for cost/availability
    - Pro-level time management strategies
    """

    try:
        chat_completion = await client.chat.completions.create(
            model=model_to_use,
            response_format={"type": "json_object"},  # Force JSON output
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        ai_response_json = chat_completion.choices[0].message.content
        meal_plan_data = json.loads(ai_response_json)
        
        # Add cooking tips to response
        cooking_tips = STATIC_COOKING_TIPS.copy()  # Always include 3 static tips
        
        if tier == "pro" and "ai_cooking_tips" in meal_plan_data:
            # Pro users get 3 static + 2 AI tips = 5 total
            cooking_tips.extend(meal_plan_data["ai_cooking_tips"])
            # Remove ai_cooking_tips from meal_plan_data (merge into cooking_tips)
            del meal_plan_data["ai_cooking_tips"]
        
        meal_plan_data["cooking_tips"] = cooking_tips
        
        # Return structured response with share data
        response_data = {
            "meal_plan": meal_plan_data,
            "share_data": {
                "budget": budget_definition,
                "budget_per_head": budget_info["per_head_range"],
                "total_daily_budget": budget_definition,
                "budget_tier": budget_info["budget_range"],
                "family": meal_plan_request.family_size,
                "location": meal_plan_request.location,
                "days": day_count,
                "total_cost": meal_plan_data.get("total_cost_estimate", 0),
                "includes_snacks": includes_snacks
            }
        }
        
        # Add upgrade notice if budget was auto-upgraded
        if budget_info["was_upgraded"]:
            response_data["notice"] = {
                "type": "budget_upgraded",
                "message": f"Budget automatically upgraded from {budget_info['original_budget']} to {budget_info['budget_range']} for family of {meal_plan_request.family_size} to ensure adequate nutrition.",
                "original_budget": budget_info["original_budget"],
                "new_budget": budget_info["budget_range"]
            }
        
        return response_data
    except Exception as e:
        print(f"Meal Plan Error: {e}")
        return {"error": str(e)}

@app.post("/analyze-loan")
@limiter.limit("5/minute")
async def analyze_loan(
    request: Request,
    loan_request: LoanAdvisorRequest, 
    profile: Annotated[dict, Depends(get_user_profile)]
):
    tier = profile['tier']
    if tier != 'pro':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature is for Pro members only.")
    
    model_to_use = "gpt-5-mini"

    try:
        dti_ratio = (loan_request.monthly_payment / loan_request.monthly_income) * 100
    except ZeroDivisionError:
        dti_ratio = 0
    
    system_prompt = f"""
Ikaw si Kaibigan, ang personal financial manager ng user. Hindi ka bangko, hindi ka robot—ikaw ang trusted friend na tumutulong sa mga desisyon sa pera.

BRAND VOICE:
- **Tone:** Taglish (natural mix of Filipino and English).
- **Persona:** Direct pero hindi harsh ("Hard Truth"). Parang kuya/ate na nagpapayo.
- **Values:** Emphasize being "masinop" (prudent), not just hardworking.
- **Formatting:** Use bolding for key numbers. Use emojis to make it friendly.
- Use Filipino expressions: "Eto ang totoo...", "Ang advice ko...",

CRITICAL RULES:
1. Use "Millions" or "Hundreds of Thousands" (NEVER use "lakhs").
2. **Context:** Understand Philippine context (e.g., mention "Petsa de Peligro" if the budget is tight).

USER'S FINANCIALS:
- Monthly Income: ₱{loan_request.monthly_income:,.2f}

LOAN DETAILS:
- Loan Amount: ₱{loan_request.loan_amount:,.2f}
- Monthly Payment: ₱{loan_request.monthly_payment:,.2f}
- Loan Term: {loan_request.loan_term_years} years
- Total Interest: ₱{loan_request.total_interest:,.2f}
- DTI Ratio: {dti_ratio:.2f}%

ANALYSIS STRUCTURE:
1. **Boss, eto ang verdict:** (Assess the DTI of {dti_ratio:.2f}%)
   - Below 10%: "✅ Very manageable 'to! Sisiw lang sa budget mo."
   - 10-20%: "👍 Affordable pa rin, pero stay disciplined."
   - 20-30%: "⚠️ Medyo mahigpit 'to. Konting allowance na lang ang matitira for savings."
   - 30%+: "🚨 Honest lang, Boss—delikado 'to. Malaki ang chance na mag-petsa de peligro ka."

2. **Ang ibig sabihin nito sa budget mo:** (Real Talk Analysis)
   - Explain how much is left for living expenses.
   - If DTI is high, warn them about the "borrow-bayad" cycle.

3. **About sa interest na ₱{loan_request.total_interest:,.2f}:**
   - Put this in perspective. (e.g., "Isipin mo, Boss: halos [X] months ng sweldo mo ay mapupunta lang sa interest.")
   - If interest is very high, use the analogy: "Parang bumili ka ng bahay pero binayaran mo ay pang-dalawa."

4. **Payo ni Kaibigan (Action Plan):**
   - Give 2-3 specific, actionable tips to lower the cost or manage the risk.
   - Mention "Negotiate rates", "Higher downpayment", or "Shorten term" if applicable.
   - End with an encouraging closing.

TONE EXAMPLES:
❌ "Your debt-to-income ratio is high."
✅ "Boss, diretsahan tayo: halos kalahati ng sweldo mo kakainin lang ng loan na 'to."

❌ "You will pay 1.5 lakhs in interest."
✅ "Ang babayaran mong interest ay hundreds of thousands—sobrang laki niyan."

❌ "Based on my analysis, your debt-to-income ratio indicates..."
✅ "Eto ang totoo, boss—'yung monthly mo, kakayanin naman ng income mo."

❌ "I recommend exploring options to reduce your interest burden."
✅ "Pro tip: Kung kaya mo mag-extra payment kahit ₱1,000/month, malaki matitipid mo sa interest."

Start with a warm Taglish greeting. End with encouragement.
"""
    
    user_prompt = "Here is my loan and my income. Can you please analyze it for me?"

    try:
        chat_completion = await client.chat.completions.create(
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
@limiter.limit("5/minute")
async def analyze_assistance(
    request: Request,
    assistance_request: AssistanceAdvisorRequest, 
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
    - Employment: {assistance_request.employment_status}
    - Has SSS: {assistance_request.has_sss}
    - Has Pag-IBIG: {assistance_request.has_pagibig}
    - Their Situation: "{assistance_request.situation_description}"

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
        chat_completion = await client.chat.completions.create(
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
@limiter.limit("5/minute")
async def create_recipe_from_notes(
    request: Request,
    recipe_request: RecipeNotesRequest,
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

    USER'S NOTES for "{recipe_request.recipe_name}":
    ---
    {recipe_request.notes}
    ---

    Now, return ONLY the valid JSON object. Do not add any conversational text.
    """

    try:
        print(f"Calling GPT-5-Mini for user {user_id}...")
        chat_completion = await client.chat.completions.create(
            model="gpt-5-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt}
            ]
        )
        
        ai_response_json = chat_completion.choices[0].message.content
        
        recipe_data = json.loads(ai_response_json)
        recipe_data['user_id'] = user_id
        recipe_data['name'] = recipe_request.recipe_name
        recipe_data['original_notes'] = recipe_request.notes

        print(f"Saving recipe '{recipe_request.recipe_name}' to Supabase...")
        insert_res = supabase.table('recipes').insert(recipe_data).execute()

        if not insert_res.data:
             raise HTTPException(status_code=500, detail="Failed to save recipe to database.")

        return insert_res.data[0] 

    except Exception as e:
        print(f"AI Chef Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI formatting error: {e}")


# --- 7. WEBHOOK ENDPOINT (THE "CASH REGISTER") ---
@app.post("/webhook-lemonsqueezy")
async def webhook_lemonsqueezy(request: Request):
    """
    Listens for events from Lemon Squeezy and updates the user's tier.
    """
    try:
        # 1. Get the Secret
        secret = os.environ.get("LEMONSQUEEZY_SIGNING_SECRET")
        if not secret:
            print("WEBHOOK ERROR: LEMONSQUEEZY_SIGNING_SECRET is not set.")
            raise HTTPException(status_code=500, detail="Webhook not configured")
            
        # 2. Get the Signature from Headers
        signature = request.headers.get("X-Signature")
        if not signature:
             raise HTTPException(status_code=400, detail="No signature header")

        # 3. Get the Raw Body (Critical for HMAC)
        payload = await request.body()
        
        # 4. Create the Digest (Use hexdigest for Lemon Squeezy)
        digest = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()

        # 5. Secure Compare
        if not hmac.compare_digest(digest, signature):
            print("WEBHOOK ERROR: Invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # 6. Parse JSON
        data = json.loads(payload)
        event_name = data.get("meta", {}).get("event_name")
        attributes = data.get("data", {}).get("attributes", {})
        
        # 7. Identify User
        user_id = data.get("meta", {}).get("custom_data", {}).get("user_id")
        user_email = attributes.get("user_email")
        
        status_val = attributes.get("status")
        
        # --- LOGIC HANDLER (Updated for "tier" column) ---
        
        # CASE A: Subscription Created/Active (Upgrade to PRO)
        if event_name in ["subscription_created", "subscription_updated"] and status_val == "active":
            print(f"WEBHOOK: Activating PRO for {user_email}")
            
            # Update to "pro"
            update_data = {"tier": "pro"} 
            
            if user_id:
                response = supabase.table("profiles").update(update_data).eq("id", user_id).execute()
            else:
                response = supabase.table("profiles").update(update_data).eq("email", user_email).execute()

            # Decrement Promo Logic (Only on creation)
            if event_name == "subscription_created":
                 try:
                    promo_res = supabase.table('launch_promo').select('spots_remaining').eq('id', 1).single().execute()
                    if promo_res.data and promo_res.data['spots_remaining'] > 0:
                        new_spots = promo_res.data['spots_remaining'] - 1
                        supabase.table('launch_promo').update({'spots_remaining': new_spots}).eq('id', 1).execute()
                 except Exception as e:
                    print(f"PROMO ERROR: {e}")

        # CASE B: Subscription Expired (Downgrade to FREE)
        elif event_name == "subscription_expired":
             print(f"WEBHOOK: Revoking PRO for {user_email}")
             
             # Update to "free"
             update_data = {"tier": "free"}
             
             if user_id:
                supabase.table("profiles").update(update_data).eq("id", user_id).execute()
             else:
                supabase.table("profiles").update(update_data).eq("email", user_email).execute()

        return {"status": "success"}

    except Exception as e:
        print(f"WEBHOOK EXCEPTION: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

