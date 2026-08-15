"""POC: does k7e save tokens (and speed up retrieval) vs raw documents?

Simulates how chat-agent answers a question two ways:

  WITHOUT k7e  -> read the raw source document into the model context.
  WITH    k7e  -> call the MCP `search_wiki` tool and read the compact,
                       compiled page (or just its snippet).

For each sample it ingests a realistic, verbose raw document, waits for the
compiled wiki page, then counts tokens (tiktoken) for: raw doc, compiled page,
search snippet — and times the `search_wiki` retrieval. Prints a comparison.

Run with the stack up::

    python scripts/poc_token_savings.py

Note: it ingests a few new pages (cleanup is easy via DELETE /items/{slug}).
"""

from __future__ import annotations

import asyncio
import time

import httpx
import tiktoken

from k7e_mcp.client import get_wiki_page, search_wiki

API = "http://localhost:8001"
HEADERS = {"X-User-Id": "poc", "X-User-Roles": "reader"}
ENC = tiktoken.get_encoding("cl100k_base")


def toks(text: str) -> int:
    return len(ENC.encode(text or ""))


async def list_slugs() -> set[str]:
    """Current published item slugs — used to detect a freshly-compiled page."""
    async with httpx.AsyncClient(base_url=API, headers=HEADERS, timeout=15) as c:
        r = await c.get("/items")
        r.raise_for_status()
        return {i["slug"] for i in r.json()}


# Realistic, verbose raw documents (the kind chat-agent would otherwise ingest):
# long, redundant, full of chit-chat and boilerplate — like real Confluence
# pages, meeting transcripts and incident threads. A timestamp keeps each run's
# topics unique so the gate doesn't flag them as near-duplicates of prior runs.
def _stamp(text: str, tag: str) -> str:
    return text.replace("__TAG__", tag)


def _samples(tag: str) -> list[dict]:
    return [
        {
            "name": "kafka-lag-incident",
            "query": "why did the notifications consumer lag and how was it fixed",
            "text": _stamp(
                """# INCIDENT THREAD (slack export, __TAG__) - notifications delayed

reminder: this is a raw paste of the slack thread, nobody has cleaned it up.

10:02 user-a: hey is anyone seeing notifications being super delayed? customers complaining
10:03 user-b: lol probably kafka again
10:03 user-a: not funny we have a SEV coming
10:05 user-c: ok looking. consumer group notifications-svc lag is like 2 million and climbing
10:06 user-b: ok that is bad. did we deploy anything
10:07 user-c: no deploy since tuesday
10:08 user-a: customers in #support are mad
10:10 user-c: ok so the notifications consumer is processing but really slowly. each message
   is doing a synchronous call to the templating service and that got slow
10:11 user-b: templating service? why is that in the hot path
10:12 user-c: historical reasons, someone added it last quarter, it renders the email body
10:13 user-a: can we just skip templating
10:14 user-c: no we need the body. but we could batch. or cache. the same 5 templates are
   used for like 90% of messages
10:20 user-c: ok confirmed, templating p99 went from 40ms to 900ms because its own redis
   cache got evicted (someone resized the redis cluster this morning, THAT was the change)
10:22 user-b: omg the redis resize. ok so not us directly
10:25 user-c: restoring the redis maxmemory fixed templating latency, consumer is catching up
10:40 user-c: lag draining, down to 400k
11:10 user-c: lag at zero, recovered

post-incident thoughts (unstructured):
- root cause: redis maxmemory was lowered during an unrelated capacity change, templating
  cache thrashed, templating got slow, notifications consumer (which calls it synchronously)
  slowed down, kafka lag exploded.
- the synchronous call to templating in the consumer hot path is the real fragility
- action: cache rendered templates in the consumer, OR make redis change reviewed, OR
  precompute templates. lots of debate, no firm owner yet.
- also we should alert on consumer lag earlier, we found out from customers not monitoring.
- someone mentioned this is the 3rd redis-related incident this year.
""",
                tag,
            ),
        },
        {
            "name": "vpn-onboarding-guide",
            "query": "how do new engineers get vpn and prod access",
            "text": _stamp(
                """# New Engineer Access & VPN Onboarding (__TAG__) - Confluence, edited 31 times

NOTE: parts of this are out of date. If something does not work ask in #it-help. Do not
DM the IT lead directly she gets too many DMs. This page is the source of truth, allegedly.

Welcome! So you need access. There are several systems and the order matters a bit. Grab
a coffee this takes a while and some steps need approvals that can take a day.

First, VPN. We use the corporate VPN client (not the old one, the old one was deprecated
last year but some laptops still have it, uninstall it). Request VPN access via the access
portal, choose "Engineering VPN" profile. Your manager approves. Then you get an email with
a config file, import it into the client. If it says certificate expired, your cert needs
re-issuing, that is a separate ticket, ugh.

Once on VPN you can reach internal tools: the wiki, jira, the internal dashboards. You can
NOT reach production yet, that is separate.

Production access: this is gated. You need (1) to have completed the security training (the
annoying 45 minute video), (2) manager approval, (3) for prod DB access specifically, a
second approval from the data team because of PII. Prod access is time-boxed, it expires
every 90 days and you re-request, this is on purpose, do not complain it is a compliance thing.

For deploys you need pipeline access which is a github team membership, ask your onboarding
buddy to add you to the eng-deployers team. You also need to be in the oncall rotation tool
but not until after your first month.

Common gotchas: VPN split tunneling means some things route weird, if a tool is slow try
toggling full tunnel. Also the VPN drops if your laptop sleeps, just reconnect. Also if you
are remote in certain regions there is a separate gateway, ask IT. Also 2FA is required for
everything, set up the authenticator app on day one or you will be sad.

That is mostly it. There is also badge access for the office, and the parking app, and the
expense tool, but those are not engineering specific, HR covers them in orientation.
""",
                tag,
            ),
        },
        {
            "name": "search-adr-meeting",
            "query": "what search backend did we choose and why",
            "text": _stamp(
                """# Architecture Decision Meeting - Search Backend (__TAG__) - raw transcript

This is an auto-transcript so names are approximate and there is filler. ~45 min meeting.

facilitator: ok thanks everyone for joining, agenda is to decide the search backend for the
   knowledge platform. we have been going back and forth in the doc. let us just decide today.
person1: right so the options on the table are basically postgres full text, elasticsearch,
   or a vector db like pgvector or a dedicated one.
person2: can you remind everyone the requirements
person1: sure. we need keyword search, we need semantic / vector search for the compiled
   pages, permission filtering, and it should be cheap to operate at our scale which is not
   huge, like tens of thousands of pages not billions.
person3: elasticsearch is powerful but it is a whole thing to operate, we would need someone
   to own the cluster, and it is expensive.
person2: agreed, ES feels like overkill and ops burden.
person1: postgres full text is basically free since we already run postgres. but it does not
   do vector search natively, well, without pgvector.
person3: pgvector is mature now though. we could do hybrid: postgres tsvector for keyword,
   pgvector for embeddings, in the same database. one system to run.
person2: i like that. keeps it simple, one datastore, transactional with our content.
facilitator: concerns?
person3: pgvector ANN at very large scale is not as good as dedicated vector dbs, but we are
   not at that scale and probably never will be for internal knowledge.
person1: and if we ever are, we can move. the retrieval interface can hide the backend.
person2: also doing search in-process for MVP is fine, we do not even need pgvector on day one,
   we can compute cosine in python and add pgvector when volume grows.
facilitator: ok so proposal: hybrid keyword + vector, postgres-based, pgvector as the scale
   path, in-process cosine acceptable for MVP. objections? ... none. decided.
person3: i will write the ADR.
facilitator: thanks. also reminder the offsite is next month. ok bye.
""",
                tag,
            ),
        },
    ]


SAMPLES = _samples(str(int(time.time())))


async def upload(text: str, name: str) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{API}/ingest/upload",
            files={"file": (f"{name}.md", text, "text/markdown")},
        )
        r.raise_for_status()
        return r.json()["raw_document_id"]


async def wait_for_new_hit(
    query: str, known: set[str], timeout_s: float = 180.0
) -> dict | None:
    """Poll search until THIS upload's page is compiled, mirrored and searchable.

    The v2 OKF pipeline is autonomous (no gate) and turns one source into several
    typed pages, so we detect readiness exactly the way chat-agent would: search
    by the question and wait for a fresh (previously-unseen) page to surface.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hits = await search_wiki(query, limit=5, base=API)
        fresh = [h for h in hits if h["slug"] not in known]
        if fresh:
            return fresh[0]  # top-ranked freshly-compiled page for this question
        await asyncio.sleep(3)
    return None


async def main() -> None:
    print("Ingesting verbose raw documents and waiting for compiled pages...\n")
    known = await list_slugs()
    rows = []
    for s in SAMPLES:
        await upload(s["text"], s["name"])
        hit = await wait_for_new_hit(s["query"], known)
        if hit is None:
            print(f"  ! {s['name']}: timed out waiting for compile")
            continue
        page = await get_wiki_page(hit["slug"], base=API)
        if page is None:
            print(f"  ! {s['name']}: page not retrievable ({hit['slug']})")
            continue
        known.add(hit["slug"])  # don't re-detect it for the next sample

        raw_t = toks(s["text"])
        page_t = toks(page["markdown"])

        # Time the retrieval the agent would actually do.
        t0 = time.perf_counter()
        hits = await search_wiki(s["query"], limit=3, base=API)
        latency_ms = (time.perf_counter() - t0) * 1000
        snippet_t = toks("\n".join(h["snippet"] for h in hits))

        rows.append(
            {
                "name": s["name"],
                "raw": raw_t,
                "page": page_t,
                "snippet": snippet_t,
                "ms": latency_ms,
            }
        )
        print(
            f"  {s['name']:<22} raw={raw_t:>5}  compiled_page={page_t:>5}  "
            f"search_snippet={snippet_t:>4}  (search {latency_ms:.0f} ms)"
        )

    if not rows:
        print("\nNo samples completed — is the stack up?")
        return

    raw = sum(r["raw"] for r in rows)
    page = sum(r["page"] for r in rows)
    snip = sum(r["snippet"] for r in rows)
    avg_ms = sum(r["ms"] for r in rows) / len(rows)

    def pct(a: int, b: int) -> str:
        return f"{(1 - b / a) * 100:.0f}% fewer" if a else "n/a"

    print("\n" + "=" * 64)
    print(f"Across {len(rows)} topics, context tokens to answer the question:")
    print(f"  raw source documents : {raw:>6} tokens   (baseline, no k7e)")
    print(f"  compiled wiki pages  : {page:>6} tokens   ({pct(raw, page)})")
    print(f"  search snippets only : {snip:>6} tokens   ({pct(raw, snip)})")
    print(
        f"\nRetrieval latency via MCP search_wiki: ~{avg_ms:.0f} ms/query (index-backed)."
    )
    print("Fewer context tokens => proportionally cheaper + faster LLM answers.")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
