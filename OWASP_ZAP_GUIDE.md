# 🛡️ OWASP ZAP Security Scan Guide

**Last Updated:** November 23, 2025
**Target:** KaibiganGPT API

---

## 1. What is OWASP ZAP?

OWASP ZAP (Zed Attack Proxy) is a free, open-source penetration testing tool. It acts as a "man-in-the-middle" proxy between your browser/tests and your API, intercepting and inspecting messages, and then actively attacking the API to find vulnerabilities.

**Goal:** Find security holes like SQL Injection, XSS, Broken Access Control, and Security Misconfigurations before hackers do.

---

## 2. Installation

1. **Download:** [OWASP ZAP](https://www.zaproxy.org/download/) (Windows Installer).
2. **Install:** Run the installer. You may need Java installed (it will prompt you if missing).

---

## 3. Configuration for API Scanning

Since we are scanning a **REST API** (not a website with HTML forms), we need to tell ZAP how to talk to our API.

### Step 1: Get your OpenAPI (Swagger) Definition
ZAP works best if you feed it your OpenAPI schema.
1. Run your FastAPI backend locally:
   ```powershell
   uvicorn main:app --reload
   ```
2. Go to `http://127.0.0.1:8000/openapi.json`.
3. Save this JSON content as `openapi.json` on your desktop.

### Step 2: Import into ZAP
1. Open OWASP ZAP.
2. In the menu, go to **Import** -> **Import an OpenAPI definition from a local file**.
3. Select your `openapi.json`.
4. **Target URL:** Ensure it points to your running local instance (`http://127.0.0.1:8000`) or your staging URL.
   *Recommendation: Scan LOCALLY first to avoid taking down your production server.*

---

## 4. Running the Scan

### Phase 1: Passive Scan (Safe)
ZAP automatically passively scans all traffic it sees.
1. After importing the definition, you will see your API endpoints in the "Sites" tree on the left.
2. Look at the **Alerts** tab at the bottom.
3. Fix any "High" or "Medium" alerts (e.g., missing security headers, cookie flags).

### Phase 2: Active Scan (Aggressive)
**⚠️ WARNING:** This sends thousands of malicious requests. Do NOT run this against Production unless you are ready for downtime.

1. Right-click on your API host in the "Sites" tree (e.g., `http://127.0.0.1:8000`).
2. Select **Attack** -> **Active Scan**.
3. **Policy:** Default Policy is fine.
4. Click **Start Scan**.

---

## 5. Interpreting Results

Go to the **Alerts** tab.

### Common False Positives to Ignore:
- **"SQL Injection" on 500 Errors:** Sometimes ZAP thinks a 500 error means SQLi. Check your logs. If it's just a Pydantic validation error, it's safe.
- **"Path Traversal":** If you don't serve files, this is usually noise.

### Critical Issues to Fix:
- **SQL Injection (Confirmed):** If the response time changes significantly or data leaks.
- **XSS (Reflected):** If you return user input without escaping (less likely in JSON APIs).
- **Sensitive Data Exposure:** If stack traces are returned in 500 errors (Ensure `debug=False` in prod).

---

## 6. Authenticated Scanning (Advanced)

Your API requires a Bearer Token. ZAP needs this token to scan protected endpoints.

1. **Get a valid JWT:** Log in to your app and copy the `access_token`.
2. **Configure ZAP Replacer:**
   - Go to **Options** (Gear icon) -> **Replacer**.
   - Add a new rule:
     - **Description:** Auth Header
     - **Match Type:** Request Header (will add if missing)
     - **Match String:** Authorization
     - **Replacement String:** `Bearer <YOUR_ACTUAL_JWT_TOKEN>`
     - **Enable:** Check.
3. Now run the Active Scan again. ZAP will attach this header to every request.

---

## 7. Reporting

1. Go to **Report** -> **Generate Report**.
2. Save as HTML.
3. Review with the team.
