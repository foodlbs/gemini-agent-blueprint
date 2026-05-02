# My AI agent deployed cleanly and never wrote a single article. Here's what I learned rebuilding it on Google's Gemini Agent Platform.

*Five engineering lessons from shipping a production graph workflow with 24-hour human-in-the-loop on ADK 2.0.*

On April 15, 2026, I deployed v1 of an AI agent designed to find new AI releases, write articles about them, and post them to Medium. It deployed cleanly. The Cloud Scheduler triggered hourly. Cloud Run responded with HTTP 200. Logs streamed normally.

In three weeks of running, it produced exactly zero articles.

The reason wasn't a bug in the agent's reasoning, the prompts, or the LLM. It was an architectural mismatch I hadn't seen until production made it visible: the agent had two human-approval gates, and humans on Telegram take up to 24 hours to tap a button. Cloud Run requests max out at 60 minutes. Every cycle hit the timeout, lost its state, and the user (me, on my phone) was left tapping Approve into the void.

Here are five lessons from rebuilding it on Google's Gemini Agent Platform — what worked, what blew up at runtime, and what the design looks like at the end. The full code is at <REPO_URL>.

## Context — what this thing actually does

Once an hour, the agent runs a single end-to-end cycle. It polls 7 sources for new AI releases (arXiv, GitHub Trending, HuggingFace Models, HuggingFace Papers, Anthropic news, Hacker News, generic RSS), triages the candidates against memory of what it has covered before, and asks me on Telegram whether to proceed with the top pick. That's HITL gate #1. On approve, it fans out to three parallel research agents — one fetching docs, one pulling repo metadata from GitHub, one searching for context and reactions. An Architect produces a section outline; a Drafter and Critic loop write the article (max 3 iterations). It generates cover art with Imagen and a 6-second demo video with Veo. Optionally, it generates a starter GitHub repo for whatever release it covered. Then it asks me again on Telegram whether to publish — HITL gate #2 — and on approve, posts to Medium.

![5-phase workflow diagram](path/to/mermaid-export.png)

The combination of multi-step LLM workflow + parallel research + 2 HITL gates + asset generation + dual publish targets is what makes this interesting. Each piece is solved in isolation; the integration is where the lessons came from.

## Lesson 1 — 24-hour HITL is incompatible with serverless request models

The original v1 design was simple. Cloud Run handles the HTTP request from Cloud Scheduler. The handler calls into the agent. The agent posts a Telegram message and waits for the callback. The callback fires; the agent continues; the request returns 200. Clean.

The problem is the word *waits*. Cloud Run requests cap at 60 minutes. Telegram replies from a human cap at "whenever I check my phone next," which during a normal weekday is 4-12 hours and on a weekend can be 24+. The two numbers do not overlap.

I tried three things that were wrong before I understood the shape of the fix.

**Extend the request timeout.** No — 60 minutes is the platform cap on Cloud Run. There's nothing to extend.

**Background the wait.** I tried spawning the wait into an asyncio task and returning 200 immediately. The handler returns, but the background task dies the moment the container scales to zero. Cloud Run is not a persistent process.

**Stash state in Redis and poll.** This works mechanically — drop the workflow state to Redis, return 200, have a separate cron job pick it up. But you've now hand-rolled a state machine on top of a graph workflow. Every node becomes a save-point. Every transition becomes a serialization boundary. The agent code stops being agent code and starts being plumbing.

The right answer is ADK 2.0's `RequestInput`. The workflow yields a `RequestInput` event keyed to a stable `interrupt_id`. ADK persists the workflow state, releases the request, and the container can scale to zero. When the human taps the Telegram button hours later, the bridge service receives the callback, looks up the `interrupt_id`, and resumes the session by sending a `FunctionResponse`. No request is held. No state machine to maintain. The pause/resume is a primitive at the framework layer.

![HITL sequence diagram](path/to/sequence-diagram.png)

**What this means for you:** if your agent has any HITL step that crosses a coffee break, you need a pause/resume primitive, not a request-timeout extension. Think about whether your framework gives you that primitive before you commit to an architecture.

## Lesson 2 — Spike before committing to a Beta SDK

ADK 2.0 was at `2.0.0b1` when I started. Beta means breaking changes between minor versions, thin docs, and sample code that confidently demonstrates patterns the framework doesn't actually support. I almost charged in anyway. Then I lost a half-day to one wrong assumption and spent the next day on four spike scripts instead.

**Spike 1 — Does `Workflow(edges=[...])` with function nodes + LlmAgents work?** Yes, but routes are emitted by `ctx.route`, NOT `Event(output=...)`. Sample code is misleading.

**Spike 2 — Does `RequestInput` actually pause without holding a request?** Yes, and the resume contract is fiddly: `Part.from_function_response()` does NOT accept an id; build `FunctionResponse(...)` directly.

**Spike 3 — Is managed Memory Bank wired through `Runner(memory_service=...)`?** Yes. `InMemoryMemoryService` for local dev, `VertexAiMemoryBankService` in prod. Same agent code.

**Spike 4 — Can a Telegram callback bridge into `RequestInput` resume?** Yes. `callback_data` is capped at 64 bytes; use prefix encoding with a Firestore lookup for full IDs.

Each spike was throwaway code — a single Python file that exercised one primitive and answered one go/no-go question. I deleted them once they served their purpose.

The Spike 1 gotcha alone would have been brutal in a half-built workflow. The official ambient-expense-agent sample has a routing node that returns `Event(output="AUTO_APPROVE")` — and it works *if* no dict-edge actually depends on routing in that branch. As soon as you add `{"AUTO_APPROVE": next_node}`, the value never matches because routing reads from `ctx.route`, which the sample never sets. You'd debug that for hours.

Spike 2's `FunctionResponse` discovery was similar. The convenience constructor `Part.from_function_response()` takes a dict but silently drops the function-call id, which the resume requires. You have to build `FunctionResponse(id=..., name=..., response=...)` directly and wrap it in a `Part`. Not in the docs. Not in the sample.

**What this means for you:** if you're building on a Beta API, budget 10-15% of your time on disposable validation scripts. The value isn't the code — the code gets thrown away — it's the explicit go/no-go decision before you wire the primitive into something you can't easily rip out.

## Lesson 3 — Make the LLM produce text, not data

ADK supports passing a Pydantic schema as `response_schema` on an LlmAgent. In theory, you get typed structured output for free; the framework handles the parsing. In practice, when the model paraphrases or pluralizes a field name, schema enforcement fails *silently* at the parsing layer. The downstream node receives `[]` or a partial model. The workflow looks healthy; events emit; edges fire; the work is wrong.

I caught it because Triage kept skipping cycles. Investigation: Scout was supposed to produce `candidates: list[Candidate]`. Some runs returned `releases: list[Candidate]` because Gemini felt that "releases" was a more natural word for what it had just enumerated. Schema validation produced an empty list, Triage saw zero candidates, and `route_after_triage` emitted `SKIP`. No error log anywhere. The cycle ended in `record_triage_skip` and looked, in the trace, exactly like a legitimate "nothing interesting today" outcome.

The fix is structural: instead of asking the LLM to produce typed data, ask for **text** in a structured format you can parse yourself.

```python
# Scout's instruction prompt now ends with:
# "Output your ranked candidates as a JSON array inside a markdown
#  ```json fenced block. Each entry must have: title, url, source,
#  score, rationale."
```

A function node — `scout_split` in `nodes/scout_split.py` — reads `state.scout_raw` (the verbatim LLM output), strips the markdown fence, parses the JSON, validates each entry against the `Candidate` Pydantic model, and writes the typed list to `state.candidates`. The same pattern repeats for Architect (`architect_split`) and Critic (`critic_split`).

Three benefits. The contract has a test surface — I can feed it real LLM outputs and assert it parses correctly. Retries are cheap — if a single candidate's JSON is malformed, per-object recovery salvages the rest instead of dropping all 25. And prompt iteration is easier — when I tweak the Scout prompt, I rerun the parser tests, not the whole workflow.

**What this means for you:** LLM-to-typed-state is a contract; contracts deserve their own test surface. A function node parser gives you that. A schema-enforcing LLM call hides failures inside a layer you don't own.

## Lesson 4 — Don't put binary blobs in your LLM's tool history

This was the cleanest war story in the rebuild.

The original `image_asset` was an LlmAgent with Imagen as a tool. The instruction said "generate cover art for this article; produce two prompt variations, generate both, select the better one." Reasonable. It worked the first call.

The second call returned a context-length error. No specific tool was named. No specific input was named. Just a generic "exceeded model context length" with a token count of 1.2 million.

I spent three hours convinced this was a prompt-bloat issue. Was Architect's outline too long? Was the Critic's verdict compounding into the Drafter's history? Was something looping? I read prompts. I added length asserts. I diff'd state between iterations. Nothing was bigger than it should have been.

Then I logged actual token counts at each LlmAgent call site and saw it: the second Imagen call was carrying the bytes of the first generated image in its tool history. PNG bytes encode as base64 inside `function_response`. A 200KB image becomes ~270K characters becomes ~70K tokens. Two of those plus the agent's working context cleared the 1M cap with room to spare.

The fix was to take the LLM out of the loop entirely.

```python
# Before — image_asset was an LlmAgent
image_asset = LlmAgent(
    name="image_asset",
    tools=[generate_image, generate_image_variation],
    instructions="Generate cover art and a variation; pick the better one.",
)

# After — image_asset_node is a function node
def image_asset_node(node_input, ctx):
    briefs = ctx.state.get("image_briefs") or []
    assets = []
    for brief in briefs:
        png_bytes = imagen.generate(prompt=build_prompt(brief))
        url = upload_to_gcs(png_bytes, slug=f"{ctx.session.id}/{brief.position}.png")
        assets.append(ImageAsset(position=brief.position, url=url, ...))
    ctx.state["image_assets"] = assets
```

The LLM never sees the bytes. Imagen runs deterministically inside the function node. The bytes go straight to GCS. State holds a URL, which is 60 characters.

**What this means for you:** any tool that returns binary data — images, PDFs, audio, embedding tensors — belongs in a function node, not an LlmAgent's tool list. The LlmAgent's job is reasoning over text. The function node's job is moving bytes around. Keep them separate, or pay the token cap eventually. [Full code in the repo](<REPO_URL>) — `nodes/image_assets.py` is the function node version.

## Lesson 5 — Fan-out tuples don't barrier; build a JoinFunctionNode for fan-in

The asset chain originally looked clean. Image generation and video generation are independent — fan them out in parallel, then have a barrier node wait for both.

```python
(architect_split, drafter, critic_llm, critic_split, route_critic_verdict, {
    "ACCEPT": (image_asset, video_asset_or_skip),  # tuple = fan-out
}),
((image_asset, video_asset_or_skip), gather_assets),  # ← I assumed this barriers
```

It didn't barrier. Video generation is fast (no LLM, just a Veo API call returning a URL); image generation is slow (Imagen + GCS upload). `gather_assets` ran on the *first* arrival, not the last. The Editor saw `image_assets=[]` and asked me to revise an article whose images hadn't finished generating.

ADK 2.0's tuple fan-out is **fan-out only**. There is no built-in fan-in barrier. I read the source to confirm.

I fixed it two ways together.

**Sequential the asset chain.** Image first, then video, then gather_assets — `(image_asset_node, video_asset_or_skip, gather_assets)`. Video is fast enough to not add meaningful latency, and the dependency makes the barrier trivial because there's only one upstream path.

**`JoinFunctionNode` for genuine parallelism.** The research phase has three parallel researchers (docs, GitHub, contextual) that take 20-40 seconds in parallel and ~90 seconds sequential. Sequentializing those would hurt. So I built a barrier primitive:

```python
class JoinFunctionNode(FunctionNode):
    """Counter-gated fan-in. Stays WAITING until all N predecessors arrive."""
    wait_for_output: bool = True


def _gather_research_impl(node_input, ctx):
    n = ctx.state.get("gather_research_call_count", 0) + 1
    ctx.state["gather_research_call_count"] = n
    if n < 3:
        return Event()  # WAITING — predecessors can re-trigger.
    # All 3 researchers have arrived. Merge and proceed.
    ...

gather_research = JoinFunctionNode(func=_gather_research_impl, name="gather_research")
```

The trick is `wait_for_output=True` plus the counter. When the function returns an `Event` with no `output`, ADK's `BaseNode` keeps the node in `WAITING` state, and the next predecessor's completion re-triggers it. On the third call the counter check passes and the node emits its real output.

**What this means for you:** ADK 2.0's tuple fan-out is fan-out only; it does NOT come with a fan-in. Read the source if you're unsure. If you need a barrier, build it — `JoinFunctionNode` is a few lines of class definition and the pattern is reusable everywhere you have multiple unconditional incoming edges.

## Closing

Five lessons, one rebuild. The pattern across all of them: graph workflows on a Beta SDK reward you for being explicit. Don't trust schema enforcement to catch field-name drift; parse the text. Don't trust tuple fan-out to barrier; build the barrier. Don't trust an LlmAgent to handle binary blobs; use a function node. Don't trust a Cloud Run handler to wait 24 hours; yield, persist, resume.

Building in public — follow [GitHub](https://github.com/<your-handle>), [Twitter](https://twitter.com/<your-handle>), or [LinkedIn](https://linkedin.com/in/<your-handle>) if useful. Questions, corrections, or your own war stories — happy to hear them.

## What's in the repo, what's not

The full agent is at <REPO_URL> — MIT-licensed, ~170 tests, Terraform for the GCP infrastructure, a complete deploy runbook, and a ~6,600-word architecture doc walking through every node.

What it includes:
- The working agent end-to-end — Scout, Triage, two HITL gates, three parallel researchers, Architect, Drafter/Critic loop, Imagen + Veo asset generation, optional GitHub repo creation, Medium publish.
- Vertex AI Agent Runtime running the workflow, Cloud Run hosting the Telegram bridge that proxies callbacks into `RequestInput` resumes.
- Memory Bank for cross-cycle topic dedup (default scope: `ai_release_pipeline`).
- All four ADK 2.0 patterns covered above — the exact `JoinFunctionNode` definition, the `RequestInput`/`FunctionResponse` resume contract, the `*_split` parser nodes, the function-node-not-LlmAgent rule for binary tools.

What it doesn't include:
- My GCP project, my secrets, my Telegram chat ID. Everything is parameterized via env vars and a `var.project_name` Terraform variable.
- A maintained OSS product — this is a reference implementation; fork it for your own topic. The README has a "Forking for your own topic" guide.
- Anything proprietary. Models, prompts, infrastructure, pinned versions — all in plain text.

---

*Tags: Google Cloud, Gemini, AI Agents, Vertex AI, Software Engineering*
