# Examples

- `sag-sync.example.json` — copy to `.sag-sync.json` at the root of your
  project repo, and fill in the real `source_id` (create one with
  `sagctl source create "<name>"`).
- `doc-templates/` — copy into your project's `docs/` as a starting point for
  ADR/runbook/research documents written to spec for retrieval (clear
  headings, complete self-contained propositions, standard frontmatter — see
  `skills/sag-publish/SKILL.md`).
- `eval/questions.example.jsonl` — publish the 3 files in `doc-templates/`
  (renaming the placeholders first) to a test source, then run:

  ```bash
  sagctl eval --questions examples/eval/questions.example.jsonl \
    --source-id <source_id> --save-baseline
  ```

  This is a smoke test confirming that `sagctl eval` runs correctly — building
  a real golden set (15-20 project-specific questions) is a follow-up task
  after backfilling the real corpus, and belongs on the project's onboarding
  checklist (not something the plugin handles).
