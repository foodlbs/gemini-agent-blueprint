# Posting checklist

Tick through this on launch day. Order matters — Medium first because the article URL is needed for the other two.

## Pre-launch (already done by this point)

- [ ] `docs/PRE_PUBLISH_CHECKLIST.md` is fully ticked (secrets rotated, greps clean, smoke tests passing)
- [ ] Public repo `gemini-agent-blueprint` is pushed to GitHub and renders correctly
- [ ] `docs/img/hitl-telegram.png` is committed and the README image renders
- [ ] Mermaid diagrams have been exported to PNG for the article (see "Mermaid → PNG" section below)

## T+0 — Publish to Medium

- [ ] Open https://medium.com/new-story
- [ ] Copy `docs/launch/article.md` content into the Medium editor
- [ ] Replace the 3 `<REPO_URL>` placeholders with the actual GitHub URL
- [ ] Replace `path/to/mermaid-export.png` with uploaded image (drag PNG into Medium editor)
- [ ] Replace `path/to/sequence-diagram.png` with uploaded sequence diagram
- [ ] Set tags: `Google Cloud`, `Gemini`, `AI Agents`, `Vertex AI`, `Software Engineering`
- [ ] Click Publish
- [ ] **Capture the article URL** — needed for the next two steps

## T+5 min — Post tweet thread

- [ ] Open Twitter compose
- [ ] Copy Tweet 1 from `docs/launch/tweet-thread.md`, post
- [ ] Click "Add another Tweet" → paste Tweet 2 → repeat for 3 and 4
- [ ] For Tweet 5: substitute `<MEDIUM_URL>` with the captured Medium URL, then paste + post
- [ ] **Capture the tweet thread URL** (right-click Tweet 1 → Copy link to Tweet)

## T+30 min — Post to LinkedIn

- [ ] Open https://linkedin.com/feed
- [ ] Click "Start a post"
- [ ] Copy `docs/launch/linkedin-post.md` content (just the post, not the tips)
- [ ] Substitute `<MEDIUM_URL>` with the captured Medium URL
- [ ] Hit Post
- [ ] **Capture the LinkedIn post URL**

## T+1h — Update README CTAs

- [ ] In your local clone, replace all 4 `<MEDIUM_URL>` in `README.md` with the Medium URL
- [ ] Replace `<TWITTER_URL>` and `<LINKEDIN_URL>` in `README.md` with the captured URLs
- [ ] Replace 7 `<MEDIUM_URL>` in `docs/ARCHITECTURE.md` with the Medium URL
- [ ] `git add README.md docs/ARCHITECTURE.md && git commit -m "docs: link to launched article + thread + LinkedIn post"`
- [ ] `git push public main`

## T+1h — Cleanup

- [ ] `git rm docs/PRE_PUBLISH_CHECKLIST.md`
- [ ] `git rm -r docs/launch/`
- [ ] `git rm -r docs/superpowers/` (delete the brainstorming history; the spec + plan are no longer needed)
- [ ] Create `docs/PRESS.md` with the 3 captured URLs (Medium, Twitter, LinkedIn) — this is the "where to find me" for repo visitors
- [ ] `git add docs/PRESS.md && git commit -m "chore: post-launch cleanup; add PRESS.md"`
- [ ] `git push public main`

---

## Mermaid → PNG export (one-time, before T+0)

Medium does not render Mermaid natively. Export both diagrams as PNG:

1. **5-phase flowchart** — open https://mermaid.live → paste the `flowchart LR` block from `README.md` → click "Actions" → "PNG" → save as `docs/img/article-flowchart.png` (used in Section 2 of the article)

2. **HITL sequence diagram** — open https://mermaid.live → paste the `sequenceDiagram` block from `docs/ARCHITECTURE.md` Section 5 → click "Actions" → "PNG" → save as `docs/img/article-sequence.png` (used in Section 3 of the article)

These PNG files do NOT get committed to the public repo — they're for upload into Medium only. Either keep them in a local `tmp/` or delete after publish.
