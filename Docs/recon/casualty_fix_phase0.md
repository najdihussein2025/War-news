# Casualty accuracy fix — Phase 0 recon

## Blocking questions

Implementation is blocked before Phase 1 because the required `dev` baseline
contradicts the prompt's stated code baseline.

1. `git checkout dev` resolves to `a478cbd` (up to date with `origin/dev`),
   while the two completed recon commits are on `main` (`ba59fef`, `0f61b55`)
   and are not ancestors of `dev`.
2. On `dev`, the modules named as current protections in the prompt and recon
   reports do not exist: `casualty_gender_evidence.py`,
   `casualty_scope_backstop.py`, and `casualty_count_backstop.py` under the
   expected news extraction/service paths. The Phase 0 inspection therefore
   cannot verify or safely modify the stated current pipeline.
3. The working tree contains an unrelated line-ending-only modification to
   `app/news/interfaces/raw_message_repository_interface.py`; it has been
   preserved and not included in this work.

**Direction needed:** should the casualty-fix work target `main` (which holds
the recon helpers/report and the referenced current safeguards), or should
those commits and their prerequisite implementation be merged/cherry-picked
into `dev` first? Continuing on this `dev` revision would amount to designing
a different, older pipeline rather than applying the specified fixes.

## Read-only findings completed before the block

- The previously committed reports were read: `Docs/recon/casualty_flow_recon.md`
  and `Docs/recon/casualty_recon_2.md`.
- `docker-compose.yml` defines all application services with the same
  `context: .` and `app/Dockerfile`: backend, pipeline, live sweep, backlog
  relevance, bulletin reconciliation, summary reconciliation, CNRS polling,
  and red-alert collector. The Oct 8 worker images are therefore stale local
  builds, not separate build contexts or pinned `image:` tags. A full compose
  rebuild would align them; it was not run.
- A SELECT-only query on `war_news_dev` found nine source/first-line groups
  repeated at least 20 times. The top candidates were source 3: `قصف مدفعي
  يستهدف بلدة المنصوري` (160), `قصف مدفعي يستهدف وادي زبقين` (47), `قصف
  مدفعي يستهدف وادي السلوقي` (38), and source 1 red-alert boilerplate (84,
  48, and 22 variants). These are repeated event/boilerplate candidates; the
  query did not find the claimed channel header among the top 30.

No application code, database row, migration, prompt, rule, or frontend file
was changed in Phase 0.
