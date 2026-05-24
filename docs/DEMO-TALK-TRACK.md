# Demo Talk Track — Business Head Walkthrough

A 15-minute live demo of the YES BANK Architecture Diagram Analyzer (Demo v1).

This document has four sections:

1. **The talk track** — exactly what to say, in order, with timing
2. **What NOT to say** — common engineering-jargon traps
3. **Questions you'll get + the right answers** — prepared responses
4. **The 1-pager handout** — what to print and leave behind
5. **Day-of logistics** — pre-meeting checklist

---

## 1 · The Talk Track (15 minutes, hand-on-mouse)

Read it once aloud before the meeting so it sounds natural, not rehearsed.

### 0:00 — Open with the problem, not the product (1 minute)

> "Today, when an architect at the bank designs a new application, a security review happens manually. Someone opens the diagram, eyeballs every component, traces the flows in their head, and checks each one against a mental list of bank controls. It takes 2–3 days, sometimes a week. Different reviewers reach different conclusions on the same diagram.
>
> What I'm about to show you does that review in **under a minute**, applies the same eight controls **every single time**, and produces a signed report we can hand to a regulator."

**Stop. Let them ask "how?" or just nod.**

---

### 1:00 — One sentence on architecture before the demo (30 seconds)

> "The way we built it: the AI does the perception — looking at the diagram and identifying components. Every security decision after that is plain code we wrote, version-controlled, and auditable. The AI can be swapped tomorrow; the compliance rules can't drift."

Don't go deeper here. They'll trust you because the demo will show it.

---

### 1:30 — Start the demo from the login screen (1 minute)

Show the browser. Frontend is at the App Service URL.

> "This is a YES BANK internal tool. It's behind the bank's Entra ID — for the demo I'm using a sample login."

Sign in as `VRC2106734 / yesbank@123`. Land on the Upload page.

> "I'm signed in as a Security Architect. Notice the top — my employee ID is attached. Everything I do from here is audit-logged."

---

### 2:30 — The "what you do" half — upload a diagram (1.5 minutes)

> "An architect comes here with their proposed architecture. They give it a title — let's say *'eBranch VNet Production'*."

Type the title.

> "Then they drop in the diagram. The tool accepts PNGs, JPGs, PDFs from Visio or Lucid, even a phone photo of a whiteboard."

Drop a real diagram (the eBranch one you tested with, or a clean Azure 3-tier sample).

> "And we click Start Review."

Click. The 5-stage progress bar appears.

> "While that runs — about 12 seconds — let me tell you what's happening behind the scenes."

---

### 4:00 — The "what's happening" half — explain the 5 stages (1.5 minutes)

The progress bar is visible. Talk to it.

> "Five stages. The first is image cleanup — standardizing whatever format the architect uploaded. The second is OCR, using Azure AI Document Intelligence to read every label on the diagram. The third — and this is the only AI step — is GPT-4o looking at the image and the OCR text, and telling us *'here are the components, here are the connections, here are the trust zones'*.
>
> The last two stages are our own deterministic code. We map the AI's free-text labels to canonical bank-approved service names using a taxonomy file. We classify every connection as crossing a trust boundary or not. And we evaluate eight named security controls."

Pause until the progress bar finishes and the analysis result loads.

---

### 5:30 — The headline view — explain what they're looking at (2 minutes)

The Results page is now showing. Walk them through it like a guided tour.

> "This is the analysis. At the top — the ARC number is `ARC-202605-008`. That's permanent. Every analysis the bank ever runs gets a unique number, traceable to the architect who submitted it.
>
> The four cards: 7 components, 5 connections, 4 trust zones, 6 of 8 compliance checks passing.
>
> Confidence 87% — that's how sure the system is. Anything under 60% gets flagged for human review. Above 85% with no critical fails goes through 'auto-review recommended'. This one's there."

Point to the diagram on the screen.

> "The original diagram on the left, with our annotations. Every component has a bounding box colored by trust zone — red for external, green for internal, blue for restricted. Every arrow is colored by its flow type."

---

### 7:30 — The Journeys tab — the closer (2 minutes)

> "But this is the bit I'm most proud of."

Click the **Journeys** tab.

> "A network engineer thinks in terms of 'how many flows go where.' An architect or a regulator thinks in terms of stories: *'how does a customer reach the trade database?'* That's a user journey.
>
> The system walks the diagram from every user entry point to every meaningful destination — every database, every identity provider, every secrets vault — and turns each path into a numbered narrative."

Point at the first journey.

> "Journey 1: *Customer to Murex DB*. The customer comes in from the internet, hits Front Door, gets routed to the App Service, which writes to Murex DB. Four trust zones crossed. End-to-end TLS — every hop encrypted, all green locks. Score 95 — high attention because it touches sensitive data.
>
> Click any journey and the diagram lights up the exact path. Everything else dims out."

Click a journey. The diagram highlights.

> "This is what an architect actually puts on a slide. This is what leadership reads."

---

### 9:30 — Compliance tab — the regulator answer (1.5 minutes)

Click **Compliance** tab.

> "Eight controls, every analysis. Each one shows pass, fail, or warn. If it fails, you see exactly which component or connection caused it."

Point at a finding.

> "Take this one — *'Private endpoints for PaaS data services'*. It warned because there's a database without a private endpoint. We know which database. We know which architect submitted the diagram. We know which review.
>
> The controls themselves live in a JSON file. A compliance officer can read it without reading any code. When the bank's security policy changes, we add a rule. We don't change Python. We don't redeploy."

---

### 11:00 — The Chat Bot (1 minute)

Click **Chat Bot** in the sidebar. Pick the same analysis from the dropdown.

> "If a reviewer wants to dig in, they can talk to the analysis."

Ask: *"How many components are in the restricted zone?"*

> "It answers using the structured JSON we extracted. It will never tell you something that isn't in the diagram. It can't hallucinate a database that doesn't exist, because it doesn't reason from scratch — it reads our findings."

---

### 12:00 — The Admin views — the trust story (1 minute)

Sign out. Sign back in as `ADMIN001`.

The sidebar now has two extra items.

> "If I'm a platform admin, I see two more things."

Click **AI Usage**.

> "Every AI call is tracked — token count, cost in dollars, model fingerprint, who triggered it. So we know exactly what we're spending and on whom. This month so far: a few thousand tokens, costs us pennies."

Click **System logs**.

> "And every API call is logged with timestamp, request ID, employee ID. If something goes wrong, I can replay the exact sequence."

---

### 13:00 — The infrastructure pitch (1 minute)

Stop touching the screen.

> "Deployment-wise: both the API and the UI run inside the bank's Azure tenant, in the South India region. The AI services — GPT-4o and Document Intelligence — have public network access **disabled**. The only entry point is a Private Endpoint inside our VNet. No diagram bytes leave the bank tenant. No prompts leave the bank tenant. Microsoft cannot see what we send."

---

### 14:00 — Close with the ask, not the technology (1 minute)

> "We're ready for a few specific things:
>
> 1. A security architect from your team to do a sample review using this tool, and tell us where the AI got it wrong or right.
> 2. Permission to feed our existing diagram library through it — we believe we can produce signed reviews on 200+ legacy applications in a week.
> 3. If you want, a side-by-side comparison: take a diagram that's been manually reviewed, run it through here, and we'll show you what the system caught and missed.
>
> The whole thing took one engineer about three weeks. We can ship more in the same time if there's appetite."

**Stop. Wait for them to talk.**

---

## 2 · Things to NOT Say

These are common mistakes that lose a business head's attention.

| ❌ Don't say | ✅ Say instead |
|---|---|
| "We use FastAPI with Pydantic and structlog" | "It's a Python backend designed to be auditable" |
| "Vector embeddings" / "RAG" / "Knowledge graph" | "The chat answers from the structured analysis we already produced" |
| "Token limits" / "context window" | "Cost is pennies per analysis" |
| "Monorepo with Turborepo and npm workspaces" | "It's one codebase that ships frontend and backend together" |
| "We have 65 backend tests" | "Every security rule is unit-tested" |
| "The compliance evaluator uses generic check functions" | "Eight controls in one JSON file the compliance team can read" |
| "We use OAuth bearer tokens with 8-hour TTL" | "Every user signs in with their employee ID" |
| "VNet integration with private DNS zones" | "All traffic stays inside the bank's network" |

The business head doesn't care about the *how*. They care about: **is this safe**, **is this auditable**, **what does it save us**, **what does it cost**.

---

## 3 · Questions You'll Get + The Right Answers

Prepare these. They **will** come up.

### "What happens if the AI makes a mistake?"

> "The AI never makes the final call. It identifies what's on the diagram. Every security decision is made by deterministic code we wrote. If the AI mis-identifies a component, the worst case is a compliance rule fires on the wrong target — and we catch that because the system tells us which component caused the verdict, and a reviewer can confirm. Confidence below 85% is automatically routed to human review."

### "Is this data going to OpenAI?"

> "No. We use **Azure** OpenAI, inside the bank's tenant, with public network access disabled. Microsoft cannot see our prompts or our diagrams. They host the model on infrastructure we have a private connection to. There's also a data-handling agreement that says they cannot train on our data."

### "How much does it cost per analysis?"

> "About 4,000 tokens per analysis on the AI side — roughly $0.02 in compute. Infrastructure is a single small App Service plan, around ₹3,000/month for the demo. At bank scale — say 1,000 analyses a month — the total runtime cost would be under ₹10,000/month."

### "Why this instead of buying something?"

> "Three reasons. First, it lives inside our tenant — no diagram bytes leave YES BANK. Second, the compliance rules are ours, not a vendor's interpretation. We can change them in minutes without a contract renegotiation. Third, the cost is a tenth of what an external vendor would charge per analysis, and the data stays ours."

### "Who reviews the AI when it changes?"

> "The model is pinned. We test every analysis against our committed test diagrams before we roll forward to a new model snapshot. If GPT-4o changes — and it has — we know within a day, because the same diagrams produce different results. The compliance verdicts don't change because that's deterministic code, not AI."

### "What if the AI gets too expensive?"

> "We can run the whole pipeline in fallback mode using OpenCV — no AI calls — for free. Less accurate, but works."

### "Can we extend it to do XYZ?"

Don't promise. Say:

> "Probably. The taxonomy of services is JSON. The compliance rules are JSON. The journey scorer is configurable. The whole architecture is built for it to be extended. Let's pick one specific use case after this meeting."

---

## 4 · The 1-Pager Handout

Print on a single sheet. Hand it to them at the end.

```
╔══════════════════════════════════════════════════════════════════════╗
║          YES BANK · Architecture Diagram Analyzer (Demo v1)          ║
╚══════════════════════════════════════════════════════════════════════╝

WHAT IT DOES
  • Upload a cloud architecture diagram (PNG, JPG, PDF, Visio export).
  • In ~12 seconds, get back:
      - Every component identified with bank-canonical names
      - Every connection labelled with protocol & encryption status
      - User journeys traced from entry actor to data sinks
      - Pass/fail/warn against the bank's 8 mandatory security controls
      - A printable report ready for review

WHO IT'S FOR
  Security architects, application owners, compliance reviewers,
  the bank's enterprise architecture team.

WHAT MAKES IT DEFENSIBLE TO A REGULATOR
  • AI does perception only. Every security decision is deterministic
    code we wrote, version-controlled, unit-tested.
  • All eight compliance controls live in a single JSON file that a
    non-engineer can read.
  • Every analysis has a unique ARC number (e.g. ARC-202605-008).
  • Every API call is logged with timestamp, request-id, and the
    employee_id that triggered it. Admins can replay any incident.
  • All AI traffic stays inside YES BANK's Azure tenant via Private
    Endpoints. No diagram leaves the bank.

WHAT WAS BUILT
  • Backend: Python FastAPI, 65 unit tests, mock fallback for offline.
  • Frontend: React + TypeScript, Yes Bank brand, print-ready report.
  • Auth: Employee ID + password (sample). Path to Entra ID is one
    module change.
  • Observability: Daily-rotated structured JSON logs, AI token usage
    dashboard, per-employee attribution.

INFRASTRUCTURE (Azure, South India region)
  • 1 × App Service (Python 3.12)         — backend
  • 1 × App Service (Node 20, static)     — frontend
  • 1 × VNet                              — bank-private network
  • 2 × Private Endpoints                 — Azure OpenAI + Doc Intel
  • 1 × Storage (Files)                   — analyses + logs persistence
  • Azure OpenAI (existing): gpt-4o
  • Azure Document Intelligence (existing): prebuilt-layout

COST
  • Infrastructure: ~₹3,000 / month for the demo
  • Per analysis: ~$0.02 in AI tokens (mostly Document Intelligence)
  • Existing AI service usage is already on the bank's contract

DELIVERY EFFORT
  • Three weeks, one engineer.
  • Reproducible via single Git repo. Two GitHub workflows deploy on push.

WHAT'S NEXT (in priority order)
  1. Pilot with 5 real applications. Validate accuracy against
     manual reviews.
  2. Bulk-load existing diagram library. Produce signed reviews on
     ~200 legacy apps.
  3. Connect to bank's CMDB so each analysis links to the actual
     application record.
  4. Replace sample auth with Entra ID / OAuth (1 module change).
  5. Add chat-to-graph: "show me every Tier-1 app that depends on
     this database."

KEY CONTACT
  Vasu Reddy (VRC2106734) · Security Architect
  vasu.reddy@yesbank.in
```

---

## 5 · Day-of Logistics

### Pre-meeting setup (30 minutes before)

- [ ] Open three browser tabs in advance, all logged in:
  - Tab 1: Upload page (so you don't have to navigate)
  - Tab 2: A pre-run analysis with good findings (in case your live upload fails)
  - Tab 3: Admin view as ADMIN001 (so the switch is fast at the end)
- [ ] Have a "demo diagram" ready that you know produces a clean result. Test it 30 minutes before. Don't gamble on a fresh diagram.
- [ ] Have the OpenCV / mock fallback URL ready in case Azure misbehaves. The demo continues. Don't let cloud weather sink the meeting.
- [ ] Print 2 copies of the 1-pager. One for the business head, one as your own cheat sheet.
- [ ] Time the demo on your own first. Aim for 13 minutes — leave 2 minutes of headroom for questions.
- [ ] Have your laptop's IP whitelisted in AOAI if you're showing from your machine (it's currently set to Disabled).

### In the meeting

- [ ] Start with the problem, not the product
- [ ] Demo flows in this order: **Upload → Results → Journeys → Compliance → Chat Bot → Admin views**
- [ ] **Pause after the Journeys explanation** — that's the "wow" beat
- [ ] Close with the **ask** (pilot + permission + comparison)
- [ ] Hand them the 1-pager and stop talking

---

## TL;DR

This is a **show-and-ask** meeting:

- The **screen** does the talking.
- The **1-pager** is the artifact they keep.
- Your **closing ask** is what determines whether you get budget and headcount for the next sprint.

Good luck.
