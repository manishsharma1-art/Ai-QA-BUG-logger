# QA Bug Logger: ROI & Cost Analysis

## Executive Summary
This document outlines the Return on Investment (ROI), workload efficiency gains, and infrastructure costs associated with deploying the AI-powered QA Bug Logger. By automating the extraction and formatting of bug reports from raw videos and text briefs, the QA team can reclaim hundreds of hours per year with near-zero infrastructure costs.

---

## 1. Workload Analysis & Time Savings

### Baseline Metrics
* **Current Manual QA Time per Bug:** ~10 minutes
* **Automated Process Time (including QA review):** ~1 minute
* **Net Time Saved per Bug:** **9 minutes** (90% efficiency increase)
* **Scope:** IndiaMART Organization-Wide
* **Average Volume:** 3,000 bugs / Quarter
* **Total Team Volume:** 3,000 bugs / Quarter (1,000 bugs / month)

### Organization-Wide Impact
* **Monthly Savings:** **150 hours saved per month**
* **Quarterly Savings:** **450 hours saved per quarter**
* **Yearly Savings:** **1,800 hours saved per year**
* *The organization reclaims 1,800 hours of productivity annually, massively boosting overall engineering velocity equivalent to adding a full-time employee's output at zero extra hiring cost.*

---

## 2. Cost Analysis

The bot is designed to be incredibly lightweight and takes full advantage of Google Cloud's generous "Always Free" tiers.

### AI Token Consumption (Gemini 2.5 Flash)
* **Token Breakdown per Bug:** 
  * Text/Prompt Context: ~1,500 tokens
  * Video Processing (60 frames × 258 tokens/image): 15,480 tokens
  * Total Input: ~17,000 tokens per bug
* **Monthly Token Volume:** 1,000 bugs × 17,000 tokens = ~17.00 Million tokens/month
* **Cost Efficiency:** At ~$0.075 per 1M tokens, processing a single bug costs **~$0.0014**.
* **Budget Utilization:** 
  * Projected Monthly Cost: **$1.40 / month**
  * Current Allocated Budget: **$20.00 / month**
  * **Status:** The team uses only **~7% of the allocated $20 API budget** to process 1,000 bugs a month, leaving a massive buffer for future scaling.

### Server Infrastructure (Google Cloud Run)
* **Required Memory:** 512MB RAM
* **Execution Time:** ~10-15 seconds per bug
* **Monthly Compute Used:** ~11,250 vCPU-seconds
* **Cost:** **$0.00 / month** *(Google Cloud Run provides 180,000 free vCPU-seconds and 2 million free requests every month, meaning the server operates completely within the free tier).*

### Storage (Artifact Registry)
* **Cost:** **$0.00 / month** *(The Docker image requires < 500MB. Google provides 5GB of free storage per month).*

### Total Operational Cost
* **Monthly Cost:** ~$1.40
* **Yearly Cost:** **~$16.80**

---

## 3. Final ROI Statement
For an estimated operational cost of just **$16.80 per year**, the organization will unlock **1,800 hours** of reallocated engineering and testing capacity. This represents an unprecedented return on investment, shifting the focus from manual data entry to critical product quality assurance.
