# Hackathon Submission Details

Here is the ready-to-copy content for your hackathon submission form based on our updated calculations and technical architecture.

---

### Project title*
Brain Box Solution - AI-Powered QA Bug Logger

### Short pitch (1 sentence)*
An AI-powered Google Chat bot that eliminates manual data entry by visually analyzing screen recordings to automatically create perfectly structured bug tickets in under 60 seconds, saving 1,800 engineering hours a year.

### Problem we're solving
* **Time-Consuming Administration:** Manually filling out bug tickets (formatting descriptions, specifying exact steps to reproduce, uploading media, and assigning environments) takes an average of **10 minutes per bug**.
* **Context Switching:** QA testers constantly lose their "testing flow" when forced to switch context from the application under test to the project management platform.
* **Inconsistent Reporting:** Bug report quality varies wildly between engineers. Key details, environment variables, or critical steps are often missed in manual write-ups, causing friction between QA and Development teams.

### Technical Journey / skills.md*
Our technical journey focused on aggressively optimizing for speed, cost, and bypassing serverless constraints. Here are our key technical implementations:

**1. Beating Serverless Timeouts (The Two-Phase Async Pipeline):**
Google Chat webhooks enforce a strict 30-second timeout, but AI video analysis inherently takes longer. We engineered a custom architecture bypassing Google Cloud Run's CPU throttling (`--no-cpu-throttling`). We implemented an isolated `asyncio.Task` protected from Python's garbage collection, which allows the bot to reply to the user instantly while performing heavy multimodal LLM processing in the background.

**2. Intelligent Video Pruning & Cost Optimization:**
Sending raw video payloads directly to the LLM leads to token limits and high latency. We built a local OpenCV (`cv2`) pipeline that intelligently extracts exactly 1 frame per second (capped at 30 frames), resizes them to 480px, and compresses them. This guarantees perfect AI visual reasoning while keeping payload sizes tiny.

**3. Platform Agnostic AI Formatting:**
We utilized **Gemini 2.5 Flash** for its exceptional multimodal reasoning. The bot doesn't just transcribe text; it infers the operating system, deduces priority levels based on the crash severity, and strictly formats the output using OpenProject's Markdown requirements.

**Tech Stack:** FastAPI (Python), Google Cloud Run, Gemini 2.5 Flash, OpenCV, SQLite (`aiosqlite`), Google Workspace API, OpenProject API.

### Skill folder (GitHub repo or Google Drive)*
*[https://github.com/manishsharma1-art/Ai-QA-BUG-logger.git](https://github.com/manishsharma1-art/Ai-QA-BUG-logger.git)*

### Demo video URL (5–10 min)*
*[Insert Demo Video URL here]*

### Impact analysis*
**Business Impact (Hours & Cost):**
Our solution turns a 10-minute manual chore into a 1-minute automated review, yielding a **90% efficiency increase**. For the organization logging ~3,000 bugs per quarter, this reclaims an astounding **1,800 hours per year**. This is equivalent to adding a full-time QA engineer to the team entirely for free.

**Cost Efficiency:**
The architecture maximizes Google Cloud's free tiers (180,000 free vCPU-seconds). The optimized OpenCV frame extraction keeps AI costs incredibly low. Processing 1,000 bugs a month via the Gemini API costs roughly **$1.40/month**. The total operational cost of this entire system is just **$16.80 per year**. 

**Scalability & Legacy Benefits:**
Unlike the legacy process which scales linearly with human effort, our bot handles peak QA reporting days asynchronously without breaking a sweat. It standardizes bug reporting across the entire organization, ensures media is always attached to the right ticket, and allows QAs to stay permanently inside Google Chat and the product they are testing.
