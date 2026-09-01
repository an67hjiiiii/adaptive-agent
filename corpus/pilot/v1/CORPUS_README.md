# Pilot reference corpus v1

This directory is an immutable, content-addressed reference set for the
eight-task Pilot benchmark. The benchmark-authoring revisions were copied
verbatim so task wording and source facts remain stable even when the living
project documents change.

`CORPUS_MANIFEST.json` is authoritative for source IDs, corpus version,
SHA-256 hashes, provenance, snapshot time, and stable section IDs. Benchmark
task bindings use those section IDs; any line ranges are human traceability
only. Do not edit a snapshot in place. A source change requires a new corpus
version (for example `corpus/pilot/v2/`).

The snapshots are source material only. They contain no hidden rubric,
taxonomy, expected-answer labels, provider credentials, or runtime route hint.
