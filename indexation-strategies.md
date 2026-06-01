# Indexation Strategies

How the indexer gets client URLs crawled by Googlebot. Core principle: **you cannot push a URL into Google's index — you can only trigger a crawl and hope Google keeps it.** Every strategy below is a *crawl-trigger*. Indexing = crawl (we control this) + Google's quality decision (we don't). This is why no honest index rate is ever 100%.

We use three complementary strategies. They are not redundant — each hits a different part of Google's crawl machinery.

| Strategy | Speed | Cost to us | Leaves durable trace? | Decay/risk | Role |
|---|---|---|---|---|---|
| Sitemap hubs | 1–5 days | Cheap (own domains) | ✅ Yes — the link | Low, we control it | The workhorse |
| WebSub (RSS) | 1–3 days | ~Free | ❌ No (notification only) | Medium, mostly ignored now | Cheap speed nudge |
| Indexing API | Hours | Quota (scarce, bannable) | n/a (it's a push) | High — account churn | The accelerant |

---

## 1. Sitemap Hubs (the workhorse)

### Why a sitemap alone can't do it
A sitemap may only list URLs for a property you've **verified ownership of** in Search Console. We don't own client URLs, so we can't put them in a sitemap directly — Google drops cross-domain entries. The sitemap can only point Google at **our own pages.**

### The two-step mechanism
```
our sitemap (lists OUR hub pages)
      │  ← sitemap's job: get Google to crawl our hub pages fast
      ▼
our hub page on our owned domain
      │  ← hub page's job: contain the client URL as an outbound link
      ▼
client's target URL  ← Google discovers it by following the link
```
- **Sitemap** = delivery mechanism. Makes Googlebot reliably/quickly crawl our hub pages (they're on a verified property, so we can ping/resubmit and watch crawl status).
- **Hub page** = carrier. The client URL reaches Google as an **outbound link** on a page Google crawls.

Sitemap gets Google *to our page*; the link on that page gets Google *to the client URL*. Both halves required.

### Hub page design: contextual, not plain link-lists
A bare list of outbound links is the textbook link-farm footprint — crawled once, flagged low-value, then rarely recrawled (which kills the mechanism, since hubs only work if **frequently recrawled**). Worse, thousands of identical link-list pages share a fingerprint and get devalued *as a pool, all at once*.

**Each client URL is embedded in unique, topically-coherent generated text.** The decisive reason is footprint longevity, not crawl priority — unique pages don't fingerprint together, which keeps the pool alive longer (directly lowering our #1 cost: pool replenishment). Pull the snippet from the target URL's own title/meta description so the context is topically coherent. Don't over-engineer it into publishable articles — just enough uniqueness and plausibility to avoid fingerprinting and pass spam classifiers.

### Links are permanent — never remove after indexing
**Indexed ≠ permanently indexed.** Google re-evaluates continuously. A URL with no inbound links can be **dropped on the next refresh**. The hub link is often the only signal keeping it discovered. Removing it = converting a durable result back into an unindexed URL, and the appear/disappear churn is itself a strong spam fingerprint.

Scaling lever is **cap and roll**, not delete:
```
Hub page holds N links (~20–50), then it's "sealed"
  → new URLs go to a fresh hub page
  → sealed pages keep their links FOREVER (static page, near-zero cost)
  → sitemap keeps listing them so they stay crawled
```
What we retire on old hubs is *crawl pressure* (move to a low-priority "maintenance" sitemap), never the link itself.

> Capacity note: hub-page count grows with **cumulative** URLs ever submitted, not active volume. Domain pool must scale accordingly.

---

## 2. WebSub / RSS (the cheap speed nudge)

### The one that works vs. the dead one
- **Legacy RSS ping** (`blogsearch.google.com/ping`, old aggregators) — dead since ~2011. Mostly ignored today. The "ping 200 services" approach is theater and adds footprint for nothing.
- **WebSub** (formerly PubSubHubbub) — a live pub/sub protocol Google still participates in. Real-time **push**, not "please poll me sometime." This is the only RSS-family method that still does anything.

### Mechanism
```
Publisher (us)  ──notify──►  Hub  ──push──►  Subscribers (incl. Google)
     │                        │
  our feed.xml          fans out the update
```

**Step 1 — publish a feed declaring its hub** (the `<link rel="hub">` is mandatory; without it nothing pushes):
```xml
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Marketing Notes</title>
  <link rel="self" href="https://ourdomain.com/feed.xml"/>
  <link rel="hub" href="https://pubsubhubbub.appspot.com/"/>
  <updated>2026-05-31T12:00:00Z</updated>
  <entry>
    <title>Some plausible title</title>
    <link href="https://CLIENT-TARGET-URL.com/page"/>   <!-- URL we want crawled -->
    <id>https://CLIENT-TARGET-URL.com/page</id>
    <updated>2026-05-31T12:00:00Z</updated>
    <summary>One contextual sentence about the link.</summary>
  </entry>
</feed>
```
The entry `<link href>` is the **client target URL** — the feed's advantage over a sitemap is it can list URLs we don't own.

**Step 2 — notify the hub** (the actual trick):
```bash
curl -X POST https://pubsubhubbub.appspot.com/ \
  -d "hub.mode=publish" \
  -d "hub.url=https://ourdomain.com/feed.xml"
```
The hub re-fetches the feed, diffs it, and pushes new entries to subscribers including Google → prompts a crawl.

**Step 3 — the part people get wrong:** the hub re-fetches and verifies the change is real. **Deploy the feed change first, then POST** (order matters). Feed must be valid, reachable, 200, content-type `application/atom+xml`, or the notification is silently dropped.

### Scale rules
1. **Many small rolling feeds**, not one giant feed. Keep each to recent items (10–50), roll old ones off. A 5,000-entry feed looks nothing like a real feed → distrusted.
2. **One feed per domain, topically coherent** (same footprint rule as hubs).
3. **Hub choice:** public hub for POC (zero setup); self-hosted for production (isolates footprint, no dependency on a shared endpoint that can vanish or rate-limit).

### Honest expectation
WebSub reliably triggers a *crawl attempt*, fast. It does **not** guarantee indexing and leaves **no durable trace** — so it's never standalone. Fire it at T+0 *alongside* the sitemap hub (WebSub = speed, hub link = durability). Cheap fire-and-forget accelerant; never the primary engine.

---

## 3. Indexing API (the accelerant)

### What it is
Google's Indexing API officially supports only `JobPosting` and `BroadcastEvent` structured data. In practice it's hammered with **any** URL type to trigger a near-instant crawl. This is **against Google's ToS** — projects get throttled/banned — which is the entire reason for an account pool.

### Account pool strategy: many low-volume projects
Detection is largely **per-project rate/volume based**. Spreading thin across many GCP projects, each sipping quota, stays under the radar and never builds an "aggressive non-job submitter" footprint on any single project. Bonus: quota is per-project, so more projects = more total quota for free.

This pairs naturally with the escalation gate (below): since the API only handles *stragglers*, low per-project volume is the traffic shape we have anyway.

The cost isn't quota — it's **lifecycle management**. Each project is a first-class entity with state:
```
Project pool entry:
  id, daily_quota, used_today, age, warmth,
  health_score (from recent success rate),
  status: warming | active | throttled | banned
```
Orchestrator pulls the *healthiest under-quota* project per submission; a background job warms new projects and retires dying ones. Same "decaying inventory with health scores" pattern as the domain pool and proxy pool — **build that abstraction once.**

---

## Orchestration: escalate, don't blast

Gate the **scarce/bannable** resource (API quota). Free-pour the cheap ones. Cheap mechanisms don't compete with each other for a budget — they only compete with the expensive one.

```
URL submitted
  │
  ├─ T+0:  add link to sitemap hub  (#1, durability anchor)
  │        + WebSub ping            (#2, speed nudge)
  │        ↑ both ~free to fire and complementary — fire together, never sequence
  │
  ├─ Verification poll @ T+48h
  │        indexed? → done, stop spending
  │        not?     → escalate
  │
  ├─ T+48h: fire Indexing API (#3) from the pool  ← spend scarce quota only on stragglers
  │
  ├─ Re-poll @ 96h, 7d
  │        not indexed? → rotate: new hub domain, fresh feed, different API project
  │
  └─ T+14d: mark failed / report "crawled-not-indexed"
```

Spending API quota only on the ~40% the free channels miss roughly **doubles effective daily capacity** per account.

> The entire escalation logic is meaningless without a trustworthy verifier. Build the verifier first.

---

## The domains

Hub pages need **frequently-crawled** domains, not high-authority ones. Crawl frequency ≠ authority.

- **Crawl frequency is driven by:** freshness/update cadence (publish often → crawled often), baseline trust, clean technical setup. **Not** by DR, rankings, or traffic. A crawled-hourly DR-15 blog beats a static DR-60 site.
- **Fresh domains:** work, but have a cold-start (slow/shallow crawl for weeks). Need a **warming pipeline** that's always preparing the next batch so we never depend on a cold domain.
- **Aged/expired domains:** crawled frequently from day one (no warming), but cost money and many are **burned** (prior spam, penalties, toxic links). Requires a vetting subsystem (index status, Wayback history, spam signals).

### Tiered, blended pool
| Tier | Source | Role |
|---|---|---|
| A | Aged/expired, vetted clean | Workhorses for new/important URLs |
| B | Fresh, warmed 6–8 wks | Bulk capacity (always have a batch warming) |
| C | Aging maintenance | Hold sealed hub pages cheaply |

**We own these domains → we get Search Console on them for free.** Use observed crawl frequency (URL Inspection / crawl stats on our own hubs) as the ground-truth **health score** for the domain pool. A domain whose crawl rate drops is dying → demote to C or retire.

---

## Verification: how to check if a URL is indexed

The rule that governs everything: **trust positives, distrust negatives.**

### If we own the site (dummy POC) → URL Inspection API
Ground truth, straight from Google. Returns `coverageState` + last-crawl time. No proxies, no CAPTCHAs, no false negatives. Limits: requires SC verification, ~2,000 queries/day per property. **For the POC, use nothing else** — and it gives the crawled-vs-indexed split needed to separate "mechanism worked" from "content too thin."

### If we don't own the site (production) → combine SERP signals into a confidence classifier
```
site: hit              → INDEXED (high confidence)   ← trust it
site: miss + phrase hit → INDEXED (medium)
both miss              → UNCONFIRMED (low) ≠ "not indexed"
```
- **`site:exacturl`** — cheap, trustworthy *positive*; unreliable *negative* (routinely returns nothing for indexed fresh/deep/low-authority pages — exactly our population).
- **Exact unique-phrase query** — tiebreaker for `site:` misses; needs a unique string from the page.
- **`both miss` = "recheck later," not "failed."** Only escalate after N consecutive misses over time — treating a false negative as failure burns API quota, our scarcest resource.

### Cost structure (production)
Needs **residential proxies** (datacenter gets CAPTCHA'd on Google search) + a **CAPTCHA solver**. Real per-check marginal cost → potentially the largest COGS line at agency volume. Therefore:
- Cache aggressively (once INDEXED high-confidence, taper rechecks to weekly).
- Decaying poll cadence (T+2d, 4d, 7d, 14d), not continuous.
- Lean on cheap `site:` positives; only misses trigger the expensive phrase query.

---

## Reality check

- The **software is ~20%**; the business is **pool logistics** (domains, API projects, proxies — all constantly decaying) and **footprint management.**
- The MVP (dummy sites + URL Inspection API) proves the **mechanisms** work. It does **not** prove the **business** works — production has no Search Console on client URLs, so the scraping verifier is most of the real engineering.
- Build order: **verifier → inventory/health abstraction → contextual hubs → escalation orchestrator.**
