# Requirement Change Request (RCR-001)
## GitHub-Based Publishing Architecture for Debate Results

---

### Document Control

| Field | Value |
|-------|-------|
| **RCR ID** | RCR-001 |
| **Project** | Blind Debate Adjudicator (`debate_system`) |
| **Title** | Migrate from Local-Hosted Server to GitHub-Based Publishing with Email Submission |
| **Date** | 2026-04-13 |
| **Status** | Draft |
| **Priority** | High |
| **Requested By** | Product Owner |

---

### 1. Executive Summary

Replace the current local-PC-hosted Flask server architecture with a **decentralized, GitHub-centric publishing model**. In the new architecture:

- **GitHub** serves as the canonical publishing platform for consolidated debate results.
- The **frontend** becomes a static, offline-capable client that reads results from GitHub, caches them locally, and renders the UI.
- **Email** becomes the sole submission channel from the frontend to the server.
- A **server-side email processor** ingests incoming emails, updates the debate state, and publishes consolidated results back to GitHub.

This removes the need for end users to host or connect to a local backend instance.

---

### 2. Current Architecture (Baseline)

```
┌─────────────┐      HTTP/API      ┌─────────────────┐
│  Frontend   │ ◄────────────────► │  Flask Backend  │
│  (Browser)  │   (localhost:5000) │  (Local PC)     │
└─────────────┘                    └─────────────────┘
                                          │
                                    ┌─────┴─────┐
                                    │ SQLite DB │
                                    │ (local)   │
                                    └───────────┘
```

**Limitations:**
- Backend must run continuously on a local PC.
- Frontend requires direct network access to the local server.
- No native offline support or distributed access.

---

### 3. Proposed Architecture (Target)

```
┌─────────────────────────────────────────────────────────────┐
│                        GITHUB                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Public Repository (or GitHub Pages)                │    │
│  │  • consolidated_results.json                        │    │
│  │  • Static frontend assets (optional)                │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS (read-only)
         ┌─────────────────┴─────────────────┐
         │                                   │
┌────────▼────────┐                ┌─────────▼─────────┐
│   Frontend      │                │  Email Processor  │
│   (Browser /    │                │  (Server)         │
│    Desktop)     │                │                   │
│                 │                │  • Polls inbox    │
│ 1. Fetches      │                │  • Parses posts   │
│    results from │                │  • Updates state  │
│    GitHub link  │                │  • Pushes to      │
│ 2. Saves to     │                │    GitHub         │
│    local file   │                │                   │
│ 3. Displays     │                │ 4. Receives       │
│    across pages │                │    emails from    │
│ 5. Submits via  │                │    frontend users │
│    email        │                │                   │
└────────┬────────┘                └───────────────────┘
         │
         │ SMTP / Email API
         ▼
   Destination
   Email Address
```

---

### 4. Functional Requirements

#### FR-1: GitHub as Publishing Platform
- **FR-1.1**: The consolidated debate results (snapshot, topics, facts, arguments, verdict, audits) shall be published as a structured JSON file in a designated GitHub repository.
- **FR-1.2**: The JSON file shall be version-controlled, with each publish creating a new commit for traceability.
- **FR-1.3**: The repository may optionally expose the frontend via GitHub Pages, but the frontend shall not depend on this.

#### FR-2: Frontend Retrieval & Local Caching
- **FR-2.1**: The frontend shall retrieve the consolidated results from a user-configured **GitHub link** (raw file URL or GitHub API endpoint).
- **FR-2.2**: Upon successful retrieval, the frontend shall save the results to a **local file** on the user’s device.
- **FR-2.3**: The frontend shall render all pages (Home, Topics, Facts, Arguments, Verdict, Audits) using the locally cached data.
- **FR-2.4**: The frontend shall provide a manual **"Refresh from GitHub"** control to update the local cache.

#### FR-3: Frontend Submission via Email
- **FR-3.1**: The **New Debate / Post** page shall generate a structured email (or pre-filled `mailto:` link) containing the user’s submission data.
- **FR-3.2**: The email shall be addressed to the **destination email address** registered during setup.
- **FR-3.3**: The email body shall include all required fields: position, topic area, factual premises, inference/conclusion, and optional counter-arguments addressed.
- **FR-3.4**: The frontend shall support both:
  - **Client-side email generation** (`mailto:` link) as a zero-config fallback.
  - **Direct SMTP/API submission** (optional advanced mode) if the user configures email credentials.

#### FR-4: Server-Side Email Processing
- **FR-4.1**: A server-side processor shall monitor the **destination email address** inbox for incoming debate submissions.
- **FR-4.2**: The processor shall parse each email, validate the submission structure, and reject malformed or spam emails.
- **FR-4.3**: Valid submissions shall be ingested into the debate engine (modulation, fact-checking, snapshot generation).
- **FR-4.4**: After processing, the processor shall regenerate the consolidated results and **post (commit/push) the updated JSON to GitHub**.
- **FR-4.5**: The processor shall send an acknowledgment email back to the submitter indicating success or failure with a reason.

#### FR-5: User Setup & Configuration
- **FR-5.1**: During first-run setup, the user shall register:
  1. **GitHub Link**: The URL to the raw consolidated results JSON file (e.g., `https://raw.githubusercontent.com/{owner}/{repo}/{branch}/data/consolidated_results.json`).
  2. **Destination Email Address**: The email address used by the frontend to submit posts and by the server to receive them.
- **FR-5.2**: The setup shall persist these values in the frontend’s local storage or a local config file.
- **FR-5.3**: The setup UI shall validate the GitHub link by attempting a test fetch.

---

### 5. Non-Functional Requirements

#### NFR-1: Offline Capability
- The frontend shall remain fully functional for reading and navigating cached debate data when offline.

#### NFR-2: Security
- **NFR-2.1**: The GitHub repository may be public (for read access) or private (if frontend authentication is implemented later).
- **NFR-2.2**: The server shall authenticate to GitHub using a **Personal Access Token (PAT)** or **GitHub App** credentials stored securely.
- **NFR-2.3**: Email submissions shall be validated (sender whitelist, structure checks, rate limiting) to prevent spam or abuse.

#### NFR-3: Compatibility
- **NFR-3.1**: The new frontend shall reuse the existing page structure (`index.html`, `topics.html`, `facts_t*.html`, etc.) where possible, but data shall be loaded dynamically from the local cache file instead of calling `/api/*` endpoints.
- **NFR-3.2**: If the GitHub link is unreachable, the frontend shall display a graceful degradation message and continue showing the last cached data.

---

### 6. Data Format

The consolidated results published to GitHub shall conform to the existing API response schema, wrapped in a top-level object:

```json
{
  "published_at": "2026-04-13T12:00:00Z",
  "commit_message": "Snapshot #7 - 3 new posts processed",
  "debate": { ... },
  "snapshot": { ... },
  "topics": [ ... ],
  "verdict": { ... },
  "audits": { ... },
  "modulation": { ... }
}
```

---

### 7. Impact Analysis

| Component | Impact | Notes |
|-----------|--------|-------|
| **Frontend** | High | Remove all `fetch('/api/...')` calls to localhost. Replace with local-file reads and GitHub fetch. Add email submission UI. Add setup page. |
| **Backend (Flask)** | Medium | Retain debate engine, scoring, and snapshot logic. Remove HTTP API layer or repurpose it for local admin use only. |
| **Email Processor** | High | New component. Can be a standalone Python daemon/script or serverless function. |
| **GitHub Integration** | High | New component. Requires `PyGithub` or `git` CLI automation for commits. |
| **Database** | Low | SQLite remains the server-side persistence layer; no schema changes required. |
| **Deployment** | High | No more `python start_server.py` for end users. Server operator runs the email processor instead. |

---

### 8. Implementation Notes

1. **Frontend Data Layer**: Create a new JavaScript module `data_bridge.js` responsible for:
   - `loadFromGitHub(url)` → fetch → save to `localStorage` / IndexedDB / local JSON file.
   - `loadFromCache()` → return parsed JSON.
   - `submitByEmail(data)` → generate `mailto:` link or call email API.

2. **Email Processor Module**: Create `backend/email_processor.py` with:
   - IMAP/SMTP polling loop.
   - Parser for structured debate submission emails.
   - Integration with existing `DebateEngine` and snapshot pipeline.
   - GitHub uploader using `PyGithub` or `requests` + GitHub REST API.

3. **GitHub Repository Layout** (suggested):
   ```
   {repo}/
   ├── data/
   │   └── consolidated_results.json
   ├── frontend/
   │   └── (static assets, optional)
   └── .github/
       └── workflows/
           └── (optional CI for validation)
   ```

4. **Setup Flow**: Add `setup.html` as the landing page when no GitHub link is configured.

---

### 9. Acceptance Criteria

- [ ] **AC-1**: A fresh frontend installation, when opened, prompts the user for a GitHub link and destination email address.
- [ ] **AC-2**: After setup, the frontend successfully fetches `consolidated_results.json` from the provided GitHub link and caches it locally.
- [ ] **AC-3**: All existing pages (Home, Topics, Facts, Arguments, Verdict, Audits) render correctly using only the locally cached data, with no `localhost:5000` API calls.
- [ ] **AC-4**: Submitting a post from the frontend produces a correctly addressed email containing all form fields.
- [ ] **AC-5**: The server-side email processor receives the email, parses it, runs it through the debate engine, and pushes an updated `consolidated_results.json` to GitHub within 5 minutes.
- [ ] **AC-6**: The frontend’s "Refresh" control retrieves the newly published results and updates the display.
- [ ] **AC-7**: The frontend remains readable (using the last cached data) when the device is offline.

---

### 10. Open Questions

1. Should the frontend support multiple active debates (multiple GitHub links), or is one link sufficient?
2. Should the email processor run as a long-lived daemon, a cron job, or a serverless function (e.g., AWS Lambda triggered by SES)?
3. Is there a requirement for end-to-end encryption of email submissions?
4. Should the GitHub repository be public by design, or should private repo access be supported from the start?

---

*End of Requirement Change Request*
