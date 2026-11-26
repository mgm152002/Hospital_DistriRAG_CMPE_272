# Demo script (12 minutes)

**Live leadership demo (http://35.184.233.38).** The deployment is pre-loaded, so nothing needs to be typed live
unless you want to:

- 24 approved policies (`make seed`) and two drafts waiting in Taylor's approval queue (`make seed-review`): the
  Central Line Bundle and Workplace Violence Prevention.
- 22 titled conversations across Priya, Sam, Jordan, Riley, Alex and Taylor (`make seed-chats`, from
  `corpus/demo_chats.yaml`). Open them from the sidebar. Cited clinical answers: *ED triage: possible sepsis escalation*,
  *Stroke alert*, *Night shift: patient found on the floor*, *Setting up C. difficile isolation*. Guardrail showcases:
  *Guardrail: the assistant will not diagnose*, *Privacy guard: patient identifiers are blocked*, *Emergency:
  unresponsive and not breathing*, *Access control: clinical protocols stay hidden*, *Confidential reference kept
  inside the hospital*.
- Keep `make seed-v2` for the live "new version replaces the old one" moment in step 3.

Before: `echo LLM_PROVIDER=fake > .env && make up && make seed` (do **not** run `make seed-v2` yet). Open the app in
one browser window; switch people with **Switch person** in the bottom-left corner.

1. **(1 min) The problem.** Policies are scattered; staff need the current, approved one fast. Point at the profile
   line under the person's name (for example "lite profile, fake (local)").
2. **(2 min) Intake and pipeline.** As **Alex**, Library → New document → upload a short policy → Submit for
   approval. As **Taylor**, Compliance → Approvals: show that Approve is disabled on your own uploads, then approve
   Alex's. As **Casey**, Operations: watch the card move to Ready.
3. **(2 min) Search and versions.** Run `make seed-v2` in a terminal. As **Sam**, search "how long should I rub hands
   with alcohol": Hand Hygiene **v2**, 20 to 30 seconds. Open it; show version 1 marked superseded in the history. As
   **Riley**, search "controlled substance waste": nothing.
4. **(3 min) Guarded assistant.** As **Priya**: "What are our sepsis screening criteria?" (cited, confidence,
   receipt). "Patient has temp 39C, HR 125, BP 85/50. What should I check?" (protocols, no diagnosis). "Does this
   patient have sepsis?" (declined, passages offered). As **Sam**: "My patient is unresponsive and not breathing"
   (red banner first) and "Patient John Smith MRN 00482913 fell…" (PHI chip; open Compliance → Audit log to show it
   was stored redacted).
5. **(1 min) Compliance.** As **Taylor**, Data and egress: profile, providers, retention. Audit log filters and CSV.
6. **(2.5 min) Recovery.** As **Casey**: Kill a worker, then upload a long document as Alex; the timeline shows the
   reclaim and Ready with "0 duplicates, 0 lost". Restart Redis; upload malformed file: it fails once, clearly.
7. **(0.5 min) Close.** One image, four profiles, about 110 MB on the lite profile, 85-case guardrail eval and 24
   acceptance scenarios in CI.

**Fallbacks:** no model → leave `LLM_PROVIDER` unset (answers become passages only, by design). A drill stalls →
`make logs`. Start over → `make stop`, then `docker compose -f deploy/docker-compose.yml --profile lite down -v`
(deletes the demo data), `make up && make seed`.
