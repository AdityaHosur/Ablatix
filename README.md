
# Ablatix
Ablatix is an enterprise-grade AI framework designed to automate global media compliance. Using a combination of Multimodal AI and Agentic RAG, Ablatix doesn't just find legal violations—it systematically "ablates" (fixes/remediates) them in real-time to protect creators and global company's marketing team from international fines and legal action.

---

## Features of this project

**1. Multimodal AI Safety Engine**

The engine uses Multimodal Intelligence to analyze video pixels and audio waveforms simultaneously for 100% scanning accuracy. It performs frame-by-frame visual audits and neural audio transcriptions to detect violations that standard text filters miss.

**2. Agentic RAG Policy Sync**

This "living brain" uses an Agentic Framework to autonomously scrape and monitor global media councils for real-time rule changes. It feeds these updates into a dynamic vector database, allowing the AI to adapt to new laws in India, UAE, and the USA instantly.

**3. Surgical AI Remediation (Ablation)**

Utilizing MoviePy, Ablatix surgically "ablates" or fixes non-compliant segments by blurring visuals or muting restricted audio at exact timestamps. This generates a "compliance-ready" export that removes legal risks while preserving the creative integrity of your media.

**4. Financial Impact Analytics**

This feature translates technical safety into Business ROI by tracking a Brand Safety Score and estimating potential legal fines avoided. By quantifying liabilities saved based on 2026 global benchmarks, Ablatix proves its value as a mission-critical financial asset.

---

## Target Users

**1. Content Creators and social media influencers**

**2.Marketing teams of global companies and new age brands**

Ablatix is an enterprise grade application which serves companies and content creators and saves them from uploading content which might have violations and  can affect their buisness. 

---

## Need of this project

Content creators and global brands have to keep posting on social media platforms to interact with their audience.If any of the post violates the country guidlines or social media guidlines or has inappropriate content then it can lead to serious legal consequences and loss of reputation in the market.So there is a need of an autonomous system that checks if the post violates guidlines or not and if it violates,then remediates(fixes) it.Now the posts are ready to upload on social media platforms !!!

---
## 📌 Scope of Violation Detection

Our system focuses on detecting major content violations based on guidelines extracted from YouTube, Instagram, and X. The following key categories are covered:

### 1. Hate Speech & Discrimination
- Content attacking or demeaning individuals/groups based on race, religion, gender, nationality, or identity.  
- Promotion of exclusion, superiority, or discrimination.  

### 2. Violence & Harmful/Dangerous Content
- Physical violence, threats, or encouragement of harm.  
- Dangerous acts, challenges, or activities that may cause injury. 

### 3. Harassment, Bullying & Abuse
- Targeted harassment, abusive language, or repeated harmful behavior toward individuals or groups.  

### 4. Nudity & Sexual Content
- Explicit sexual content or inappropriate nudity.  
- Content involving sexual exploitation or unsafe exposure.  

### 5. Self-Harm & Suicide Content
- Promotion, encouragement, or depiction of self-harm or suicide.  
- Harmful eating disorder-related content.  

### 6. Misinformation & Deceptive Content
- False or misleading information that can cause real-world harm (e.g., health, elections).  

### 7. Spam, Scams & Fraud
- Phishing, scams, deceptive practices, or misleading content intended to exploit users.  

### 8. Illegal Activities & Regulated Goods
- Promotion or sale of illegal goods such as drugs, weapons, or restricted products.  
- Encouragement of unlawful activities. 

### 9. Privacy Violations
- Sharing personal or sensitive information without consent (e.g., doxxing).

### 10. Impersonation & Fake Identity
- Pretending to be individuals, organizations, or brands with intent to mislead.

---

## 🧠 Note
These categories are derived from real-world platform policies and represent the most critical and commonly enforced content violations across major social media platforms. The system focuses on high-impact violations to enable effective and scalable detection.

---

## Team Members

- Aditya Hosur (1MS22CS016)
- Atharva Manchalkar (1MS22CS037)
- Dheer N Raijada (1MS22CS167)
- Manvith A Rai (1MS23CS407)

---

## Build Steps

Follow these steps to build and run the project locally.

**Backend:**
- Create and activate a Python virtual environment and install requirements:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

- Run the backend (from the repository root or inside `backend`):

```powershell
cd backend
uvicorn main:app --reload
```

**Frontend:**
- Install dependencies and build the frontend:

```bash
cd frontend
npm install
npm run build
```

- Run frontend in development mode:

```bash
npm run dev
```

Notes: On Windows prefer the PowerShell commands shown; on macOS/Linux use the corresponding shell variants.

## Environment variables

Add required API keys and runtime flags to the backend and frontend environment files. Do NOT commit secrets to source control.

- **Backend (.env)**: create `backend/.env` with the following keys (example):

```env
PAGEINDEX_API_KEY="<your_pageindex_api_key>"
OLLAMA_API_KEY="<your_ollama_api_key>"
GROQ_API_KEY="<your_groq_api_key>"    # optional, if using Groq
GEMINI_API_KEY="<your_gemini_api_key>" # optional, Google/Gemini
OLLAMA_MODEL="gemma4:31b-cloud"       # optional override
ENABLE_REMEDIATION=true                # true/false
BLUR_STRENGTH=51                       # integer (gaussian kernel size)
USE_BEEP_FOR_AUDIO=true                # true/false
```

See an example `.env` already present at [backend/.env](backend/.env#L1-L4).

- **Frontend (.env.local)**: for Next.js create `frontend/.env.local` (or use your deployment's env settings):

```env
NEXT_PUBLIC_BACKEND_URL="http://localhost:8000"  # URL reachable from the browser
BACKEND_URL="http://127.0.0.1:8000"              # used by server-side/frontend proxies
```

Notes:
- Use `NEXT_PUBLIC_` prefixed variables for values that must be available in the browser.
- Keep API keys and secrets in the backend only; do not expose them as `NEXT_PUBLIC_` values.
- Add `.env`/`.env.local` to `.gitignore` if not already ignored.





