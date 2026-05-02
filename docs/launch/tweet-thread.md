# Tweet thread (5 tweets)

Strategy: Hook + 3 punchy lessons (curated for shareability) + CTA. The 2 unused lessons (Spike before Beta, Make LLM produce text) live in the article.

Post the thread by replying to your own tweets — Tweet 2 replies to Tweet 1, Tweet 3 replies to Tweet 2, etc. Twitter's threading UI handles this if you click "Add another Tweet" on the compose screen.

---

## Tweet 1 — Hook

```
On April 15 I deployed v1 of an AI agent that polls AI release sources, writes articles, and posts them to Medium.

It deployed cleanly. Scheduler triggered hourly. Cloud Run returned 200.

In three weeks it produced ZERO articles.

Here's what I learned rebuilding it 🧵
```

Char count: ~270 (under 280)

---

## Tweet 2 — Lesson 1 (architectural insight)

```
Lesson 1: 24-hour human-in-the-loop is incompatible with serverless request models.

My agent had Telegram approval gates. Humans take ~24h. Cloud Run requests cap at 60 min.

The fix: ADK 2.0's RequestInput pauses the workflow as a *suspended generator* — no HTTP request held.
```

Char count: ~280

---

## Tweet 3 — Lesson 4 (war story)

```
Lesson 2: Don't put binary blobs in your LLM's tool history.

Image-gen was an LlmAgent calling Imagen as a tool. The 2nd call returned the prompt PLUS the bytes of the 1st image still in tool history.

1.2M tokens. Hit the 1M cap. Died silently.

Fix: function node, not LlmAgent.
```

Char count: ~280

---

## Tweet 4 — Lesson 5 (concrete technical)

```
Lesson 3: ADK 2.0's tuple fan-out is fan-out only — there is no fan-in.

I had image+video gen parallel via tuple, then a "gather_assets" node to wait for both.

Video was fast. Image was slow. Gather ran on first arrival.

I built JoinFunctionNode: counter-gated, fires on N arrivals.
```

Char count: ~280

---

## Tweet 5 — CTA

```
Two more lessons in the article — including why I spiked for a day before touching a Beta SDK, and why my LLMs now produce TEXT and let function nodes do the parsing.

Full write-up + working code (MIT, fork-friendly):

📖 <MEDIUM_URL>
⚙️ github.com/<your-handle>/gemini-agent-blueprint
```

Char count: ~280 (will be under once URLs are real and shorter)

---

## Posting tips

- Tweet 1's emoji 🧵 signals "thread incoming"
- For Tweet 5, post AFTER the article goes live so the URL is real
- After the thread is live, quote-retweet Tweet 1 ~24h later with "If this resonated…" — Twitter algorithm rewards engagement on your own threads
