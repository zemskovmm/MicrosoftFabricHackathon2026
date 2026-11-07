# InventoryPulse document processing workflow

Open `document-processing.html` directly in a browser. This is a standalone Archify workflow with Russian diagram labels and the default English viewer controls. `candidate.json` is the editable source.

The main example follows selected SKF 6205-2RSH offers from `001-table-01.md` and `012-card-03.md`, joined to the existing synthetic plant fixture. Each branch carries its own example; alternative branch counts do not describe the main two-record run. Cards distinguish prior live isolated GPT-OSS tests, deterministic checks, and automated approval/extraction tests. This is not evidence of one end-to-end LLM run or a live Fabric deployment.

Generated with Archify 3.0.1 at tt-a1i/archify revision `7f483b61e8f68d0d5c3219d2c943c5381c8db0b1`, the same revision used by the supplied IDD diagram site. It is not the unrelated npm package named archify.

Rebuild from the repository root with a checkout of that revision:

```sh
node /path/to/archify/archify/bin/archify.mjs finalize workflow \
  .archify/workflow-document-processing-20261107-201800/candidate.json \
  .archify/workflow-document-processing-20261107-201800/document-processing.html \
  --repo-root . --quality showcase --out-dir output/archify-workflow-review --json
```

All four gates passed: validation, delivery, artifact verification, and real-browser verification. The generated page was also opened and visually inspected in Chrome. The source revision in the diagram identifies the implementation explained, before this diagram-only commit.
