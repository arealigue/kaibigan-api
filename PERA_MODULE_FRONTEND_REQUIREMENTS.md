# Pera Module - Complete Frontend Requirements
**Financial Hub for KaibiganGPT**  
**Version:** 1.0 | **Date:** November 15, 2025

---

## 📋 Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Pera Dashboard (Landing Page)](#1-pera-dashboard-landing-page)
3. [Kaibigan Kaban (Expense Tracker)](#2-kaibigan-kaban-expense-tracker)
4. [Ipon Tracker (Savings Goals)](#3-ipon-tracker-savings-goals)
5. [Utang Tracker (Debt Management)](#4-utang-tracker-debt-management)
6. [AI Financial Advisor](#5-ai-financial-advisor)
7. [API Reference](#api-reference)
8. [Implementation Checklist](#implementation-checklist)

---

## Architecture Overview

### Navigation Structure
```
Pera (Dashboard/Overview) ← Main landing page
├── Kaibigan Kaban (Full expense tracker) - NEW ⭐
├── Ipon Tracker (Savings goals) - EXISTING
├── Utang Tracker (Debt management) - MOVED FROM TULONG
├── Loan Calculator (Free tool) - EXISTING
└── AI Financial Advisor (Pro AI hub) - NEW ⭐
```

### Key Architectural Decisions
- ✅ **Dashboard-first approach** (not tabs) - Pera page is a navigation hub
- ✅ **Utang moved entirely** from Tulong module to Pera module
- ✅ **Live data for Pro**, static snapshots for Free users
- ✅ **Responsive grid layout** (auto-adjusts: mobile 1-2 cols, desktop 3-4 cols)
- ✅ **Backend ready** - All endpoints implemented and tested
- ✅ **Priority order**: Kaban → Loan Analyzer → Spending Insights

### Pro vs Free Feature Matrix

| Feature | Free | Pro |
|---------|------|-----|
| Pera Dashboard | Static preview ("Last updated X mins ago") | Live data, real-time |
| Kaibigan Kaban | ❌ Locked (Upgrade CTA) | ✅ Full access |
| Ipon Tracker | ❌ Locked | ✅ Full access |
| Utang Tracker | ❌ Locked | ✅ Full access |
| Loan Calculator | ✅ Full access | ✅ Full access |
| AI Loan Analyzer | ❌ Locked | ✅ Full access |
| AI Spending Insights | ❌ Locked | ✅ Full access |

---

## 1. Pera Dashboard (Landing Page)

### Route: `/pera`

### Purpose
- Financial health snapshot
- Quick actions hub
- Navigation to sub-modules
- Conversion funnel for Free → Pro

### Layout Structure

```
┌────────────────────────────────────────────────────────────┐
│ Pera (Money)                           [PRO Badge] [Upgrade]│
│ Tignan ang iyong financial health                          │
│ 🗓️ November 2025                                           │
├────────────────────────────────────────────────────────────┤
│ ┌──────────────┬──────────────┬──────────────┬───────────┐│
│ │💰 Total Kita │💸 Gastos     │💵 Balance    │📊 Change  ││
│ │ ₱50,000      │ ₱32,450      │ ₱17,550      │ +12%      ││
│ │ This Month   │ This Month   │              │ vs Oct    ││
│ └──────────────┴──────────────┴──────────────┴───────────┘│
├────────────────────────────────────────────────────────────┤
│ Quick Actions:                                              │
│ [+ Bagong Gastos] [+ Ipon] [+ Utang] [📊 View Details]    │
├────────────────────────────────────────────────────────────┤
│ ┌─Module Cards Grid (Responsive)──────────────────────────┐│
│ │                                                          ││
│ │ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ││
│ │ │🏦 Kaban      │  │💎 Ipon       │  │📝 Utang      │  ││
│ │ │Expense Track │  │Savings Goals │  │Debt Manager  │  ││
│ │ │47 trans      │  │3 goals       │  │2 unpaid      │  ││
│ │ │[Open →]      │  │[Open →]      │  │[Open →]      │  ││
│ │ └──────────────┘  └──────────────┘  └──────────────┘  ││
│ │                                                          ││
│ │ ┌──────────────┐  ┌──────────────┐                     ││
│ │ │🧮 Calculator │  │✨ AI Advisor │                     ││
│ │ │Loan Calc     │  │AI Insights   │                     ││
│ │ │(FREE)        │  │(PRO)         │                     ││
│ │ │[Open →]      │  │[Open →]      │                     ││
│ │ └──────────────┘  └──────────────┘                     ││
│ └──────────────────────────────────────────────────────────┘│
├────────────────────────────────────────────────────────────┤
│ Recent Activity (Unified Feed)                              │
│ ┌──────────────────────────────────────────────────────┐   │
│ │🍽️ Pagkain • Jollibee    Nov 15, 2:30 PM    -₱250   │   │
│ │💎 Ipon • Laptop Fund     Nov 15, 9:00 AM    +₱500   │   │
│ │🚗 Transport • Grab       Nov 14, 8:15 AM    -₱120   │   │
│ └──────────────────────────────────────────────────────┘   │
│                            [View All Activity →]            │
└────────────────────────────────────────────────────────────┘
```

### Components Breakdown

#### A. Header Section
- **Title:** "Pera (Money)"
- **Subtitle:** "Tignan ang iyong financial health"
- **User Tier Badge:** Shows "FREE" or "PRO"
- **Upgrade Button:** Visible for free users
- **Month Selector:** Dropdown to change month (affects summary cards)

#### B. Financial Summary Cards (Top Row)
**Data Source:** `GET /kaban/summary?year={year}&month={month}`

**For Pro Users:**
- Real-time data fetched on page load
- Auto-refresh every 5 minutes (optional)
- Green/red color coding for positive/negative

**For Free Users:**
- Show placeholder cards with blurred numbers
- Text: "Upgrade to Pro to track your expenses"
- Or show static message: "Last updated: Never (Upgrade to Pro)"
- Small "🔒" icon on each card

**Cards:**
1. **Total Kita (Income)** - Green text, ₱ format
2. **Total Gastos (Expense)** - Red text, ₱ format
3. **Net Balance** - Conditional color (green if positive, red if negative)
4. **This Month vs Last Month** - Percentage change with ↑↓ arrow

#### C. Quick Actions Bar
**Floating action buttons for common tasks:**
- `[+ Bagong Gastos]` → Opens "Add Transaction" modal (Kaban)
- `[+ Ipon Deposit]` → Opens "Add to Goal" modal (Ipon)
- `[+ Utang Record]` → Opens "Record Debt" modal (Utang)
- `[📊 View All]` → Goes to unified activity log

**Pro Users:** All buttons functional
**Free Users:** Buttons show "Upgrade to Pro" tooltip on click

#### D. Module Cards Grid
**Grid Layout:**
- Mobile: 1 column (stacked)
- Tablet: 2 columns
- Desktop: 3-4 columns

**Card 1: Kaibigan Kaban 🏦** (NEW)
```
┌────────────────────────────────┐
│ 🏦 Kaibigan Kaban              │
│ Expense & Income Tracker       │
│                                │
│ This Month:                    │
│ • 47 transactions              │
│ • Top: 🍽️ Pagkain (₱8,200)    │
│ • Recent: Jollibee (2h ago)   │
│                                │
│        [Open Kaban →]          │
│                                │
│ FREE: [🔒 Upgrade to Access]   │
└────────────────────────────────┘
```
- **Pro:** Shows live preview, clickable
- **Free:** Grayed out, shows upgrade button

**Card 2: Ipon Tracker 💎** (EXISTING)
```
┌────────────────────────────────┐
│ 💎 Ipon Tracker                │
│ Savings Goals                  │
│                                │
│ Active Goals: 3                │
│ • Laptop: 68% (₱20.4k/₱30k)   │
│ • Emergency: 42% (₱21k/₱50k)  │
│                                │
│        [Open Ipon →]           │
└────────────────────────────────┘
```
- **Pro:** Shows goals with progress bars
- **Free:** Locked with upgrade CTA

**Card 3: Utang Tracker 📝** (MOVED FROM TULONG)
```
┌────────────────────────────────┐
│ 📝 Utang Tracker               │
│ Debt Management                │
│                                │
│ Unpaid Debts: 2                │
│ • Juan - ₱5,000 (Due: Nov 20) │
│ • Maria - ₱2,500 (OVERDUE!)   │
│                                │
│        [Open Utang →]          │
└────────────────────────────────┘
```
- Shows urgent/overdue debts
- Red badge for overdue items
- **Pro only**

**Card 4: Loan Calculator 🧮** (EXISTING - FREE)
```
┌────────────────────────────────┐
│ 🧮 Loan Calculator             │
│ Housing Loan Estimator (FREE)  │
│                                │
│ Calculate monthly payments     │
│ for any loan amount            │
│                                │
│        [Calculate →]           │
└────────────────────────────────┘
```
- **Free & Pro:** Everyone has access
- Already implemented in backend: `POST /calculate-loan`

**Card 5: AI Financial Advisor ✨** (NEW - PRO)
```
┌────────────────────────────────┐
│ ✨ AI Financial Advisor (PRO)  │
│ Personalized Insights          │
│                                │
│ • Loan Analyzer                │
│ • Spending Insights            │
│ • More tools coming...         │
│                                │
│        [Open Advisor →]        │
└────────────────────────────────┘
```
- **Pro:** Access to AI tools
- **Free:** Shows upgrade overlay

#### E. Recent Activity Feed
**Purpose:** Unified view of all financial activities

**Data Sources:**
- Kaban transactions: `GET /kaban/transactions` (limit 5)
- Ipon deposits: `GET /ipon/goals` then `/transactions`
- Utang payments: `GET /utang/debts`

**Display:**
- Last 5-10 activities across all modules
- Format: `{emoji} {category} • {description}  {date/time}  {amount}`
- Click item → Navigate to source module
- "View All Activity" → Full activity log page

**For Free Users:**
- Show empty state: "Upgrade to Pro to track activities"

---

## 2. Kaibigan Kaban (Expense Tracker)

### Route: `/pera/kaban`

### Purpose
Full-featured expense and income tracking system (the heart of Pera module)

### Layout Structure

```
┌─────────────────────────────────────────────────────────┐
│ [← Back to Pera] Kaibigan Kaban      🗓️ November 2025  │
├─────────────────────────────────────────────────────────┤
│ ┌──────────────┬──────────────┬──────────────┐         │
│ │💰 Kita       │💸 Gastos     │💵 Balance    │         │
│ │ ₱50,000      │ ₱32,450      │ ₱17,550      │         │
│ └──────────────┴──────────────┴──────────────┘         │
│                                                          │
│ [+ Add Transaction] [📊 Analytics] [📥 Export CSV]      │
├─────────────────────────────────────────────────────────┤
│ ┌─Categories────┐ ┌─Transactions─────────────────────┐ │
│ │🍽️ Pagkain    │ │ Filters: [Date] [Type] [Category]│ │
│ │🚗 Transport   │ ├──────────────────────────────────┤ │
│ │🏠 Bahay       │ │ Nov 15 • 🍽️ Jollibee    -₱250   │ │
│ │⚡ Kuryente    │ │         Lunch with team          │ │
│ │💼 Sahod       │ │         [Edit] [Delete]          │ │
│ │[+ Custom]     │ ├──────────────────────────────────┤ │
│ └───────────────┘ │ Nov 15 • 💼 Sahod      +₱15,000  │ │
│                   │         Monthly salary           │ │
│                   │         [Edit] [Delete]          │ │
│                   └──────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ ┌─Analytics Chart (Collapsible)──────────────────────┐ │
│ │     [Pie Chart: Spending by Category]             │ │
│ │ 🍽️ Pagkain 35% • 🚗 Transport 20% • 🏠 Rent 30%   │ │
│ └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Components Breakdown

#### A. Summary Cards (Top)
**API:** `GET /kaban/summary?year={year}&month={month}`

**Response:**
```json
{
  "year": 2025,
  "month": 11,
  "total_income": 50000,
  "total_expense": 32450,
  "balance": 17550,
  "transaction_count": 47
}
```

**Display:**
- 3 cards: Kita (green), Gastos (red), Balance (conditional)
- Format amounts with ₱ and commas: `₱50,000`
- Show transaction count as subtitle

#### B. Action Bar
- **[+ Add Transaction]** → Opens add modal
- **[📊 Analytics]** → Toggle analytics chart visibility
- **[📥 Export CSV]** → Future feature (not implemented yet)

#### C. Categories Panel (Left Side)
**API:** `GET /kaban/categories`

**Response:**
```json
[
  {
    "id": "uuid-1",
    "name": "Pagkain",
    "emoji": "🍽️",
    "user_id": null  // Default category
  },
  {
    "id": "uuid-2",
    "name": "Car Maintenance",
    "emoji": "🔧",
    "user_id": "user-uuid"  // Custom category
  }
]
```

**Features:**
- Display all categories (default + custom)
- Default categories have `user_id: null`
- Custom categories have `user_id: {user's UUID}`
- Click category → Filter transactions by category
- **[+ Add Custom Category]** button (Pro only)

**Add Category Modal:**
```
Add Custom Category
┌────────────────────────────┐
│ Category Name:             │
│ [________________]         │
│                            │
│ Emoji (optional):          │
│ [________________]         │
│                            │
│   [Cancel]  [Create]       │
└────────────────────────────┘
```
**API:** `POST /kaban/categories`
**Body:** `{name: "Car Maintenance", emoji: "🔧"}`

#### D. Transactions List (Center/Right)
**API:** `GET /kaban/transactions?start_date={date}&end_date={date}&transaction_type={type}&category_id={id}`

**Response:**
```json
[
  {
    "id": "tx-uuid-1",
    "user_id": "user-uuid",
    "category_id": "cat-uuid",
    "amount": 250,
    "transaction_type": "expense",
    "transaction_date": "2025-11-15",
    "description": "Jollibee lunch",
    "created_at": "2025-11-15T14:30:00",
    "expense_categories": {
      "name": "Pagkain",
      "emoji": "🍽️"
    }
  }
]
```

**Features:**
- **Filters:**
  - Date range picker (start_date, end_date)
  - Type: All / Kita / Gastos
  - Category dropdown
- **Display:**
  - Date | Category emoji+name | Description | Amount
  - Red text for expenses (-₱250), Green for income (+₱15,000)
  - Relative time: "2h ago", "Yesterday", "Nov 15"
- **Actions per item:**
  - [Edit] → Opens edit modal
  - [Delete] → Confirmation dialog → DELETE request

**Add Transaction Modal:**
```
Add Transaction
┌────────────────────────────┐
│ Amount (₱):                │
│ [________________]         │
│                            │
│ Type:                      │
│ ⚫ Gastos  ⚪ Kita          │
│                            │
│ Category:                  │
│ [Dropdown ▼]               │
│                            │
│ Description (optional):    │
│ [________________]         │
│                            │
│ Date:                      │
│ [2025-11-15]  📅           │
│                            │
│   [Cancel]  [Add]          │
└────────────────────────────┘
```
**API:** `POST /kaban/transactions`
**Body:**
```json
{
  "category_id": "uuid",
  "amount": 250,
  "transaction_type": "expense",
  "description": "Jollibee lunch",
  "transaction_date": "2025-11-15"
}
```

**Edit Transaction Modal:**
- Same fields as Add modal
- Pre-filled with existing data
- **API:** `PUT /kaban/transactions/{id}`
- **Body:** Same as POST (only changed fields)

**Delete Transaction:**
- Show confirmation dialog: "Delete this transaction? This cannot be undone."
- **API:** `DELETE /kaban/transactions/{id}`

#### E. Analytics Chart (Bottom - Collapsible)
**API:** `GET /kaban/stats/category?year={year}&month={month}`

**Response:**
```json
{
  "year": 2025,
  "month": 11,
  "categories": [
    {
      "category_id": "uuid-1",
      "category_name": "Pagkain",
      "emoji": "🍽️",
      "total": 8200,
      "count": 15
    },
    {
      "category_id": "uuid-2",
      "category_name": "Transportasyon",
      "emoji": "🚗",
      "total": 5400,
      "count": 22
    }
  ],
  "total_categories": 5
}
```

**Visualization:**
- **Pie Chart** or **Bar Chart** showing spending by category
- Use Chart.js, Recharts, or ApexCharts
- Display: Category emoji + name + percentage
- Click slice → Filter transactions by that category
- Show total amount per category
- Empty state: "No expenses this month" (if no data)

### Mobile Optimization
- Stack summary cards vertically
- Hide categories panel (show as drawer/modal)
- Floating Action Button (FAB) for "+ Add Transaction"
- Swipe left on transaction item → Show Edit/Delete actions

---

## 3. Ipon Tracker (Savings Goals)

### Route: `/pera/ipon`

### Purpose
Manage savings goals and track deposits (existing feature, needs integration)

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│ [← Back to Pera] Ipon Tracker           [+ New Goal]    │
├─────────────────────────────────────────────────────────┤
│ Active Goals                                             │
│                                                          │
│ ┌─Goal Card──────────────────────────────────────────┐  │
│ │ 💻 Laptop Fund                                     │  │
│ │ ₱20,400 / ₱30,000 (68%)                           │  │
│ │ [████████████░░░░░░] Target: Dec 2025             │  │
│ │ [+ Add Deposit] [View History] [Edit] [Delete]    │  │
│ └────────────────────────────────────────────────────┘  │
│                                                          │
│ ┌─Goal Card──────────────────────────────────────────┐  │
│ │ 🚨 Emergency Fund                                  │  │
│ │ ₱21,000 / ₱50,000 (42%)                           │  │
│ │ [████████░░░░░░░░░░] Target: Jun 2026             │  │
│ │ [+ Add Deposit] [View History] [Edit] [Delete]    │  │
│ └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### API Endpoints (Already Implemented)

#### Create Goal
**API:** `POST /ipon/goals`
**Body:**
```json
{
  "name": "Laptop Fund",
  "target_amount": 30000,
  "target_date": "2025-12-31"
}
```

#### Get All Goals
**API:** `GET /ipon/goals`
**Response:**
```json
[
  {
    "id": "goal-uuid-1",
    "user_id": "user-uuid",
    "name": "Laptop Fund",
    "target_amount": 30000,
    "target_date": "2025-12-31",
    "created_at": "2025-01-01T00:00:00"
  }
]
```

#### Add Deposit
**API:** `POST /ipon/transactions`
**Body:**
```json
{
  "goal_id": "goal-uuid-1",
  "amount": 500,
  "notes": "Weekly deposit"
}
```

#### Get Goal Transactions
**API:** `GET /ipon/goals/{goal_id}/transactions`
**Response:**
```json
[
  {
    "id": "tx-uuid",
    "user_id": "user-uuid",
    "goal_id": "goal-uuid-1",
    "amount": 500,
    "notes": "Weekly deposit",
    "created_at": "2025-11-15T10:00:00"
  }
]
```

### Features
- Goal progress bar (visual percentage)
- Calculate progress: `(total_deposits / target_amount) * 100`
- Show total saved vs target
- Add deposit modal
- Transaction history modal (list all deposits for a goal)
- Edit/Delete goal (frontend only, no backend endpoints yet)

---

## 4. Utang Tracker (Debt Management)

### Route: `/pera/utang`

### Purpose
Track debts owed by others and generate AI collection messages

**Note:** This is being **moved from Tulong module to Pera module**. No backend changes needed.

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│ [← Back to Pera] Utang Tracker      [+ Record Utang]    │
├─────────────────────────────────────────────────────────┤
│ Unpaid Debts (₱7,500 total)                             │
│                                                          │
│ ┌─Debt Card─────────────────────────────────────────┐   │
│ │ 👤 Juan dela Cruz                                 │   │
│ │ Amount: ₱5,000 • Due: Nov 20, 2025               │   │
│ │ Notes: Pautang for emergency                      │   │
│ │ [Mark as Paid] [Generate Message] [Edit]         │   │
│ └───────────────────────────────────────────────────┘   │
│                                                          │
│ ┌─Debt Card─────────────────────────────────────────┐   │
│ │ 👤 Maria Santos (⚠️ OVERDUE!)                     │   │
│ │ Amount: ₱2,500 • Due: Nov 10, 2025               │   │
│ │ Notes: Borrowed for tuition                       │   │
│ │ [Mark as Paid] [Generate Message] [Edit]         │   │
│ └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### API Endpoints (Already Implemented)

#### Create Debt Record
**API:** `POST /utang/debts`
**Body:**
```json
{
  "debtor_name": "Juan dela Cruz",
  "amount": 5000,
  "due_date": "2025-11-20",
  "notes": "Pautang for emergency"
}
```

#### Get All Unpaid Debts
**API:** `GET /utang/debts`
**Response:**
```json
[
  {
    "id": "debt-uuid-1",
    "user_id": "user-uuid",
    "debtor_name": "Juan dela Cruz",
    "amount": 5000,
    "due_date": "2025-11-20",
    "notes": "Pautang for emergency",
    "status": "unpaid",
    "created_at": "2025-10-01T00:00:00"
  }
]
```

#### Update Debt Status
**API:** `PUT /utang/debts/{debt_id}`
**Body:**
```json
{
  "status": "paid"
}
```

#### Generate AI Collection Message
**API:** `POST /utang/generate-message`
**Body:**
```json
{
  "debtor_name": "Juan dela Cruz",
  "amount": 5000,
  "tone": "Gentle"
}
```
**Response:**
```json
{
  "message": "Hi Juan, kumusta? Pasensya na sa abala. Pwede po bang paalala lang sa ₱5,000 na inutang mo last month? Salamat!"
}
```

### Features
- Show overdue badge (red) if `due_date < today`
- Calculate total unpaid: sum all `amount` where `status == 'unpaid'`
- Mark as paid button → Update status
- Generate message modal → Select tone → Copy result
- Filter: All / Unpaid / Paid / Overdue

### AI Message Generator Modal
```
Generate Collection Message
┌────────────────────────────────────┐
│ Debtor: Juan dela Cruz            │
│ Amount: ₱5,000                     │
│                                    │
│ Select Tone:                       │
│ ⚫ Gentle  ⚪ Firm  ⚪ Final        │
│                                    │
│        [Generate Message]          │
│                                    │
│ Generated Message:                 │
│ ┌────────────────────────────────┐│
│ │Hi Juan, kumusta? Pasensya na  ││
│ │sa abala. Pwede po bang paalala││
│ │lang sa ₱5,000 na inutang mo...││
│ └────────────────────────────────┘│
│        [📋 Copy Message]           │
└────────────────────────────────────┘
```

**Tone Options:**
- **Gentle:** "nahihiya" reminder, friendly
- **Firm:** Polite but direct
- **Final:** Urgent, serious tone

---

## 5. AI Financial Advisor

### Route: `/pera/ai-advisor`

### Purpose
Hub for AI-powered financial tools (Pro only)

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│ [← Back to Pera] ✨ AI Financial Advisor (PRO)          │
├─────────────────────────────────────────────────────────┤
│ AI Tools                                                 │
│                                                          │
│ ┌─Tool Card─────────────────────────────────────────┐   │
│ │ 🏦 Loan Analyzer                                  │   │
│ │ Analyze if a loan is affordable based on income  │   │
│ │ [Analyze Loan →]                                  │   │
│ └───────────────────────────────────────────────────┘   │
│                                                          │
│ ┌─Tool Card─────────────────────────────────────────┐   │
│ │ 💡 Spending Insights (Coming Soon)                │   │
│ │ AI-powered analysis of spending patterns         │   │
│ │ [Get Insights →] 🔒                               │   │
│ └───────────────────────────────────────────────────┘   │
│                                                          │
│ ┌─Tool Card─────────────────────────────────────────┐   │
│ │ 📊 More AI Tools Coming...                        │   │
│ │ Stay tuned for updates!                           │   │
│ └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### A. Loan Analyzer (Priority 1)

**API:** `POST /analyze-loan` (Already implemented)

**Input Form:**
```
AI Loan Analyzer
┌────────────────────────────────────┐
│ Your Monthly Income (₱):           │
│ [50000]                            │
│                                    │
│ Loan Details (from calculator):    │
│ • Amount: ₱3,000,000              │
│ • Monthly Payment: ₱21,490        │
│ • Total Interest: ₱1,736,400      │
│ • Loan Term: 30 years             │
│                                    │
│        [Analyze My Loan]           │
└────────────────────────────────────┘
```

**Request Body:**
```json
{
  "loan_amount": 3000000,
  "monthly_payment": 21490,
  "total_interest": 1736400,
  "loan_term_years": 30,
  "monthly_income": 50000
}
```

**Response:**
```json
{
  "analysis": "Kumusta! Based on your ₱50,000 monthly income...\n\n**Affordability:** High Risk / Not Recommended\n\nYour Debt-to-Income (DTI) ratio is 43%..."
}
```

**Display:**
- Show AI response in markdown format
- Color-code verdict: Green (affordable), Yellow (manageable), Red (not recommended)
- Add "Copy Analysis" button
- Option to save analysis (future feature)

### B. Spending Insights (Priority 2 - Coming Soon)

**Planned Features:**
- Analyze Kaban transaction data
- Identify spending patterns
- Suggest budget optimizations
- Compare to similar users (anonymized)

**API:** Not implemented yet (Phase 2)

---

## API Reference

### Base URL
```
Production: https://kaibigan-api.vercel.app
Local Dev: http://localhost:8000
```

### Authentication
All endpoints (except Loan Calculator) require JWT token:
```javascript
headers: {
  'Authorization': 'Bearer {jwt_token}'
}
```

### Endpoints Summary

| Method | Endpoint | Auth | Tier | Purpose |
|--------|----------|------|------|---------|
| **Kaban** |
| GET | `/kaban/categories` | ✅ | Pro | List all categories |
| POST | `/kaban/categories` | ✅ | Pro | Create custom category |
| POST | `/kaban/transactions` | ✅ | Pro | Add transaction |
| GET | `/kaban/transactions` | ✅ | Pro | List transactions (with filters) |
| PUT | `/kaban/transactions/{id}` | ✅ | Pro | Update transaction |
| DELETE | `/kaban/transactions/{id}` | ✅ | Pro | Delete transaction |
| GET | `/kaban/summary` | ✅ | Pro | Monthly summary |
| GET | `/kaban/stats/category` | ✅ | Pro | Category breakdown |
| **Ipon** |
| POST | `/ipon/goals` | ✅ | Pro | Create savings goal |
| GET | `/ipon/goals` | ✅ | Pro | List all goals |
| POST | `/ipon/transactions` | ✅ | Pro | Add deposit to goal |
| GET | `/ipon/goals/{id}/transactions` | ✅ | Pro | Get goal transactions |
| **Utang** |
| POST | `/utang/debts` | ✅ | Pro | Record debt |
| GET | `/utang/debts` | ✅ | Pro | List unpaid debts |
| PUT | `/utang/debts/{id}` | ✅ | Pro | Update debt status |
| POST | `/utang/generate-message` | ✅ | Pro | Generate AI message |
| **Loan & AI** |
| POST | `/calculate-loan` | ❌ | Free | Calculate loan (client-side OK) |
| POST | `/analyze-loan` | ✅ | Pro | AI loan analysis |

### Error Handling

**403 Forbidden (Non-Pro):**
```json
{
  "detail": "Kaibigan Kaban is a Pro feature."
}
```
**Frontend Action:** Show upgrade modal

**404 Not Found:**
```json
{
  "detail": "Transaction not found or permission denied."
}
```
**Frontend Action:** Show error toast, refresh list

**500 Server Error:**
```json
{
  "detail": "Failed to create transaction."
}
```
**Frontend Action:** Show error toast, retry button

---

## Implementation Checklist

### Phase 1: Pera Dashboard (Week 1)
- [ ] Create `/pera` route and layout
- [ ] Header section (title, tier badge, month selector)
- [ ] Summary cards component
  - [ ] Fetch `GET /kaban/summary`
  - [ ] Handle Pro vs Free display
  - [ ] Implement "Last updated X mins ago" for Free
- [ ] Quick actions bar (modals or navigation)
- [ ] Module cards grid (responsive layout)
  - [ ] Kaban card with live preview (Pro) or locked state (Free)
  - [ ] Ipon card
  - [ ] Utang card
  - [ ] Loan Calculator card
  - [ ] AI Advisor card
- [ ] Recent activity feed
  - [ ] Fetch unified data from Kaban, Ipon, Utang
  - [ ] Display with emoji, description, amount
  - [ ] "View All" link
- [ ] Pro gating logic
  - [ ] Check user tier from profile/auth
  - [ ] Show upgrade modals for Free users
  - [ ] Lock/unlock features dynamically
- [ ] Mobile responsive layout

### Phase 2: Kaibigan Kaban (Week 2-3)
- [ ] Create `/pera/kaban` route
- [ ] Summary cards (Kita, Gastos, Balance)
  - [ ] Fetch `GET /kaban/summary`
  - [ ] Month/year selector
- [ ] Categories panel
  - [ ] Fetch `GET /kaban/categories`
  - [ ] Display default + custom categories
  - [ ] Add custom category modal (Pro)
  - [ ] POST `/kaban/categories`
- [ ] Transactions list
  - [ ] Fetch `GET /kaban/transactions`
  - [ ] Implement filters (date range, type, category)
  - [ ] Pagination or infinite scroll
  - [ ] Edit/Delete actions
- [ ] Add transaction modal
  - [ ] Form: amount, type, category, description, date
  - [ ] POST `/kaban/transactions`
  - [ ] Validation (positive amount, required fields)
- [ ] Edit transaction modal
  - [ ] Pre-fill form with existing data
  - [ ] PUT `/kaban/transactions/{id}`
- [ ] Delete transaction
  - [ ] Confirmation dialog
  - [ ] DELETE `/kaban/transactions/{id}`
- [ ] Analytics chart
  - [ ] Fetch `GET /kaban/stats/category`
  - [ ] Pie or bar chart (Chart.js/Recharts)
  - [ ] Click slice → Filter transactions
  - [ ] Empty state handling
- [ ] Mobile optimization
  - [ ] Categories as drawer/modal
  - [ ] FAB for add transaction
  - [ ] Swipe actions for edit/delete
- [ ] Loading states (skeletons)
- [ ] Empty states (no transactions)
- [ ] Error handling (toasts, retry)
- [ ] Optimistic updates (add/edit/delete)

### Phase 3: Ipon Tracker (Week 4)
- [ ] Create `/pera/ipon` route (or refactor existing)
- [ ] Goals list
  - [ ] Fetch `GET /ipon/goals`
  - [ ] Display goal cards with progress bars
  - [ ] Calculate progress percentage
- [ ] Create goal modal
  - [ ] Form: name, target amount, target date
  - [ ] POST `/ipon/goals`
- [ ] Add deposit modal
  - [ ] Form: amount, notes
  - [ ] POST `/ipon/transactions`
- [ ] Goal transactions history modal
  - [ ] Fetch `GET /ipon/goals/{id}/transactions`
  - [ ] Display deposits list
- [ ] Edit/Delete goal (frontend only for now)
- [ ] Mobile optimization
- [ ] Empty states

### Phase 4: Utang Tracker (Week 5)
- [ ] Create `/pera/utang` route
- [ ] Move from Tulong module navigation
- [ ] Debts list
  - [ ] Fetch `GET /utang/debts`
  - [ ] Display debt cards
  - [ ] Show overdue badge
  - [ ] Calculate total unpaid
- [ ] Create debt modal
  - [ ] Form: debtor name, amount, due date, notes
  - [ ] POST `/utang/debts`
- [ ] Mark as paid
  - [ ] Confirmation dialog
  - [ ] PUT `/utang/debts/{id}` with status: "paid"
- [ ] Generate AI message modal
  - [ ] Form: debtor name, amount, tone selector
  - [ ] POST `/utang/generate-message`
  - [ ] Display generated message
  - [ ] Copy to clipboard button
- [ ] Edit debt modal
- [ ] Filter: All / Unpaid / Overdue
- [ ] Mobile optimization
- [ ] Empty states

### Phase 5: AI Financial Advisor (Week 6)
- [ ] Create `/pera/ai-advisor` route
- [ ] AI tools hub layout
- [ ] Loan Analyzer
  - [ ] Input form: monthly income, loan details
  - [ ] Integrate with existing Loan Calculator
  - [ ] POST `/analyze-loan`
  - [ ] Display AI analysis (markdown rendering)
  - [ ] Color-code verdict
  - [ ] Copy analysis button
- [ ] Spending Insights placeholder (Coming Soon)
- [ ] Pro-only enforcement
- [ ] Mobile optimization

### Phase 6: Polish & Testing (Week 7)
- [ ] Add loading skeletons (all pages)
- [ ] Empty states (all lists)
- [ ] Error handling (toasts, retry buttons)
- [ ] Optimistic updates (Kaban transactions)
- [ ] Caching with React Query or SWR
- [ ] Accessibility (keyboard nav, ARIA labels)
- [ ] Mobile responsive testing (all screens)
- [ ] Cross-browser testing
- [ ] E2E tests (Cypress/Playwright)
  - [ ] Kaban CRUD flow
  - [ ] Ipon create goal + deposit
  - [ ] Utang record + generate message
  - [ ] Loan analyzer flow
- [ ] Performance optimization
  - [ ] Code splitting (lazy load routes)
  - [ ] Image optimization
  - [ ] Bundle size analysis
- [ ] Analytics tracking (page views, button clicks)
- [ ] User testing & feedback

---

## Tech Stack Recommendations

### UI Framework
- **React** (with TypeScript preferred)
- **Next.js** (if SSR/SSG needed)
- **Vue.js** (alternative)

### UI Libraries
- **Tailwind CSS** (utility-first styling)
- **Chakra UI** or **Material UI** (component library)
- **HeadlessUI** (unstyled accessible components)

### Charts
- **Chart.js** with `react-chartjs-2`
- **Recharts** (React-specific)
- **ApexCharts** (feature-rich)

### Forms & Validation
- **React Hook Form** (performance)
- **Zod** or **Yup** (schema validation)

### HTTP & State Management
- **Axios** (HTTP client)
- **TanStack Query (React Query)** (caching, optimistic updates)
- **Zustand** or **Context API** (global state)

### Date Handling
- **date-fns** (lightweight)
- **Day.js** (Moment.js alternative)
- **react-datepicker** (date picker component)

### Utilities
- **clsx** or **classnames** (conditional CSS classes)
- **react-hot-toast** (toast notifications)
- **react-modal** (accessible modals)

---

## Design Guidelines

### Colors
- **Income (Kita):** Green (`#10B981`, `#059669`)
- **Expense (Gastos):** Red (`#EF4444`, `#DC2626`)
- **Balance Positive:** Green
- **Balance Negative:** Red
- **Neutral:** Gray (`#6B7280`)
- **Pro Badge:** Gold/Yellow (`#F59E0B`)
- **Locked Feature:** Gray + Lock icon

### Typography
- **Title:** 24-32px, Bold
- **Subtitle:** 14-16px, Regular
- **Card Heading:** 18-20px, Semi-bold
- **Body Text:** 14-16px, Regular
- **Amount:** Monospace font (for alignment)

### Spacing
- **Card Padding:** 16-24px
- **Grid Gap:** 16-24px
- **Section Margin:** 32-48px

### Icons
- Use emoji for categories (default)
- Optional: Use icon library (Heroicons, Lucide)

---

## Mobile Optimization

### Breakpoints
- **Mobile:** < 640px (1 column)
- **Tablet:** 640px - 1024px (2 columns)
- **Desktop:** > 1024px (3-4 columns)

### Mobile-Specific Features
- Floating Action Button (FAB) for quick add
- Bottom navigation bar (optional)
- Swipe gestures (swipe left to delete)
- Pull-to-refresh
- Collapsible sections (categories, filters)
- Sticky header (month selector)

---

## Security & Performance

### Security
- Never expose JWT tokens in URLs
- Use HTTPS for all API calls
- Sanitize user input (XSS prevention)
- Rate limiting (prevent spam)
- Logout on 401/403 errors

### Performance
- Lazy load routes (code splitting)
- Paginate or virtualize long lists
- Debounce search inputs
- Optimize images (WebP format)
- Cache API responses (React Query)
- Prefetch dashboard data on login

---

## Future Enhancements (Post-Launch)

### Kaban
- [ ] Export to CSV/Excel
- [ ] Recurring transactions (auto-add monthly bills)
- [ ] Budget alerts (notify when exceeding category budget)
- [ ] Receipt upload (OCR with AI)
- [ ] Multi-currency support

### Ipon
- [ ] Interest calculator (savings with interest)
- [ ] Goal milestones (celebrate 25%, 50%, 75%)
- [ ] Shared goals (family savings)

### Utang
- [ ] Payment reminders (auto-send on due date)
- [ ] Payment history (track partial payments)
- [ ] Recurring debts (monthly utilities)

### AI Advisor
- [ ] Spending Insights (analyze patterns)
- [ ] Budget Recommendations
- [ ] 13th Month Planner
- [ ] Padala Optimizer (remittance planner)
- [ ] Financial Health Score

### General
- [ ] Dark mode
- [ ] Multi-language (English, Tagalog)
- [ ] Notifications (push, email)
- [ ] Data backup/restore
- [ ] Social sharing (achievements, goals)

---

## Support & Documentation

### User Help
- Add tooltips for Pro features
- "?" icon with feature explanations
- Tutorial/onboarding for first-time users
- FAQ section

### Developer Documentation
- API changelog (track backend updates)
- Component Storybook (UI component library)
- README with setup instructions
- Contribution guidelines

---

## Contact & Feedback

For questions or clarifications on this requirements document:
- Backend API Docs: `https://kaibigan-api.vercel.app/docs` (FastAPI auto-generated)
- Issues: GitHub Issues (backend repo)
- Updates: This document will be updated as features evolve

---

**Version History:**
- **v1.0** (Nov 15, 2025): Initial requirements document with all clarifications

---

**Ready to implement!** Copy this file to your frontend repo and start building. 🚀
