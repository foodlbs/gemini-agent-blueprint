# LinkedIn post

Strategy: Different voice from Twitter — paragraph-led, measured, all 5 lessons listed. One CTA at the bottom. Hashtags at the very end (LinkedIn's algorithm rewards 3-5 specific hashtags).

Char limit: LinkedIn allows 3,000; this is ~1,500 (sweet spot for engagement).

---

## Post

```
On April 15 I deployed v1 of an AI agent designed to find new AI releases, write articles about them, and publish to Medium.

It deployed cleanly. Cloud Scheduler triggered hourly. Cloud Run responded HTTP 200. In three weeks of running, it produced zero articles.

The cause wasn't a bug in the prompts or the model. It was an architectural mismatch I hadn't seen until production made it visible: the agent had two human-approval gates over Telegram, humans take roughly 24 hours to tap a button, and Cloud Run requests cap at 60 minutes. Every cycle timed out and lost its state.

Five lessons from rebuilding it on Google's Gemini Agent Platform (ADK 2.0 + Vertex AI Agent Runtime):

→ 24-hour human-in-the-loop needs a pause/resume primitive, not a request-timeout extension. ADK's RequestInput is a suspended generator — the pause writes state to durable storage and releases the request.

→ Spike before committing to a Beta SDK. One day of disposable validation scripts caught a routing gotcha that would have cost a week mid-build.

→ LLMs should produce text, not typed data. Move parsing to a function node — your contract gets a test surface and your retries cost nothing.

→ Don't put binary blobs in LLM tool history. Image bytes accumulating across two Imagen calls blew the 1M-token cap and killed the workflow silently.

→ Fan-out tuples don't barrier. Build a JoinFunctionNode primitive for explicit fan-in if you need it.

Full write-up: <MEDIUM_URL>
Working code (MIT, fork-friendly): github.com/<your-handle>/gemini-agent-blueprint

#AI #GoogleCloud #GeminiAI #VertexAI #SoftwareEngineering #BuildInPublic
```

---

## Posting tips

- LinkedIn shows ~3 lines + "see more" before truncating in feed. The hook ("In three weeks of running, it produced zero articles.") needs to land in those first lines.
- Don't post the article URL as a separate "first comment" — LinkedIn's algorithm penalizes that pattern. Inline it.
- The 6 hashtags at the end are intentional: 3-5 is optimal, 6 is the upper end without diminishing returns.
- Best time to post (EST): Tue-Thu 8am-10am or 4pm-6pm. Avoid Monday mornings and Friday afternoons.
