**PRODUCT REQUIREMENTS DOCUMENT**

**AI Code Review Bot**

_Automated pull request analysis powered by large language models_

| **Document version** | v1.0 - Initial draft               |
| -------------------- | ---------------------------------- |
| **Date**             | June 15, 2026                      |
| **Author**           | Engineering / Product              |
| **Status**           | Draft - under review               |
| **Target release**   | Q3 2026 (MVP)                      |
| **Stakeholders**     | Eng Lead, DevOps, Senior Engineers |

# **1\. Overview**

AI Code Review Bot is a GitHub App that automatically reviews pull requests using a large language model. When a developer opens or updates a PR, the bot fetches the diff, analyzes each changed file with a structured LLM prompt, and posts inline review comments directly on the changed lines - just like a senior engineer would.

The goal is to reduce the time senior engineers spend on routine code review tasks (style issues, obvious bugs, missing error handling) so they can focus on higher-order architectural feedback.

# **2\. Problem statement**

**Current pain points**

- Code review is a bottleneck - PRs sit unreviewed for hours or days waiting for engineer availability.
- Senior engineers spend significant review time on low-level feedback (naming, null checks, security basics) that a tool could catch.
- New engineers get inconsistent feedback quality depending on who reviews their PRs.
- No automated enforcement of team-specific conventions without complex linting setups.

**Opportunity**

LLMs have become good enough to surface useful, contextual feedback on real code. By integrating this feedback directly into the GitHub PR workflow - not as a separate tool - we lower friction to near zero for both the reviewer and the author.

# **3\. Goals & non-goals**

## **3.1 Goals**

- Post automated inline review comments on every PR within 60 seconds of the PR being opened or updated.
- Reduce senior engineer time spent on low-level review feedback by at least 30%.
- Surface bugs, security issues, and style violations with a false-positive rate below 20%.
- Be configurable per repository via a .reviewbot.yml file.
- Support Python, JavaScript/TypeScript, and Go in the MVP.

## **3.2 Non-goals**

- Replace human code review - the bot is an assistant, not a gatekeeper.
- Full static analysis or compilation - the bot works only on the diff, not the full codebase.
- Auto-merging or auto-approving PRs.
- Support for proprietary or self-hosted LLMs in the MVP.
- IDE integration (future phase).

# **4\. User stories**

## **4.1 PR Author**

| **User story**                                                                                                                                   | **Acceptance criteria**                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| As a PR author, I want to receive automated feedback within a minute of opening a PR so I can fix obvious issues before requesting human review. | Bot posts comments within 60s. Comments appear as inline review comments on specific changed lines, not as a single top-level comment. |
| As a PR author, I want to understand why the bot flagged something so I can decide whether to act on it.                                         | Each comment includes a short explanation of the issue and a suggested fix or direction.                                               |
| As a PR author, I want to dismiss bot comments I disagree with so they don't clutter the review.                                                 | Bot comments are posted as a separate review thread. Resolving the thread archives them without affecting other reviews.               |

## **4.2 Team / Engineering Lead**

- As an engineering lead, I want to configure what the bot focuses on per repo so the feedback matches our team's standards.
- As an engineering lead, I want to see an acceptance rate metric (how often devs act on the bot's suggestions) so I can tune prompts over time.
- As an engineering lead, I want the bot to skip certain directories (e.g. vendor/, generated/) so it doesn't flag code we don't control.

# **5\. Functional requirements**

## **5.1 GitHub App integration**

- Register as a GitHub App with read access to code and read/write on pull requests and checks.
- Subscribe to pull_request events: opened, synchronize, reopened.
- Verify webhook signature (HMAC-SHA256) on every incoming request.
- Handle webhook delivery failures with automatic retry (GitHub retries up to 3 times).

## **5.2 Diff fetching & parsing**

- Fetch the unified diff for the PR via the GitHub REST API.
- Parse diff hunk headers to extract file paths, line ranges, and added/removed lines.
- Map LLM suggestions back to GitHub's position-based comment API (position = line offset within hunk).
- Skip binary files, generated files (based on .gitattributes or configurable glob patterns), and files over 500 lines changed.

## **5.3 LLM analysis**

- Send each changed file's diff to the LLM with a structured system prompt.
- System prompt instructs the model to: identify bugs, flag security issues (hardcoded secrets, injection risks), suggest missing error handling, and note style violations.
- Include surrounding context (up to 20 lines before and after each hunk) to improve suggestion quality.
- Chunk large diffs by file; skip files if token count would exceed context window.
- Return structured output: array of { file, line, severity, message, suggestion }.

## **5.4 Comment posting**

- Post suggestions as a single GitHub review (not individual comments) to avoid notification spam.
- Each comment anchored to the specific line using the position field in the review API.
- Include a severity badge in the comment body: \[BUG\], \[SECURITY\], \[STYLE\], \[SUGGESTION\].
- Post a summary comment at the top of the review listing the file count reviewed and issue count by severity.

## **5.5 Configuration (.reviewbot.yml)**

Each repository may include a .reviewbot.yml file in the root. Supported options:

- enabled: true/false - disable the bot for the entire repo.
- focus: \[bugs, security, style, all\] - limit what the bot checks.
- ignore_paths: - list of glob patterns to skip.
- languages: - override auto-detected language list.
- max_comments: - cap comments per review (default: 20).

## **5.6 Feedback loop**

- Listen for pull_request_review_comment events to detect when users reply to or resolve bot comments.
- Track thumbs-up / thumbs-down reactions on bot comments as a proxy for suggestion quality.
- Store per-repo acceptance rate in the database for dashboard display.

# **6\. Technical architecture**

## **6.1 Stack**

| **Layer**               | **Technology**                                                |
| ----------------------- | ------------------------------------------------------------- |
| **Webhook server**      | Node.js + Fastify (or Python + FastAPI)                       |
| **GitHub integration**  | @octokit/app (Node) or PyGithub                               |
| **Job queue**           | BullMQ + Redis - async processing so webhook returns 200 fast |
| **LLM API**             | Anthropic Claude (claude-sonnet-4-6) or OpenAI GPT-4o         |
| **Database**            | PostgreSQL (review history, repo config, metrics)             |
| **Deployment**          | Fly.io or Railway - single container, auto-restart            |
| **Local dev tunneling** | smee.io or ngrok to receive webhooks locally                  |

## **6.2 Request flow**

- GitHub fires a pull_request webhook to the bot's /webhook endpoint.
- Server verifies the HMAC signature, returns HTTP 200 immediately, and enqueues a review job.
- Worker picks up the job, fetches the PR diff via GitHub API, and parses hunk headers.
- Worker sends each file's diff to the LLM API with the structured system prompt.
- LLM returns structured JSON: array of suggestions with file, line, severity, and message.
- Worker maps suggestions to GitHub's position API and calls createReview to post inline comments.
- Review is stored in Postgres. Metrics updated.

# **7\. Non-functional requirements**

## **7.1 Performance**

- P95 time from webhook receipt to first comment posted: under 60 seconds.
- System must handle at least 50 concurrent PR reviews without degradation.
- LLM API calls must have a 30-second timeout with graceful fallback (skip file, log error).

## **7.2 Reliability**

- Webhook handler must return HTTP 200 within 2 seconds (offload all work to the queue).
- Failed review jobs must retry up to 3 times with exponential backoff.
- Dead-letter queue for jobs that fail all retries - alert on accumulation.
- Graceful degradation: if the LLM API is down, skip the review and post a status comment.

## **7.3 Security**

- All webhook payloads verified with HMAC-SHA256 using the GitHub App secret.
- LLM API key stored in environment variables, never in source code or logs.
- The bot must never store or log the full source code content of reviewed files.
- Rate limit LLM API calls per repo to prevent accidental runaway costs.

## **7.4 Observability**

- Structured JSON logging (request ID, repo, PR number, duration, error if any).
- Per-repo metrics: reviews triggered, comments posted, acceptance rate, LLM API cost estimate.
- Simple admin dashboard (React) showing recent reviews and aggregate stats.

# **8\. Milestones & timeline**

| **Phase**                | **Scope**                                                                                 | **Target** |
| ------------------------ | ----------------------------------------------------------------------------------------- | ---------- |
| **Phase 1 - Core loop**  | GitHub App registration, webhook server, diff fetching, LLM call, inline comments posted. | Week 1-2   |
| **Phase 2 - Robustness** | Job queue, retries, rate limiting, HMAC verification, error handling.                     | Week 3     |
| **Phase 3 - Config**     | .reviewbot.yml parsing, ignore paths, focus modes, language detection.                    | Week 4     |
| **Phase 4 - Metrics**    | Reaction tracking, Postgres storage, acceptance rate metric.                              | Week 5     |
| **Phase 5 - Dashboard**  | Simple React UI showing per-repo stats and recent review history.                         | Week 6     |
| **Phase 6 - Polish**     | Performance tuning, cost controls, README, live demo deployment.                          | Week 7-8   |

# **9\. Risks & mitigations**

| **Risk**                                         | **Likelihood** | **Mitigation**                                                                                                    |
| ------------------------------------------------ | -------------- | ----------------------------------------------------------------------------------------------------------------- |
| High false-positive rate erodes trust in the bot | Medium         | Tune system prompt iteratively. Track and act on acceptance rate. Allow per-repo focus mode to reduce scope.      |
| LLM API latency or downtime delays reviews       | Medium         | Async queue decouples receipt from processing. Graceful degradation posts a status comment if LLM is unavailable. |
| Runaway LLM costs on large repos                 | Low            | Per-repo daily token budget with alerting. Skip files over 500 changed lines.                                     |
| GitHub API rate limits hit on large PRs          | Low            | Use the GitHub App's per-installation rate limit (5000 req/hr). Batch diff requests where possible.               |
| Sensitive code exposed to third-party LLM API    | Medium         | Document clearly in README. Future: support local/self-hosted LLM option.                                         |

# **10\. Success metrics**

- Time to first comment: P95 under 60 seconds from PR open event.
- Suggestion acceptance rate: at least 40% of bot comments result in a code change or explicit acknowledgment within 7 days.
- Review coverage: at least 90% of eligible PRs receive a review (not skipped due to errors or limits).
- Engineer satisfaction: quarterly survey score of 3.5/5 or higher for usefulness of bot feedback.
- Cost efficiency: LLM API cost per review under \$0.05 on average.

# **11\. Open questions**

- Should the bot block merging (as a required status check) or remain advisory only? Recommend: advisory-only for MVP.
- Which LLM provider should be the primary? Evaluate Anthropic Claude vs OpenAI GPT-4o on code review quality before launch.
- Should we support GitHub Enterprise (self-hosted) in the initial release, or cloud-only?
- How should the bot handle PRs in non-English codebases with non-English comments?
- Do we want to offer a SaaS version of this tool (hosted bot) or keep it self-hosted only?

_This document is a living draft. All requirements subject to change based on discovery and feedback. Last updated June 15, 2026._