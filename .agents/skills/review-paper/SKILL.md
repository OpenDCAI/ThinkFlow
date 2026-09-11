---
name: review-paper
description: Critique or peer-review an attached academic paper for correctness, novelty, significance, methodology, experiments, reproducibility, literature positioning, strengths, weaknesses, and actionable revisions. Use when the user asks to review, critique, assess, evaluate, act as a reviewer, check whether claims are supported, or judge submission readiness. Do not use for ordinary explanation or summary requests.
metadata:
  inspiration: bytedance/deer-flow academic-paper-review
---

# Review Paper

Produce a rigorous, constructive review grounded in the supplied paper. Understand the work before judging it. Do not turn a normal reading question into a venue recommendation.

## Evidence boundaries

1. Use the attached LaTeX/PDF context as the primary evidence.
2. Separate objective errors, methodological concerns, missing evidence, and preferences.
3. Search externally for literature positioning, current baselines, public code, retractions, or citation verification only when those checks affect the requested review.
4. Mark external findings separately from statements made by the paper.
5. Never infer acceptance, rejection, novelty, or correctness from author identity, affiliation, writing polish, or venue alone.

## Review sequence

1. Identify paper type, central claims, intended contribution, and evaluation target.
2. For every major claim, identify the presented evidence and rate support as strong, moderate, weak, or absent.
3. Evaluate the rubric in [references/review-rubric.md](references/review-rubric.md), adapting emphasis to empirical, theoretical, systems, survey, or position papers.
4. Classify concerns by severity:
   - **Major**: threatens correctness, central novelty, or the main empirical conclusion.
   - **Moderate**: materially limits generality, reproducibility, or interpretation but is repairable.
   - **Minor**: clarity, presentation, or localized reporting issue.
5. Give a concrete remedy or decisive follow-up experiment for each major or moderate concern.
6. State review confidence and the limits of what could be checked from the supplied material.

## Default output

Use this structure unless the user asks for a shorter critique:

```markdown
# Review: {title}

## Executive Assessment
## Claimed Contributions and Supporting Evidence
## Strengths
## Major Concerns
## Minor Concerns
## Methodology and Experimental Assessment
## Literature Positioning
## Questions for the Authors
## Actionable Recommendations
## Overall Assessment and Confidence
```

An overall accept/reject recommendation is optional. Include it only when the user asks for a reviewer-style verdict or names a target venue. Do not manufacture page or section references; include evidence locations only when available and requested.

If asked to save the review, write Markdown under `../../artifacts/paper-reviews/` without overwriting existing files.
