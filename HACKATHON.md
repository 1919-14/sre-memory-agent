# HackWithHyderabad — Working Brief

> Consolidated artifact: problem statement + content submission guide.
> Reference doc for building the project and producing all required deliverables.
> Project repo: `sre-memory-agent`

---

## 1. The Problem Statement — AI Agents That Learn Using Hindsight

Build AI-powered applications using **Hindsight**, the memory system by **Vectorize** that lets AI agents
remember, recall, and improve over time.

The project must demonstrate **persistent memory and learning from past interactions** — not a stateless
chatbot. Memory is the product, not a feature.

### Required Technology

| Item | Value |
| --- | --- |
| Mandatory | **Hindsight** (all teams) |
| Docs | https://hindsight.vectorize.io/ |
| GitHub | https://github.com/vectorize-io/hindsight |
| Hindsight Cloud | https://ui.hindsight.vectorize.io |
| Cloud promo code | `MEMHACK99` → $50 free credits (**apply in billing AFTER registering**) |
| Community Slack | Hindsight Community Slack (for usage questions) |
| LLM access | Any LLM. Groq recommended (fast, generous free tier): https://groq.com/ |
| Suggested models | `openai/gpt-oss-120b`, `qwen/qwen3-32b` — handle function-calling errors |
| Coding agents | Code.in (https://code.in/), Jules (https://jules.google.com/), OpenCode (https://opencode.ai/), OpenClaw plugin (https://hindsight.vectorize.io/sdks/integrations/openclaw) |
| Inspiration repo | https://github.com/vectorize-io/self-driving-agents |

### Judging Criteria

| Criterion | Weight | What judges look for |
| --- | --- | --- |
| Innovation | 30% | Fresh take on a real problem; goes beyond obvious chatbot territory |
| Use of Hindsight Memory | 25% | Memory central to value; agent clearly improves over time |
| Technical Implementation | 20% | Clean, well-architected, functional code; handles edge cases |
| User Experience | 15% | Intuitive interaction; demo tells a compelling story |
| Real-world Impact | 10% | Solves a genuine problem; credible path to adoption |

### How to Pick a Winning Project

1. **Solve a real business problem.** Ask: "Would someone pay $50/month for this?"
   - ❌ "An AI that remembers your favorite color."
   - ✅ "An AI sales assistant that remembers every objection a prospect raised across calls and drafts personalized follow-ups."
2. **Make memory the star, not a feature.** Show a clear before/after: generic without memory → dramatically better with it.
   - Show improvement across multiple interactions
   - Recall context from days/weeks ago
   - Learn user preferences and adapt behavior
   - Build domain expertise from past conversations
3. **Think like a demo.** Value must be obvious within 60 seconds: problem → agent solving it → agent getting smarter.

### Constraints & Anti-patterns

- **Avoid student-centric projects**: AI tutors, group project managers, quiz generators, etc.
- **Keep scope tight**: one workflow, one persona, one clear value proposition, executed well.
- **Use realistic data.** Real data from Kaggle/HuggingFace is great; otherwise generate synthetic data that
  *looks* real — real-sounding customer names, deal sizes, error logs. **The data quality is the single
  biggest factor in making the project look real.**

### Project Idea Map (professional workflows where memory transforms the agent)

| Function | Agent ideas |
| --- | --- |
| **Sales & Revenue** | Deal Intelligence (objections, competitors, stakeholders, pricing across a deal cycle) · Outbound Prospecting (which messaging angles work per persona) · Proposal & RFP (past wins/losses, reusable boilerplate) |
| **Marketing & Content** | Content Strategy (what was published, what performed, gaps, brand voice) · SEO & Citation (ranking history, past optimizations, competitor moves) · Social Engagement (post styles/topics/timing that work for *your* audience) |
| **Engineering & DevOps** | Incident Response (past incidents, root causes, working runbooks) · Code Review (team standards, recurring mistakes, architecture preferences) · DevOps Pipeline (deploy history, failure causes, risky changes) |
| **Ops & Support** | Customer Support (full ticket history, environment, frustration level, what worked) · Accounts Payable (vendor patterns, terms, recurring discrepancies) · Compliance & Audit (requirements, findings, remediation status) |
| **Product & Strategy** | User Feedback Synthesizer (themes across channels over time) · Competitive Intelligence (cumulative competitor moves) · Meeting Prep (per-contact history, promises, missed follow-ups) |

### Submission Requirements

- [ ] GitHub repository — clean, documented code
- [ ] Demo video showing the agent in action
- [ ] Live project demo to judges
- [ ] Content deliverables — **every team member**: Article + Social Post; **team**: Video
- [ ] Written explanation of how Hindsight memory is used in the solution

---

## 2. Content Submission Guide

### Overview

You built something real with agent memory — now help other developers see what's possible. Generate an
article, a social post, and a video using the prompts below, run **inside the project repo** so the AI can
read your actual code. Estimated time: ~1 hour with an AI coding agent.

### Where to Publish

Any developer-visible, **public and linkable** platform:

- **Medium** — best discoverability for technical content, free
- **Dev.to / Hashnode** — developer-native with built-in audiences
- **Substack** — good for longer technical write-ups
- **LinkedIn Articles** — note: a LinkedIn *article* ≠ a LinkedIn *post*

### Content Contest Requirements

Teams where **every member** submits an article and a social post, plus one team video, are eligible.

| Deliverable | Length | Scope |
| --- | --- | --- |
| Article — technical write-up | 800–1,500 words | Per team member |
| Social post — promoting the article | — | Per team member |
| Video — demo/walkthrough | 2–5 min | 1 per team |

Members may cover the same project from different angles or focus on the parts they personally built.
**Everything must be in English.**

### 🚫 Disqualifiers (read this twice)

- **No mention of the hackathon anywhere** — not in the title, body, or hashtags of articles or social posts.
- Do not post videos/articles as Google Drive links — publish to a real public platform (YouTube, Medium, Dev.to, etc.).

---

### Part 1 — The Article

Write something an AI enthusiast and engineer would be excited to read. Find the most interesting aspect of
the project and make it exciting — aim for "OpenClaw level of excitement."

#### Step 1: Title Ideas (Prompt 1)

Titles must be about the **idea or the result**, never the hackathon. An engineer should want to click it in their feed.

**Good:** "My AI agent just broke up with my girlfriend." · "I built an agent to apply to jobs, it found ones that hadn't even been posted yet." · "How We Built a ____ that ____ using Hindsight, ____, and ____"

**Bad:** "Our Hindsight Hackathon Project" · "Exploring Agent Memory with Hindsight" · "A Deep Dive into Memory-Augmented AI Agents"

```
You are an experienced software engineer who writes high-performing technical articles for skeptical
developers on sites like Hacker News, Reddit, and personal blogs.

Your task: generate 20 possible article titles about the project in this repo. Find a unique angle to
highlight your work with Hindsight.

DO NOT MENTION HACKATHON ANYWHERE IN THE ARTICLE TITLES.

Each title must:
- Mention Hindsight (nothing negative)
- Hint at a real story, failure, or insight
- Be about one specific idea, decision, or problem
- Make another engineer curious enough to think "I want to see what happened there."

Constraints:
- Audience: experienced engineers, not managers or marketers.
- Voice: first person ("I...", "What I learned...") where natural, but don't force it.
- Style: Short, concrete, specific. No more than 10 words.
- No hype, no clickbait, no buzzwords ("revolutionary", "unlock", "smart", "AI-powered", etc.).
- Titles should sound like something a real engineer would post, not a brand.

Good patterns: "I built an agent that X, here's what I learned." / "How I Did Y With Z" /
"Why I Stopped Doing X and Switched to Y" / "How I Designed/Built/Debugged Z"

Avoid patterns like: "The Future of X" / "Why X Will Change Everything" / "A Comprehensive Guide to X"

Look through the code in this repository and identify potential candidates for the article's core topic.

Output:
- Return exactly 20 titles, one per line, no numbering, no extra commentary.
- Make them diverse: vary the verbs, angles, structures.
```

**YOUR TURN:** Pick the title you like best (or riff on one).

#### Step 2: Full Article Draft (Prompt 2)

```
You are a senior software engineer who writes first-person, technical blog posts that other engineers
actually want to read. You are looking at a real codebase and telling the story of what you built, why,
and what you learned. No marketing voice, no hype.

You are going to write an article based on this repository.

DO NOT MENTION HACKATHON ANYWHERE IN THE ARTICLE.

Goal:
Given this repo, understand what the project does, how it's structured, and any interesting design
decisions. Identify one clear, opinionated story to tell about building or using this system. Write a
first-person article that would be credible and interesting to experienced engineers on Hacker News,
Reddit, and personal blogs. Write it in a style that would be appropriate for CIO magazine, TheNewStack,
or similar publications. Focus on making an interesting article about the project I'm working on in this
repository. Assume that by the time the article is published, any mock data, demo-quality
implementations, placeholders have all been fully implemented with real production implementations. Do
not position the project as a demo or hackathon project. Assume you are describing the future state
fully completed project that this repository has the potential to become.

Voice and tone:
- First person: "I" / "we", not "the team" or "the product".
- Sound like a competent engineer who ships code and explains it clearly.
- Be concrete, specific, mildly opinionated.
- No buzzwords, no "revolutionary", no "unlocking value", no "smart agents".
- If something was painful, say so directly.
- Assume readers are technical and skeptical.

Structure (target 1,200-2,000 words):
1. Hook (first 1-2 sentences)
2. What the system does and how it hangs together
3. Core technical story - pick one through-line and go deep
4. Code-backed explanations with 2-4 small snippets from the repo
5. Results / behavior with concrete example interactions
6. Lessons learned - 3-5 reusable takeaways

Style rules:
- Prefer specifics over abstractions.
- Do not claim benchmarks or results not clearly implied by the code.
- Include aspects of Hindsight usage and its benefits as a major theme.

Include markdown links with SEO-optimized anchor text naturally embedded into the article's copy:
  - Hindsight GitHub: https://github.com/vectorize-io/hindsight
  - Hindsight docs: https://hindsight.vectorize.io/
  - Vectorize agent memory: https://vectorize.io/what-is-agent-memory

Title: [PASTE YOUR CHOSEN TITLE]

Output format:
- Output only the finished article in Markdown.
- Single H1 title (# ...), sections with ## headings, code blocks for snippets.

Write the markdown to a file called: article.md
```

**YOUR TURN:** Edit the draft. Add your voice, fix details, drop in screenshots.

#### Step 3: Add Screenshots and Images

- Project screenshots — the agent's interface
- Terminal/code screenshots — real retain/recall calls in action
- Architecture diagram — where Hindsight sits in the stack (a simple box diagram is fine; Nano Banana works)
- Team photo — optional, but adds personality

Capture: macOS `Cmd+Shift+4` · Windows `Win+Shift+S` · Linux Flameshot / gnome-screenshot.
Use PNG for code/UI, JPEG for photos. Crop tightly.

#### Step 4: Clean Up and Publish

Verify header/link formatting matches the target platform. Confirm these links are present and correct:

- Hindsight GitHub: https://github.com/vectorize-io/hindsight
- Hindsight docs: https://hindsight.vectorize.io/
- Vectorize agent memory: https://vectorize.io/what-is-agent-memory

#### Step 5: Share Your Article on Reddit

Submit as a **Link post** on one of: r/llmdevs · r/sideproject · r/aiagents · r/aimemory

#### Pre-Submit Checklist

- [ ] Title is about the idea/result, not the hackathon
- [ ] Opens with something specific and surprising, not a generic intro
- [ ] Problem explained in concrete terms
- [ ] Shows where and how Hindsight was integrated
- [ ] At least one real code snippet from the project
- [ ] At least one concrete before/after example
- [ ] At least one honest lesson, limitation, or dead end
- [ ] Screenshots/images included
- [ ] Published to a public, linkable URL

---

### Part 2 — The Social Post

Publish the article first, then promote it with a LinkedIn post (or X) that makes engineers stop scrolling.
Goal: saves, reposts, comments — not just clicks.

```
You are an expert B2B LinkedIn copywriter known for creating technically credible and interesting posts
that resonate with developers, AI engineers, and AI enthusiasts.

Write a single LinkedIn post about the project in this repository in a way that maximizes the value to
the reader. Write it in the style of Andrej Karpathy.

Assume you have read the README, skimmed the code, and seen the article we wrote about this project.
Ground the post in specific behaviors and outcomes that only make sense because the agent is using
Hindsight for memory.

Requirements:
DO NOT MENTION HACKATHON ANYWHERE IN THE SOCIAL POST.

Hook (first 2 lines):
- Open with a bold, curiosity-driving statement or question.
- Speak to a real pain or misconception about agents.
- No hashtags or links in the first 2 lines.

Body:
- Short paragraphs (1-2 sentences), plenty of line breaks for mobile.
- Present 3-7 concrete, technical takeaways as a mini cheat sheet, step-by-step, or before/after contrasts.
- At least one takeaway should show a clear behavior change before vs after adding the technology.
- Focus on things a practitioner could actually copy tomorrow.
- Somewhere in the body positively mention Hindsight agent memory and the decision to use it.

Positioning:
- Credible, hands-on, slightly opinionated. Not salesy.
- Tie the project to a concrete outcome.

Links & hashtags:
- Add 3-5 relevant hashtags on the last line only: #AIAgents, #AI, #Hindsight, #AgentMemory, #AIMemory, #LLM.
- Do not use #Hackathon or student-related tags.

Tone:
- Clear, direct, slightly opinionated. No fluff. No emojis unless they add clarity.

Frame the post around the cool project we built - do not mention it is a hackathon project.

Return only the final post text, under 800 characters.
```

**YOUR TURN:** Review, tweak the hook, publish. Post the article URL as the **first comment**.

Then:
- **Step 5** — Make sure the project GitHub repo link is in the **main post content**.
- **Step 6** — Once live, add a **comment** linking Hindsight: https://github.com/vectorize-io/hindsight
  - e.g. "Here's a link to Hindsight if you want to check it out: https://github.com/vectorize-io/hindsight"

Reference examples: [1](https://www.linkedin.com/feed/update/urn:li:activity:7449155863837167616/) · [2](https://www.linkedin.com/feed/update/urn:li:activity:7449068622813036544/) · [3](https://www.linkedin.com/feed/update/urn:li:activity:7449108681063038976/)

---

### Part 3 — The Video

Screen recording with voiceover. Talking head + screen preferred, not required.

| Attribute | Requirement |
| --- | --- |
| Length | 2–5 min (shorter is better) |
| Style | Screen recording + voiceover |
| Resolution | 1080p minimum |
| Recording | Record your screen — not a phone pointed at a monitor |

**Cover:**
1. Quick intro (30 sec) — who you are, what you built, one sentence on why
2. The problem (30 sec) — show the agent failing/struggling **without** memory
3. The demo (2–3 min) — a real interaction; show retain/recall happening live
4. Wrap up (30 sec) — one key takeaway; what surprised you

#### Video Script & Titles (Prompt 5)

```
Look at this project and write a 3-minute video script for a screen-recorded demo.

My name: [YOUR NAME]

Structure it as:
1. Quick intro (who I am, what this project does) - 30 sec
2. Show the problem (the agent without memory, what goes wrong) - 30 sec
3. Live demo (show retain/recall in action, highlight the before/after moment) - 2 min
4. One key takeaway (what surprised me) - 30 sec

Include specific cues for what I should show on screen at each point. Reference actual files, commands,
or endpoints from this project.

Keep the narration conversational - not scripted-sounding. A mid-level engineer should be able to follow along.

Also give me 5 high performing titles for the video that would make people on YouTube want to click on
the video.
```

**YOUR TURN:** Practice once, then record. Don't aim for perfect — aim for authentic.

**Recording tips:** OBS / Loom / QuickTime, or a Filmora free trial for screen+camera. Don't read the script
verbatim. Increase terminal/editor font size. Close notifications and unrelated tabs. A quick "Hi, I'm
[name]" on camera adds personality. Mistakes are fine — authenticity beats polish.

#### Thumbnail (Prompt 6)

```
Generate a viral thumbnail for this YouTube video. Make the thumbnail attention grabbing and something
that people scrolling would want to click on if they see it. The aspect ratio needs to be 16:9

Here is the video script:

[YOUR VIDEO SCRIPT HERE]
```

Use Google Nano Banana, attach a team member photo. Any free Gmail account works.

**Post the video publicly on YouTube** with the thumbnail — not Google Drive.

---

## 3. Quick Reference — All Prompts

| Step | What it does | You do |
| --- | --- | --- |
| Prompt 1 | Generates title ideas from your code | Pick the best title |
| Prompt 2 | Writes the full 800–1,500 word article | Edit + add screenshots/diagrams |
| Prompt 3 | Writes a LinkedIn/X post for the published article | Add article link, review, post; first comment links Hindsight repo |
| Prompt 5 | Writes a video script from your project | Record the video |
| Prompt 6 | Generates a viral YouTube thumbnail | Post video + thumbnail to YouTube |

**Time:** ~30–60 min per person for article/social + ~30–45 min for the team video.
The AI does the first draft; your job is picking options, adding real experience, dropping in screenshots, publishing.

Tag **Code.in** on LinkedIn.

---

## 4. Open Questions / Next Steps

- [ ] Confirm the project idea (repo slug: `sre-memory-agent` suggests an **Incident Response Agent** direction)
- [ ] Decide Hindsight Cloud vs. self-hosted OSS
- [ ] Pick LLM provider (Groq `openai/gpt-oss-120b` / `qwen/qwen3-32b` recommended)
- [ ] Define the 60-second demo story: problem → solution → agent getting smarter
- [ ] Generate realistic synthetic data early (biggest factor in perceived credibility)
- [ ] Assign per-member article angles and the team video
