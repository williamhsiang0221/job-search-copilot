# Design decisions

The calls that shaped this project, why I made them, and what the evidence
was. Each one is a decision I would defend in a product review.

---

## 1. Extraction and judgement are separate steps

**Decision.** A normalizer extracts what a posting *says* — responsibilities,
qualifications, pay, workplace, a short summary of the role. A separate
evaluator decides what it *means* for me. The raw posting text is always
kept.

**Why.** Changing how I judge roles should never require re-reading every
posting, and improving extraction should never require fetching postings
again. Keeping the raw text made both true: when I later added the role
summary, I re-normalized only the postings I needed, from stored text, for
under a cent each.

## 2. The model judges; code decides

**Decision.** The evaluator model assigns ten sub-scores on fixed scales and
reports gating facts (pay, years of experience required). Weights, gates,
thresholds and the final verdict are Python.

**Why.** A model asked to do weighted arithmetic mid-paragraph gets it subtly
wrong and never says so. With the arithmetic in code, a rubric change is a
reviewable diff, and two verdicts are always comparable because each stores
the weights it was computed with.

**The asymmetry the whole design rests on.** The verdict routes my attention.
A wrong APPLY costs a minute of reading; a wrong SKIP costs the role. So
uncertainty never produces a SKIP: when the posting doesn't state something,
the sub-score abstains instead of guessing low, and a low score reached with
an abstention lands on MAYBE, not SKIP. Only a hard gate on something the
posting actually states — pay below the floor, too many years required — can
skip a role outright. Unmatched score combinations also land on MAYBE.

## 3. "Copied, not written" — checked by code, not requested in a prompt

**Decision.** Two places where a model could invent text are guarded by code:
the Resume Assembler may only place lines that exist verbatim in one of my
real resumes, in the same section; and the posting's "about the role"
summary must appear word for word in the posting, or it is dropped.

**Why.** A resume line I can't defend in an interview is worse than no line.
A prompt that says "don't invent" is a request; a substring check is a
guarantee. On the first real postings it ran against, it dropped one
sentence that did not appear in the posting.

## 4. A hand-built agent loop where the harness is the referee

**Decision.** The Assembler is a tool-use loop I wrote directly against the
Messages API rather than an agent framework. The agent can view the draft,
swap a bullet or header, load more resumes, and run three checks. Every rule
lives in the tool handlers: same section only, no duplicates, only resumes
already loaded. A rejected move comes back as an error the agent must
handle. The loop — not the model — decides when to stop: on a pass, a round
cap, a turn cap or a cost cap.

**Why.** I wanted to understand an agent loop end to end, and every rule
enforced in code is one the model can't talk its way around. Each step is
written to the database as it happens, so the run is traced live in the UI:
every swap, every scan, every token and cent.

**What live runs taught me.**
- Replies hit the output limit mid-analysis and ended with no move, which
  the loop read as "done": 3 of the first 9 runs. Now a cut-off reply gets a
  short nudge and the loop continues.
- The recruiter screen only reads the top of the resume, and the agent kept
  swapping lines further down, so the recruiter saw identical drafts every
  round (0 of 5 rounds judged). Naming the exact positions it reads in the
  tool result fixed it: the agent swapped into those lines, the recruiter
  judged 3 of 5 rounds and preferred the draft. Describing the rule in words
  had not.

## 5. Measure before optimizing

**Prompt caching.** Each agent turn re-sends the whole conversation, so about
90% of a run's cost was re-sent input. A cache breakpoint that moves forward
each turn bills already-seen input at a tenth of the price. Measured on a
real 10-turn run: $0.059 against $0.157 uncached, **−62%**. Cost tracking was
updated in the same change — the API reports cached tokens separately, and
without that the per-run cost cap would have under-counted.

**The job filter.** I felt the boards were showing me only product-manager
roles. A 14-day dry scan of every tracked board — 1,438 postings in my
locations, title filter off — confirmed it: of 113 roles kept, about 95 were
PM titles, two were analytics, none were AI strategy. One broad phrase caught
every PM title while the other families relied on exact wording companies
rarely use. Re-tuned against the real titles, the same data kept **191**, and
a location bug (a two-letter keyword matching inside "Atlanta" and "Dallas")
was fixed along the way.

## 6. Pairwise judges, and knowing their limits

**Decision.** The Assembler's two screens compare the draft against the
original resume, side by side: a keyword-coverage ATS screen and a
six-second recruiter skim that only sees the headline and the top bullets of
the two most recent roles. A/B order is randomized, the original is never
named, and identical inputs are a free tie.

**What I chose not to build yet.** The natural next step is a scoreboard that
learns which bullets win. I held off. Those screens are a cheap model with
limited information, and anything that optimizes against them learns to
please the judge — the same failure as reward hacking in model training. I
also saw the ATS verdict flip between drafts that differed by one line. The
order I'd follow: calibrate the judge against my own blind picks first, use
my choices as the main learning signal, and treat interview outcomes as the
long-run check.

## 7. My own decisions are the evaluator's ground truth

**Decision.** Every verdict can carry a note: why I applied or passed, or
where the verdict got it wrong. The process for changing the rubric: propose
the change from those notes, then back-test it on the noted roles — does it
agree with my real decisions more often than the current one? — before it
ships.

**Why.** It's the same idea as product teams learning from what users accept
or change. My notes are plentiful, immediate, and the closest thing to ground
truth a one-person search has.

## 8. The Bullet Bank treats the sentence as the unit

**Decision.** About 1,300 bullet lines across my resumes are under 300
distinct sentences, because good lines get reused. The Bullet Bank stores
the sentence once, with how many resumes used it and when. A tag on a
sentence applies to every resume that contains it.

**Tag suggestions are suggestions.** A model proposes tags from each tag's
written definition. Nothing is applied until I accept it, a rejected
suggestion never comes back, and the share I accept is shown. That share is
the measure of how far to trust the suggester before automating anything.
The first live run exposed a real bug: every suggested tag was discarded,
because the model echoed the category into the tag name. The output schema
now only allows exact tag names.

## 9. Versioned prompts, stamped on every result

Every prompt is a file with a version, and every stored result records which
version produced it, viewable in the app. Two disagreeing evaluations are
then never a mystery: same posting, different rubric, and you can read both.

## 10. Personal data never lives in the code

Everything about the candidate — the rubric's background section, salary
floor, target locations, how their resume PDFs are laid out — lives in a
profile folder. The code is generic. This repository ships a fictional
profile and a demo database built by the app's own code, and a leak check
scans for personal terms and any real resume sentence before anything is
published. It's the same pattern companies use to publish a filtered mirror
of a private codebase, at one-person scale.
