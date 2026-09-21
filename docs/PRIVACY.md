# Privacy and data flow

Jev Second Brain operates on files you choose. Source Markdown is read only;
the derived state lives outside the vault. An ordinary `init`, `index`,
`search`, or `suggest` preview does not make a model request.

| Data | Where it goes | Trigger |
| --- | --- | --- |
| Full `.md` text, titles, paths, extracted links | Local `index.sqlite` in the configured state directory | `index` |
| Note pair text, titles, paths, content revision IDs | Vercel AI Gateway → TypeSafe Jev | `suggest --evaluate` on a cache miss |
| Search query and bounded note excerpt | Vercel AI Gateway → TypeSafe Jev | `search --rerank` on a cache miss |
| Typed relationship judgment, routing and usage metadata | Local `alignment-cache.sqlite` | Successful pair evaluation |
| Typed search judgment and digest identity | Local `rerank-cache.sqlite` | Successful search evaluation |
| Human disposition and optional rationale | Local append only `reviews.jsonl` | `review` |

The pair cache does not store the raw pair text. The search cache does not
store the raw query or excerpt. The index *does* store full note text, and CLI
JSON may display paths, excerpts, or judgments; handle the state directory and
captured output as private material. The CLI reads `AI_GATEWAY_API_KEY` from the
process environment and does not write it to state files.

## Outbound calls

Every provider request uses Vercel's documented `/v1/evaluate` endpoint with
model `typesafe-ai/jev`, `zeroDataRetention: true`, and a TypeSafe only provider
allowlist. For private mode (the default), the first uncached request starts
with fictional canary text. The code requires the response's TypeSafe route
and explicit ZDR evidence before sending a private note or search excerpt. A
missing key, unsupported account, unavailable route, or missing evidence stops
private pair evaluation. Search reranking reports a local fallback on an
evaluation error. These guards do not establish that your account's route is
working until you run and inspect a live synthetic canary.

`--public` skips that **private route verification** for material you have
already classified as public. The request still asks Vercel for ZDR. Use this
flag only with fictional or genuinely public notes. There is no automatic
classification of private versus public source text.

The CLI bounds work per invocation: candidate count, request size, attempts,
input token reserve, and estimated/reported cost. `--max-requests` and
`--max-cost-usd` set two ceilings; they are not a persistent account spending
cap. Requests and retries can still be billable. Set a Vercel team budget as
well, and verify current price and quota before a larger run. MIT licensing
applies to this package; it does not confer free inference.

Vercel documents [typed evaluation](https://vercel.com/docs/ai-gateway/modalities/evaluation)
and [per request ZDR](https://vercel.com/docs/ai-gateway/security-and-compliance/zdr).
At the time of this document, Vercel lists per request ZDR for Pro and
Enterprise accounts. Provider policies and account features can change, so
check the current documentation and your account before a private pilot.

## Source authority

A Jev probability is a judgment about the supplied evidence, not a verified
fact. A source path and content revision let you inspect the original note.
`review keep` records a human decision but does not add a link to Markdown.
Index rows and old cache entries can be rebuilt or retired; the original vault
is the authoritative record. Do not publish a state directory, raw CLI output
from private notes, or an API key with this repository.
