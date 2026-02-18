"""
PAUTANG Module Router — Kaibigan Pautang System
Track money you lent to others, with partial payments and AI reminders.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Annotated, Optional
from dependencies import get_user_profile, supabase, limiter
from openai import AsyncOpenAI
import datetime
import logging

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI()

# --- CONSTANTS ---
MAX_ACTIVE_PAUTANG = 3
MAX_MONTHLY_REMINDERS = 5

# Router configuration
router = APIRouter(
    prefix="/pautang",
    tags=["Pautang — Lending Tracker"],
    responses={401: {"description": "Unauthorized"}}
)

# --- PYDANTIC MODELS ---

class PautangCreate(BaseModel):
    borrower_name: str
    amount: float
    date_lent: Optional[datetime.date] = None
    expected_return_date: Optional[datetime.date] = None
    notes: Optional[str] = None

class PautangUpdate(BaseModel):
    borrower_name: Optional[str] = None
    amount: Optional[float] = None
    date_lent: Optional[datetime.date] = None
    expected_return_date: Optional[datetime.date] = None
    notes: Optional[str] = None

class PaymentCreate(BaseModel):
    amount: float
    payment_date: Optional[datetime.date] = None
    notes: Optional[str] = None

class ReminderRequest(BaseModel):
    tone: str  # "Gentle", "Firm", "Final"


# ──────────────────────────────────────────────
# 1. LIST PAUTANG (supports ?status=active|paid)
# ──────────────────────────────────────────────
@router.get("")
async def list_pautang(
    profile: Annotated[dict, Depends(get_user_profile)],
    pautang_status: Optional[str] = None,
):
    """List pautang records. Optional ?status=active|paid filter."""
    user_id = profile["id"]
    try:
        query = supabase.table("pautang").select("*").eq("user_id", user_id)
        if pautang_status in ("active", "paid"):
            query = query.eq("status", pautang_status)
        query = query.order("created_at", desc=True)
        res = query.execute()
        return res.data or []
    except Exception:
        logger.exception("list_pautang failed")
        raise HTTPException(status_code=500, detail="Failed to load pautang records")


# ──────────────────────────────────────────────
# 2. CREATE PAUTANG (max 3 active)
# ──────────────────────────────────────────────
@router.post("")
@limiter.limit("30/minute")
async def create_pautang(
    request: Request,
    body: PautangCreate,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Create a new pautang record. Max 3 active debts."""
    user_id = profile["id"]

    # Check active limit
    try:
        count_res = (
            supabase.table("pautang")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        active_count = count_res.count or 0
        if active_count >= MAX_ACTIVE_PAUTANG:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{active_count} of {MAX_ACTIVE_PAUTANG} active pautang reached. Mark one as paid to add more.",
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_pautang: failed to check active count")

    try:
        data = body.model_dump()
        data["user_id"] = user_id
        if data.get("date_lent") is None:
            data["date_lent"] = datetime.date.today().isoformat()
        else:
            data["date_lent"] = data["date_lent"].isoformat()
        if data.get("expected_return_date"):
            data["expected_return_date"] = data["expected_return_date"].isoformat()
        data["status"] = "active"

        insert_res = supabase.table("pautang").insert(data).execute()
        if not insert_res.data:
            raise HTTPException(status_code=500, detail="Failed to create pautang record.")
        return insert_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("create_pautang failed")
        raise HTTPException(status_code=500, detail="Failed to create pautang record")


# ──────────────────────────────────────────────
# 3. UPDATE PAUTANG (edit borrower, amount, dates, notes)
# ──────────────────────────────────────────────
@router.put("/{pautang_id}")
@limiter.limit("60/minute")
async def update_pautang(
    request: Request,
    pautang_id: str,
    body: PautangUpdate,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Update a pautang record (name, amount, dates, notes)."""
    user_id = profile["id"]
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Serialize dates
        for date_field in ("date_lent", "expected_return_date"):
            if date_field in update_data and update_data[date_field]:
                update_data[date_field] = update_data[date_field].isoformat()

        update_data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        res = (
            supabase.table("pautang")
            .update(update_data)
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Pautang not found or permission denied.")
        return res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_pautang failed")
        raise HTTPException(status_code=500, detail="Failed to update pautang record")


# ──────────────────────────────────────────────
# 4. DELETE PAUTANG
# ──────────────────────────────────────────────
@router.delete("/{pautang_id}")
@limiter.limit("30/minute")
async def delete_pautang(
    request: Request,
    pautang_id: str,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Delete a pautang record permanently."""
    user_id = profile["id"]
    try:
        res = (
            supabase.table("pautang")
            .delete()
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Pautang not found or permission denied.")
        return {"detail": "Pautang deleted successfully"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete_pautang failed")
        raise HTTPException(status_code=500, detail="Failed to delete pautang record")


# ──────────────────────────────────────────────
# 5. MARK FULLY PAID
# ──────────────────────────────────────────────
@router.post("/{pautang_id}/mark-paid")
@limiter.limit("30/minute")
async def mark_pautang_paid(
    request: Request,
    pautang_id: str,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Mark a pautang as fully paid."""
    user_id = profile["id"]
    try:
        res = (
            supabase.table("pautang")
            .update({
                "status": "paid",
                "paid_date": datetime.date.today().isoformat(),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Pautang not found, already paid, or permission denied.")
        return res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("mark_pautang_paid failed")
        raise HTTPException(status_code=500, detail="Failed to mark pautang as paid")


# ──────────────────────────────────────────────
# 6. LIST PAYMENTS for a pautang
# ──────────────────────────────────────────────
@router.get("/{pautang_id}/payments")
async def list_payments(
    pautang_id: str,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Get all payments for a pautang (newest first)."""
    user_id = profile["id"]
    try:
        # Verify ownership
        pautang_res = (
            supabase.table("pautang")
            .select("id")
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not pautang_res.data:
            raise HTTPException(status_code=404, detail="Pautang not found")

        payments_res = (
            supabase.table("pautang_payments")
            .select("*")
            .eq("pautang_id", pautang_id)
            .order("payment_date", desc=True)
            .execute()
        )
        return payments_res.data or []
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_payments failed")
        raise HTTPException(status_code=500, detail="Failed to load payments")


# ──────────────────────────────────────────────
# 7. ADD PAYMENT
# ──────────────────────────────────────────────
@router.post("/{pautang_id}/payments")
@limiter.limit("30/minute")
async def add_payment(
    request: Request,
    pautang_id: str,
    body: PaymentCreate,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Record a partial or full payment."""
    user_id = profile["id"]
    try:
        # Verify ownership and get pautang data
        pautang_res = (
            supabase.table("pautang")
            .select("*")
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        if not pautang_res.data:
            raise HTTPException(status_code=404, detail="Active pautang not found")

        pautang = pautang_res.data[0]

        # Calculate total paid so far
        existing_payments_res = (
            supabase.table("pautang_payments")
            .select("amount")
            .eq("pautang_id", pautang_id)
            .execute()
        )
        total_paid = sum(p["amount"] for p in (existing_payments_res.data or []))
        remaining = float(pautang["amount"]) - total_paid

        if body.amount > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Payment amount (₱{body.amount:,.2f}) exceeds remaining balance (₱{remaining:,.2f})",
            )
        if body.amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be positive")

        # Insert payment
        payment_data = {
            "pautang_id": pautang_id,
            "amount": body.amount,
            "payment_date": (body.payment_date or datetime.date.today()).isoformat(),
        }
        if body.notes:
            payment_data["notes"] = body.notes

        payment_res = supabase.table("pautang_payments").insert(payment_data).execute()
        if not payment_res.data:
            raise HTTPException(status_code=500, detail="Failed to record payment")

        # Auto-mark as paid if fully repaid
        new_total_paid = total_paid + body.amount
        if new_total_paid >= float(pautang["amount"]):
            supabase.table("pautang").update({
                "status": "paid",
                "paid_date": datetime.date.today().isoformat(),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }).eq("id", pautang_id).execute()

        return {
            "payment": payment_res.data[0],
            "total_paid": new_total_paid,
            "remaining": float(pautang["amount"]) - new_total_paid,
            "auto_paid": new_total_paid >= float(pautang["amount"]),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("add_payment failed")
        raise HTTPException(status_code=500, detail="Failed to record payment")


# ──────────────────────────────────────────────
# 8. GENERATE AI REMINDER (5/month for all)
# ──────────────────────────────────────────────
@router.post("/{pautang_id}/reminder")
@limiter.limit("5/minute")
async def generate_reminder(
    request: Request,
    pautang_id: str,
    body: ReminderRequest,
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Generate an AI-powered reminder message. 5/month limit for all users."""
    user_id = profile["id"]

    if body.tone not in ("Gentle", "Firm", "Final"):
        raise HTTPException(status_code=400, detail="Tone must be Gentle, Firm, or Final")

    # Check monthly limit
    month_year = datetime.date.today().strftime("%Y-%m")
    try:
        usage_res = (
            supabase.table("ai_reminder_usage")
            .select("*")
            .eq("user_id", user_id)
            .eq("month_year", month_year)
            .execute()
        )
        usage = usage_res.data[0] if usage_res.data else None
        current_count = usage["usage_count"] if usage else 0

        if current_count >= MAX_MONTHLY_REMINDERS:
            # Calculate reset date
            today = datetime.date.today()
            if today.month == 12:
                reset_date = datetime.date(today.year + 1, 1, 1)
            else:
                reset_date = datetime.date(today.year, today.month + 1, 1)
            raise HTTPException(
                status_code=429,
                detail=f"You've used all {MAX_MONTHLY_REMINDERS} reminders this month. Resets on {reset_date.strftime('%B %d, %Y')}.",
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("generate_reminder: failed to check usage")

    # Get the pautang details
    try:
        pautang_res = (
            supabase.table("pautang")
            .select("*")
            .eq("id", pautang_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not pautang_res.data:
            raise HTTPException(status_code=404, detail="Pautang not found")

        pautang = pautang_res.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("generate_reminder: failed to fetch pautang")
        raise HTTPException(status_code=500, detail="Failed to load pautang")

    # Calculate overdue days
    days_overdue = 0
    if pautang.get("expected_return_date"):
        try:
            return_date = datetime.date.fromisoformat(pautang["expected_return_date"])
            delta = datetime.date.today() - return_date
            if delta.days > 0:
                days_overdue = delta.days
        except (ValueError, TypeError):
            pass

    # Calculate total paid for remaining amount
    try:
        payments_res = (
            supabase.table("pautang_payments")
            .select("amount")
            .eq("pautang_id", pautang_id)
            .execute()
        )
        total_paid = sum(p["amount"] for p in (payments_res.data or []))
    except Exception:
        total_paid = 0

    remaining_amount = float(pautang["amount"]) - total_paid

    tone_instructions = {
        "Gentle": "a very gentle, friendly, and 'nahihiya' reminder. Start with 'Hi [Name], kumusta?'. Use humor if appropriate.",
        "Firm": "a polite but firm and direct reminder that the payment is due. Mention the amount clearly. Reference agreed date if available.",
        "Final": "a final, urgent, and very serious reminder that the payment is long overdue. Still respectful but clear about need.",
    }

    expected_date_str = ""
    if pautang.get("expected_return_date"):
        expected_date_str = f"\n- Expected return date: {pautang['expected_return_date']}"

    system_prompt = f"""Generate a debt reminder message in Taglish (Tagalog-English mix).

Context:
- Borrower: {pautang['borrower_name']}
- Original amount: ₱{float(pautang['amount']):,.2f}
- Remaining balance: ₱{remaining_amount:,.2f}
- Date lent: {pautang['date_lent']}{expected_date_str}
- Days overdue: {days_overdue}
- Notes: {pautang.get('notes') or 'None'}
- Tone: {body.tone}

Tone guidelines:
- {tone_instructions.get(body.tone, "polite tone")}

Keep message under 200 characters for easy copy-paste to Messenger/SMS.
Respond *only* with the message itself. Do not add any extra text or explanation."""

    try:
        chat_completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}],
        )
        ai_response = chat_completion.choices[0].message.content

        # Update reminders_generated on the pautang record
        reminders = pautang.get("reminders_generated") or {}
        reminders[body.tone.lower()] = {
            "date": datetime.date.today().isoformat(),
            "message": ai_response,
        }
        supabase.table("pautang").update({
            "reminders_generated": reminders,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", pautang_id).execute()

        # Increment usage counter
        if usage:
            supabase.table("ai_reminder_usage").update({
                "usage_count": current_count + 1,
            }).eq("id", usage["id"]).execute()
        else:
            supabase.table("ai_reminder_usage").insert({
                "user_id": user_id,
                "month_year": month_year,
                "usage_count": 1,
            }).execute()

        return {
            "message": ai_response,
            "tone": body.tone,
            "usage_count": current_count + 1,
            "usage_limit": MAX_MONTHLY_REMINDERS,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("generate_reminder failed")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")


# ──────────────────────────────────────────────
# 9. GET REMINDER USAGE (monthly count + reset date)
# ──────────────────────────────────────────────
@router.get("/reminder-usage")
async def get_reminder_usage(
    profile: Annotated[dict, Depends(get_user_profile)],
):
    """Get the user's AI reminder usage for the current month."""
    user_id = profile["id"]
    month_year = datetime.date.today().strftime("%Y-%m")

    try:
        usage_res = (
            supabase.table("ai_reminder_usage")
            .select("*")
            .eq("user_id", user_id)
            .eq("month_year", month_year)
            .execute()
        )
        current_count = usage_res.data[0]["usage_count"] if usage_res.data else 0

        # Calculate reset date (1st of next month)
        today = datetime.date.today()
        if today.month == 12:
            reset_date = datetime.date(today.year + 1, 1, 1)
        else:
            reset_date = datetime.date(today.year, today.month + 1, 1)

        return {
            "usage_count": current_count,
            "usage_limit": MAX_MONTHLY_REMINDERS,
            "month_year": month_year,
            "reset_date": reset_date.isoformat(),
        }
    except Exception:
        logger.exception("get_reminder_usage failed")
        raise HTTPException(status_code=500, detail="Failed to load reminder usage")
