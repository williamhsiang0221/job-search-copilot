"""Fictional content for the demo database (see seed_demo.py).

Every company, person and figure here is invented. The candidate is Jordan
Lee, the example profile in profile.example/ — a growth PM from a consumer
fintech app, finishing an MBA, targeting New York.
"""

# --------------------------------------------------------------------------
# Jobs. "past" jobs are roles Jordan already applied to (they anchor the
# similarity search and carry tailored resumes); "open" jobs are new postings
# waiting to be evaluated.
# --------------------------------------------------------------------------

JOBS = [
    # ---- past applications --------------------------------------------
    {
        "kind": "past", "source": "greenhouse", "job_id": "demo-gh-1001",
        "company": "Northwind Pay", "title": "Senior Product Manager, Growth",
        "location": "New York, NY", "workplace": "hybrid", "comp": (165000, 205000), "posted_days_ago": 62,
        "summary": ["The Growth team owns how new customers discover, sign up for and start using Northwind Pay's consumer wallet."],
        "responsibilities": [
            "Own the sign-up and first-week activation funnel for the consumer wallet.",
            "Define growth metrics and run a roadmap of experiments with design, engineering and data science.",
            "Partner with marketing on referral and lifecycle programs that drive acquisition.",
            "Translate funnel analysis into prioritized product bets and communicate results to leadership.",
        ],
        "qualifications": [
            "4+ years of product management experience, ideally on growth or onboarding.",
            "Strong SQL and experimentation skills; comfortable designing A/B tests.",
            "Experience with consumer mobile products at scale.",
            "MBA or equivalent experience preferred.",
        ],
    },
    {
        "kind": "past", "source": "ashby", "job_id": "demo-ab-2001",
        "company": "Lumen Health", "title": "Product Manager, AI Care Experiences",
        "location": "New York, NY", "workplace": "hybrid", "comp": (150000, 185000), "posted_days_ago": 55,
        "summary": ["You will lead the product work that brings safe, useful AI assistance into every patient conversation on Lumen Health."],
        "responsibilities": [
            "Lead discovery and delivery of LLM-powered features for patient messaging.",
            "Define evaluation criteria and quality bars for AI responses with clinical partners.",
            "Run pilots with care teams and scale what works across the platform.",
            "Track adoption, accuracy and time saved, and report outcomes to executives.",
        ],
        "qualifications": [
            "3+ years in product management, with at least one shipped AI or ML feature.",
            "Experience designing evaluations for model quality.",
            "Comfort working with regulated or sensitive data.",
            "Excellent written communication.",
        ],
    },
    {
        "kind": "past", "source": "lever", "job_id": "demo-lv-3001",
        "company": "Cobalt Ledger", "title": "Product Analytics Lead",
        "location": "Remote - US", "workplace": "remote", "comp": (145000, 175000), "posted_days_ago": 48,
        "summary": ["Product Analytics at Cobalt Ledger makes sure every product decision for our small-business accounting app is grounded in data."],
        "responsibilities": [
            "Build the metrics framework and dashboards for activation, retention and revenue.",
            "Design and analyze experiments, including holdouts and incrementality tests.",
            "Model churn and expansion to guide pricing and lifecycle programs.",
            "Partner with product managers to size opportunities and shape roadmaps.",
        ],
        "qualifications": [
            "5+ years in product or growth analytics.",
            "Expert SQL and Python; experience with causal inference.",
            "Experience presenting to senior stakeholders.",
        ],
    },
    {
        "kind": "past", "source": "greenhouse", "job_id": "demo-gh-1002",
        "company": "Fernway Travel", "title": "Lifecycle Marketing Manager",
        "location": "New York, NY", "workplace": "onsite", "comp": (125000, 150000), "posted_days_ago": 40,
        "summary": ["Lifecycle Marketing at Fernway Travel keeps travelers coming back between trips through personalized email, push and in-app journeys."],
        "responsibilities": [
            "Own email, push and in-app journeys from onboarding to win-back.",
            "Build audience segments and test offers, timing and creative.",
            "Measure incremental impact of campaigns with holdout groups.",
        ],
        "qualifications": [
            "3+ years in lifecycle or CRM marketing.",
            "Hands-on experience with a customer engagement platform.",
            "Analytical mindset; comfortable with SQL.",
        ],
    },
    {
        "kind": "past", "source": "ashby", "job_id": "demo-ab-2002",
        "company": "Sundial AI", "title": "AI Product Strategist",
        "location": "New York, NY", "workplace": "hybrid", "comp": (155000, 190000), "posted_days_ago": 33,
        "summary": ["Sundial AI's strategy team helps enterprise customers turn our agent platform into measurable business outcomes."],
        "responsibilities": [
            "Scope AI agent deployments with enterprise customers and define success metrics.",
            "Run pilots, build the business case and present results to customer executives.",
            "Feed customer insights back into the product roadmap.",
        ],
        "qualifications": [
            "4+ years in product, strategy or consulting.",
            "Hands-on experience with LLMs and prompt design.",
            "Strong executive communication.",
        ],
    },
    {
        "kind": "past", "source": "greenhouse", "job_id": "demo-gh-1003",
        "company": "Pinecrest Commerce", "title": "Product Manager, Personalization",
        "location": "New York, NY", "workplace": "hybrid", "comp": (160000, 195000), "posted_days_ago": 26,
        "summary": ["The Personalization team decides what each shopper sees first across Pinecrest Commerce's marketplace."],
        "responsibilities": [
            "Own recommendation and ranking surfaces across home, search and email.",
            "Work with ML engineers to define model objectives and launch experiments.",
            "Balance shopper relevance with merchant and marketplace goals.",
        ],
        "qualifications": [
            "4+ years of product management, including recommendation or ranking systems.",
            "Experience running large-scale A/B tests.",
            "Familiarity with marketplace dynamics.",
        ],
    },
    # ---- open postings --------------------------------------------------
    {
        "kind": "open", "source": "greenhouse", "job_id": "demo-gh-1101",
        "company": "Orbitly", "title": "Senior Product Manager, Activation",
        "location": "New York, NY", "workplace": "hybrid", "comp": (170000, 210000), "posted_days_ago": 2,
        "summary": ["The Activation team makes sure every new Orbitly creator publishes their first project within a day of signing up."],
        "responsibilities": [
            "Own the new-user journey from sign-up to first published project.",
            "Run a high-velocity experimentation program with design and engineering.",
            "Use funnel and cohort analysis to find the biggest activation drop-offs.",
            "Partner with lifecycle marketing on onboarding messaging.",
        ],
        "qualifications": [
            "5+ years of product management, with growth or onboarding ownership.",
            "Strong experimentation and SQL skills.",
            "Experience with consumer subscription products.",
        ],
    },
    {
        "kind": "open", "source": "ashby", "job_id": "demo-ab-2101",
        "company": "Kestrel Mobility", "title": "Product Manager, AI Assistant",
        "location": "New York, NY", "workplace": "hybrid", "comp": (155000, 190000), "posted_days_ago": 1,
        "summary": ["You will own Kestrel Mobility's in-app AI assistant, which helps riders plan trips and resolve issues without waiting for support."],
        "responsibilities": [
            "Define the roadmap for the rider-facing AI assistant.",
            "Set up evaluation of answer quality and resolution rate with data science.",
            "Pilot new assistant capabilities with a subset of riders and scale what works.",
            "Coordinate with support operations to reduce ticket volume.",
        ],
        "qualifications": [
            "3+ years of product management; at least one shipped LLM feature.",
            "Experience defining model evaluation criteria.",
            "Consumer product experience.",
        ],
    },
    {
        "kind": "open", "source": "lever", "job_id": "demo-lv-3101",
        "company": "Granite Analytics", "title": "Growth Data Scientist",
        "location": "New York, NY", "workplace": "onsite", "comp": (150000, 180000), "posted_days_ago": 3,
        "summary": ["Growth Data Science at Granite Analytics measures what actually moves acquisition and retention for our analytics product."],
        "responsibilities": [
            "Design experiments and incrementality tests for growth initiatives.",
            "Build propensity and churn models to target lifecycle programs.",
            "Define north-star and input metrics with product leadership.",
        ],
        "qualifications": [
            "3+ years in data science or analytics.",
            "Strong Python, SQL and statistics; causal inference experience.",
        ],
    },
    {
        "kind": "open", "source": "greenhouse", "job_id": "demo-gh-1102",
        "company": "Juniper Grocers", "title": "Product Marketing Manager",
        "location": "Remote - US", "workplace": "remote", "comp": (110000, 135000), "posted_days_ago": 4,
        "summary": ["Product Marketing at Juniper Grocers tells the story of our delivery membership to busy households."],
        "responsibilities": [
            "Own positioning and messaging for the delivery membership.",
            "Plan launches with product, lifecycle and paid teams.",
            "Run customer research to sharpen value propositions.",
        ],
        "qualifications": [
            "3+ years in product marketing.",
            "Experience launching consumer subscription products.",
        ],
    },
    {
        "kind": "open", "source": "oracle", "job_id": "demo-or-4101",
        "company": "Halcyon Bank", "title": "Vice President, Digital Product",
        "location": "Jersey City, NJ", "workplace": None, "comp": (175000, 220000), "posted_days_ago": 2,
        "summary": ["Halcyon Bank's Digital Product group is rebuilding how retail customers open and grow accounts on mobile."],
        "responsibilities": [
            "Lead the mobile account-opening product and its roadmap.",
            "Partner with risk and compliance to launch new verification flows.",
            "Drive conversion and early engagement metrics for new accounts.",
        ],
        "qualifications": [
            "8+ years of product management experience, 5+ in financial services.",
            "Experience leading teams of product managers.",
        ],
    },
    {
        "kind": "open", "source": "ashby", "job_id": "demo-ab-2102",
        "company": "Mapleleaf Learning", "title": "Strategy & Operations Manager, Growth",
        "location": "New York, NY", "workplace": "hybrid", "comp": None, "posted_days_ago": 5,
        "summary": ["Strategy & Operations at Mapleleaf Learning turns growth questions into decisions for our tutoring marketplace."],
        "responsibilities": [
            "Build business cases for new growth channels and present them to leadership.",
            "Run pilots with marketing and product, and scale what works.",
            "Own the operating cadence for growth metrics.",
        ],
        "qualifications": [
            "4+ years in strategy, consulting or operations.",
            "Strong modeling and communication skills.",
        ],
    },
]

# The open job that gets a finished Resume Assembler run and an ICP resume.
ASSEMBLER_JOB = ("greenhouse", "demo-gh-1101")

# --------------------------------------------------------------------------
# Evaluations: what the (scripted) model returns for each open job. Weights,
# gates, the salary floor and the verdict are computed by the real evaluator.
# Each tuple: (score, rationale); None score = abstained.
# --------------------------------------------------------------------------

EVALUATIONS = {
    "Orbitly": {
        "function_alignment": (10, "Owns the activation funnel and a user-facing metric — core growth PM."),
        "company_tier": (4, "Orbitly is not on the tier lists; unlisted default, Tier 3."),
        "seniority_scope": (8, "Ships growth product in year one and owns activation; scope growth likely."),
        "location": (10, "New York, NY."),
        "keyword_match": (9, "Activation, experimentation, funnel and cohort analysis, lifecycle partnership — all evidenced."),
        "yoe_title": (7, "Asks 5+ years PM; candidate has ~3 PM years plus analytics, bridged by the MBA."),
        "education_reqs": (10, "No blockers; work authorization fine."),
        "story_depth": (10, "Activation +35% and the referral program map directly and survive probing."),
        "gap_exposure": (7, "Creator-tools domain is new; otherwise no major gap."),
        "why_company": (4, "Tier 3, plausible but generic narrative."),
        "reasoning": "Score 1 is driven by a pure growth PM role owning activation in New York. Score 2 is strong: the activation and referral stories map directly to the JD's funnel and experimentation asks. The 5+ year PM ask is the main stretch, bridged by the MBA and analytics background.",
        "note": "Applied — activation is exactly my story. Tier 3 undersells it; the brand is strong in creator tools.",
    },
    "Kestrel Mobility": {
        "function_alignment": (10, "Owns the AI assistant roadmap and resolution rate — ships product, owns a metric."),
        "company_tier": (4, "Unlisted; Tier 3 default."),
        "seniority_scope": (8, "Owns a user-facing AI product from year one."),
        "location": (10, "New York, NY."),
        "keyword_match": (8, "LLM feature, evaluation criteria, pilots, support deflection — evidenced by the triage pilot."),
        "yoe_title": (10, "3+ years PM asked; squarely in band."),
        "education_reqs": (10, "No blockers."),
        "story_depth": (9, "Support triage pilot (18% faster handling) and recommendation model both map."),
        "gap_exposure": (7, "Mobility domain is new."),
        "why_company": (4, "Tier 3, generic."),
        "reasoning": "Score 1 rests on a shipping AI product role with a clear metric in New York. Score 2 is high: the LLM triage pilot is a direct match for evaluation and support deflection. The mobility domain is the only notable gap.",
    },
    "Granite Analytics": {
        "function_alignment": (8, "Embedded growth data science with a named owned metric."),
        "company_tier": (4, "Unlisted; Tier 3 default."),
        "seniority_scope": (6, "Owns measurement, but no product ownership in year one."),
        "location": (10, "New York, NY."),
        "keyword_match": (5, "Experiments and churn models evidenced; incrementality testing and north-star design only partly."),
        "yoe_title": (10, "3+ years asked; in band."),
        "education_reqs": (10, "No blockers."),
        "story_depth": (5, "Churn model maps; the experimentation story is about enabling tests, not running causal analysis."),
        "gap_exposure": (7, "Deep statistics depth is a stretch."),
        "why_company": (4, "Tier 3, generic."),
        "reasoning": "Score 1 is moderate: an analytics role with an owned metric but no product ownership. Score 2 is middling — churn modeling maps, but the causal-inference depth the role centers on is only partly evidenced. Worth a look, not a priority.",
    },
    "Juniper Grocers": {
        "function_alignment": (8, "Product marketing for a consumer subscription."),
        "company_tier": (4, "Unlisted; Tier 3 default."),
        "seniority_scope": (6, "Owns positioning; limited product ownership."),
        "location": (6, "Remote US — acceptable but scored down."),
        "keyword_match": (6, "Positioning and launches partly evidenced via referral and onboarding work."),
        "yoe_title": (7, "Title family adjacent."),
        "education_reqs": (10, "No blockers."),
        "story_depth": (6, "Referral program and onboarding messaging map loosely."),
        "gap_exposure": (7, "No dedicated PMM title yet."),
        "why_company": (4, "Tier 3, generic."),
        "reasoning": "A product marketing role that fits partially. The pay range tops out at $135K, below the floor, so the salary gate decides the verdict regardless of fit.",
    },
    "Halcyon Bank": {
        "function_alignment": (10, "Owns the mobile account-opening product and its conversion metric."),
        "company_tier": (4, "Unlisted; Tier 3 default."),
        "seniority_scope": (8, "Owns a core product with clear metrics."),
        "location": (6, "Jersey City, NJ — acceptable but scored down."),
        "keyword_match": (7, "Conversion, onboarding and verification flows evidenced."),
        "yoe_title": (1, "Asks 8+ years PM and 5+ in financial services — hard mismatch."),
        "education_reqs": (7, "No hard blockers."),
        "story_depth": (7, "Onboarding and verification redesign map well."),
        "gap_exposure": (4, "People management of PMs is a structural gap."),
        "why_company": (4, "Tier 3, generic."),
        "pm_years_required": 8,
        "reasoning": "The function fits, but the posting demands 8+ years of PM-title experience, which trips the PM-years gate. Skip.",
    },
    "Mapleleaf Learning": {
        "function_alignment": (8, "Growth S&O with a named owned metric cadence."),
        "company_tier": (4, "Unlisted; Tier 3 default."),
        "seniority_scope": (6, "Owns business cases and pilots; product ownership indirect."),
        "location": (10, "New York, NY."),
        "keyword_match": (7, "Business cases, pilots and growth metrics evidenced."),
        "yoe_title": (7, "4+ years strategy asked; analytics and PM experience bridge it."),
        "education_reqs": (10, "MBA valued; no blockers."),
        "story_depth": (7, "Referral program and support pilot stories map."),
        "gap_exposure": (7, "No consulting background."),
        "why_company": (None, "The posting gives no basis for a specific why-this-company case."),
        "reasoning": "A strategy role close to growth, in New York. Pay is not stated, so the salary floor cannot apply. The posting gives no basis for a why-this-company case, so that sub-score abstains rather than guessing low.",
    },
}

# --------------------------------------------------------------------------
# Applications (dashboard, All Applications). (company, title, role, status,
# highest_round, days_ago, linked job_id or None, referral)
# --------------------------------------------------------------------------

APPLICATIONS = [
    ("Northwind Pay", "Senior Product Manager, Growth", "Product Manager", "applied", "interview", 60, "demo-gh-1001", None),
    ("Lumen Health", "Product Manager, AI Care Experiences", "Product Manager", "rejected", "phone_screen", 54, "demo-ab-2001", None),
    ("Cobalt Ledger", "Product Analytics Lead", "Data Analyst", "rejected", "applied", 47, "demo-lv-3001", None),
    ("Fernway Travel", "Lifecycle Marketing Manager", "Marketing", "applied", "applied", 39, "demo-gh-1002", None),
    ("Sundial AI", "AI Product Strategist", "Strategy", "applied", "final_round", 32, "demo-ab-2002", "MBA classmate"),
    ("Pinecrest Commerce", "Product Manager, Personalization", "Product Manager", "applied", "phone_screen", 25, "demo-gh-1003", None),
    ("Orbitly", "Senior Product Manager, Activation", "Product Manager", "applied", "applied", 1, "demo-gh-1101", None),
    ("Tidewater Media", "Growth Product Manager", "Product Manager", "rejected", "applied", 70, None, None),
    ("Velvet Audio", "Product Manager, Subscriptions", "Product Manager", "rejected", "phone_screen", 66, None, None),
    ("Quillon", "AI Product Manager", "Product Manager", "rejected", "applied", 64, None, None),
    ("Harborview Insurance", "Senior Data Analyst, Growth", "Data Analyst", "rejected", "applied", 58, None, None),
    ("Brightwater Fitness", "CRM Marketing Manager", "Marketing", "rejected", "applied", 52, None, None),
    ("Silverpine Capital", "Strategy Associate, Digital", "Strategy", "withdrawn", "phone_screen", 50, None, None),
    ("Aster Telehealth", "Product Manager, Patient Growth", "Product Manager", "rejected", "interview", 45, None, "Former colleague"),
    ("Meadowlark Games", "Product Analyst", "Data Analyst", "rejected", "applied", 43, None, None),
    ("Copperline Logistics", "AI Strategy Manager", "Strategy", "applied", "applied", 37, None, None),
    ("Redwood Robotics", "Product Manager, Platform", "Product Manager", "rejected", "applied", 35, None, None),
    ("Bluebird Banking", "Growth Marketing Manager", "Marketing", "applied", "applied", 30, None, None),
    ("Cascade Health", "Product Operations Manager", "Product Manager", "rejected", "applied", 28, None, None),
    ("Emberly", "Senior Product Manager, Onboarding", "Product Manager", "applied", "phone_screen", 21, None, None),
    ("Lattice Grove", "Marketing Analytics Lead", "Data Analyst", "applied", "applied", 18, None, None),
    ("Polaris Home", "Product Manager, Search", "Product Manager", "applied", "applied", 0, None, None),
    ("Ridgeway Bank", "AI Transformation Lead", "Strategy", "applied", "applied", 10, None, None),
    ("Starling Pets", "Lifecycle Product Marketing Manager", "Marketing", "applied", "applied", 7, None, None),
    ("Wavecrest Studio", "Product Manager, Creator Growth", "Product Manager", "applied", "applied", 0, None, None),
]

# --------------------------------------------------------------------------
# Jordan Lee's tailored resumes, in the example profile's layout. Parsed by
# the real resume parser. Each is attached to the application at that
# company.
# --------------------------------------------------------------------------

_EDUCATION = """\
EDUCATION
2024 - 2026 LAKESHORE SCHOOL OF BUSINESS Chicago, IL
 Master of Business Administration, June 2026
• Product Management Club, VP of Programming
2014 - 2018 RIVERTON UNIVERSITY Riverton, OH
 Bachelor of Arts in Economics, May 2018
• Dean's List; captain of the debate team
"""

_ADDITIONAL = """\
ADDITIONAL DATA
• Work Authorization: U.S. Citizen | Languages: English, Spanish
• Tools: SQL, Python, Amplitude, Braze, Figma, Looker
"""


def _resume(headline: str, carewell: list[str], courtside: list[str], bp_pm: list[str], bp_sa: list[str],
            bp_da: list[str], northbeam: list[str]) -> str:
    def bullets(items):
        return "".join(f"• {b}\n" for b in items)

    return (
        "JORDAN LEE\n"
        f"{headline}\n"
        "New York, NY | jordan.lee@example.com\n"
        + _EDUCATION
        + "EXPERIENCE\n"
        "Spring 2026 Carewell Health (digital primary-care startup) Chicago, IL\n"
        " AI Product Manager, MBA Intern\n" + bullets(carewell)
        + "Fall 2025 Courtside Analytics (sports ticket pricing) Chicago, IL\n"
        " Analytical Consultant, MBA Intern\n" + bullets(courtside)
        + "2019 - 2025 Brightpath Mobile (consumer fintech app, 3M users) New York, NY\n"
        " Product Manager, Growth, 2022 - 2025\n" + bullets(bp_pm)
        + " Senior Analyst, Growth Analytics, 2021 - 2022\n" + bullets(bp_sa)
        + " Data Analyst, 2019 - 2021\n" + bullets(bp_da)
        + "2018 - 2019 Northbeam Digital Agency (performance marketing agency) New York, NY\n"
        " Marketing Analyst\n" + bullets(northbeam)
        + _ADDITIONAL
    )


# Shared building blocks, so the Bullet Bank shows lines reused across
# resumes and reworded variants of the same story.
_ACTIVATION = "Rebuilt onboarding flow, lifting first-week activation 35% and halving drop-off at identity check; partnered with design and compliance on progressive verification"
_ACTIVATION_V2 = "Led onboarding redesign that lifted first-week activation 35%; ran 12 A/B tests with design and engineering to cut identity-check drop-off in half"
_REFERRAL = "Launched referral program, doubling referral sign-ups and lowering blended CAC 12%; set reward tiers and fraud limits with marketing and finance"
_RECS = "Shipped in-app offer recommendation model with ML engineers, raising offer click-through 22% and monthly active usage 6%"
_TRIAGE = "Piloted LLM support triage assistant, cutting ticket handling time 18% across 3 queues; set evaluation criteria and human review with support leads"
_TRIAGE_V2 = "Built evaluation harness for an LLM triage pilot, scoring 400 labeled tickets on accuracy and safety before rollout to 3 support queues"
_PRICING = "Modeled dynamic ticket pricing on 210K transactions, identifying a 9% revenue opportunity; presented recommendations to the client's leadership"
_PRICING_V2 = "Analyzed 210K ticket transactions to surface underpriced seat tiers, sizing a 9% revenue upside adopted in the client's next season plan"
_CHURN = "Built churn-propensity model on 18 months of account data, targeting a win-back campaign that recovered 4% of at-risk subscribers"
_DASH = "Designed the growth metrics dashboard used in weekly business reviews, replacing 6 manual reports for product and marketing leads"
_EXPERIMENTS = "Set up experimentation framework with holdout groups, letting product teams launch 40+ tests a year with consistent readouts"
_COHORTS = "Analyzed sign-up cohorts to locate the identity-check drop-off, sizing the opportunity that funded the onboarding redesign"
_AGENCY = "Optimized paid social campaigns for 5 retail clients, lowering cost per acquisition 15% through audience and creative testing"
_AGENCY_V2 = "Built weekly performance reports for 5 retail clients, flagging budget shifts that improved return on ad spend 11%"

RESUMES = {
    # application company -> resume text
    "Northwind Pay": _resume(
        "Growth Product Manager | 35% Activation Lift on a 3M-User App | MBA '26",
        [_TRIAGE], [_PRICING],
        [_ACTIVATION, _REFERRAL, _RECS], [_EXPERIMENTS, _COHORTS], [_DASH], [_AGENCY],
    ),
    "Lumen Health": _resume(
        "AI Product Manager | LLM Pilots with Measured Outcomes | MBA '26",
        [_TRIAGE_V2, _TRIAGE], [_PRICING],
        [_RECS, _ACTIVATION_V2, _REFERRAL], [_EXPERIMENTS], [_DASH], [_AGENCY],
    ),
    "Cobalt Ledger": _resume(
        "Product Analytics Lead | Experimentation and Churn Modeling | MBA '26",
        [_TRIAGE_V2], [_PRICING_V2, _PRICING],
        [_ACTIVATION_V2, _RECS], [_CHURN, _EXPERIMENTS, _COHORTS], [_DASH], [_AGENCY_V2],
    ),
    "Sundial AI": _resume(
        "AI Product Strategist | From Pilot to Measured Rollout | MBA '26",
        [_TRIAGE, _TRIAGE_V2], [_PRICING_V2],
        [_REFERRAL, _RECS, _ACTIVATION], [_EXPERIMENTS], [_DASH], [_AGENCY],
    ),
}

# --------------------------------------------------------------------------
# Bullet Bank: tags applied by hand, and what the scripted suggester proposes.
# --------------------------------------------------------------------------

TAGGED = {
    _ACTIVATION: ["Experimentation", "User Research/Discovery"],
    _ACTIVATION_V2: ["Experimentation"],
    _REFERRAL: ["Paid/Performance", "Partnerships/Co-marketing"],
    _RECS: ["Personalization/Recsys"],
    _TRIAGE: ["Agentic/LLM Product", "Pilot-to-Scale"],
    _CHURN: ["Predictive Modeling", "Lifecycle/Funnel Analytics"],
    _DASH: ["BI/Dashboarding"],
}

SUGGESTED = {
    # sentence -> [(tag, reason), ...]; the first of each list gets accepted
    # and the rest stay pending, except where noted in seed_demo.py.
    _TRIAGE_V2: [("Agentic/LLM Product", "Builds an evaluation harness for an LLM pilot."),
                 ("Pilot-to-Scale", "Scores a pilot before rolling it out to three queues.")],
    _EXPERIMENTS: [("Experiment Design/Causal Inference", "Sets up holdout groups for consistent test readouts."),
                   ("Experimentation", "Lets teams launch 40+ tests a year.")],
    _PRICING: [("Business Case/Exec Comms", "Sizes a revenue opportunity and presents it to leadership."),
               ("Predictive Modeling", "Models pricing on transaction data.")],
    _COHORTS: [("Lifecycle/Funnel Analytics", "Analyzes sign-up cohorts to find a funnel drop-off.")],
    _AGENCY: [("Paid/Performance", "Optimizes paid social against cost per acquisition."),
              ("Audience Targeting", "Lowers CPA through audience testing.")],
}

# --------------------------------------------------------------------------
# Resume Assembler run on ASSEMBLER_JOB, and the ICP resume for it.
# --------------------------------------------------------------------------

ATS_CRITERIA = [
    ("Ownership of an activation or onboarding funnel", "domain", True, ["activation", "onboarding", "funnel"]),
    ("Experimentation program with A/B tests", "skill", True, ["A/B", "experiment"]),
    ("Funnel and cohort analysis", "skill", True, ["cohort", "funnel"]),
    ("SQL and analytics fluency", "tool", True, ["SQL"]),
    ("Partnership with lifecycle marketing", "domain", False, ["lifecycle", "messaging"]),
    ("Consumer subscription product experience", "domain", False, ["subscription", "consumer"]),
]

ICP_EXPERIENCE = [
    ("Health-tech startup — AI PM internship", [
        "Piloted an LLM onboarding assistant for new patients, raising day-one task completion 20%; defined evaluation criteria with clinical leads and set human review for low-confidence answers",
        "Mapped first-week drop-off across 3 patient cohorts, prioritizing 2 activation fixes adopted for the next release; partnered with design to prototype guided setup",
    ]),
    ("Fintech app — Growth Product", [
        "Owned first-week activation for a 3M-user app, lifting activation 35% through 12 onboarding experiments; partnered with design, engineering and compliance",
        "Built referral loop doubling invite-driven sign-ups and cutting blended CAC 12%; worked with marketing on reward tiers and lifecycle messaging",
        "Launched cohort-based activation dashboard used in weekly reviews, replacing 6 manual reports; aligned metric definitions with product and marketing leads",
    ]),
]

# Tracked ATS boards — real public job-board APIs, not anyone's actual list.
TRACKED_COMPANIES = [
    ("Stripe", "greenhouse", "stripe"),
    ("Datadog", "greenhouse", "datadog"),
    ("Notion", "ashby", "notion"),
    ("Plaid", "ashby", "plaid"),
    ("Spotify", "lever", "spotify"),
]
