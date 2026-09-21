---
name: link-new-material
description: Propose evidence-backed relationships between new material and an existing collection, such as a new note and related notes. Retrieve candidate targets, judge each pair, and benchmark missed links separately from incorrect links.
---

# Link new material

Find supported relationships from new material to an existing collection.

## Prerequisites

Inspect repository instructions and existing collection, identifiers and link
semantics with `rg --files` and targeted `rg` queries. Establish which relationship
types the application supports and which mutations are authorized. Use the
installed provider skill (such as `typesafe-ai`) or official provider docs for
pairwise judgments. Keep source evidence and inferred relationships distinct.

## Workflow

1. **Define a useful link.** Name directed relationship types and what evidence
   supports each. For notes, shared vocabulary alone need not imply a useful
   crosslink. Preserve a no-supported-relationship outcome; do not force links.
2. **Snapshot inputs.** Store stable source and target IDs, navigable URLs or
   resolvable local paths, content revisions and evidence references. Retain
   collection coverage and exclusions. Never assume a fetched subset is complete.
3. **Retrieve targets for recall.** Apply exact scope/access filters, then union
   FTS terms, entities, existing relations and other available cheap signals.
   Exclude self-links and deduplicate target IDs. For a small frozen corpus,
   establish an exhaustive pair-evaluation baseline before optimizing retrieval.
4. **Judge pairs.** Give each question the new material and candidate evidence;
   return defined relationship type(s), score/probability and evidence references.
   Cache source revision, target revision, direction, rubric, adapter and model
   epoch. Unrelated pairs are valid outcomes. Do not infer reciprocal relations
   unless the defined relation is symmetric. Changed targets invalidate their
   pairs; unchanged targets do not require blanket recomputation.
5. **Propose or apply within scope.** Select links in code with evaluated
   thresholds and explicit limits. Present supporting source/target spans and
   navigable links. Separate proposed, accepted and rejected links and human
   corrections. Existing user-authored links are not removed by a new judgment.
   If applying links is authorized, use idempotent edge keys and verify results.
6. **Benchmark both stages.** Freeze development and held-out source-target
   judgments. Measure candidate target recall and final accepted-link precision
   and recall by relationship type. Compare candidate retrieval against the small
   exhaustive baseline so missed targets cannot hide behind strong reranking.
   Include no-link, paraphrase, shared-word-but-unrelated, asymmetric and revised
   target cases. Record inference calls, latency and cost alongside link quality.

## Shared implementation

In this standalone package, reuse `jev_second_brain`'s indexing, provider and
judgment cache rather than adding a separate client or store for pair links.
Pass both exact inputs/revisions, direction and rubric into the cache identity.
Keep pair judgments separate from standing labels and query-item relevance.
The corpus adapter owns relationship meanings, access rules and any later
link-writing policy. The MVP records proposals and human dispositions outside
source Markdown; it does not apply links. This pattern does not require a graph
database or memory migration.

## Error handling

Incomplete retrieval makes link proposals partial; provider errors leave pairs
pending. Unsupported or missing evidence cannot become an accepted relation.
Ambiguous writes require reconciliation before retry. A relabel cannot overwrite
human corrections or duplicate an existing edge.
