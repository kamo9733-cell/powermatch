> **DRAFT — requires review by qualified counsel; not legal advice.**

# Sub-processors (Draft)

Last updated: [DATE]. Policy (CLAUDE.md §2.2): the core product is fully self-hostable with no required third-party cloud calls. This list covers services used by the hosted SaaS edition only. Entries are placeholders; replace them with actual vendors and verify locations and transfer mechanisms before publication.

| Sub-processor | Purpose | Data | Location | Transfer mechanism | Status |
|---|---|---|---|---|---|
| [HOSTING PROVIDER] | Compute, storage, database | Account data, floor metadata, optional cloud video | [REGION] | [adequacy/SCC] | Placeholder |
| [OBJECT STORAGE / BACKUP PROVIDER] | Encrypted backups | Encrypted database backups | [REGION] | [adequacy/SCC] | Placeholder |
| [EMAIL DELIVERY PROVIDER] | Verification/reset and alert emails | Email address, alert text | [REGION] | [adequacy/SCC] | Placeholder; self-hosted SMTP is supported |
| [SMS / PUSH PROVIDER] | Alert delivery | Phone number, alert text | [REGION] | [adequacy/SCC] | Placeholder; optional, behind an interface |
| [ERROR/LOG MONITORING] | Observability | Pseudonymised logs, no video | [REGION] | [adequacy/SCC] | Placeholder; self-hosted option |
| [SUPPORT DESK] | Customer support | Contact details, ticket contents | [REGION] | [adequacy/SCC] | Placeholder |
| Payment processor | Not applicable | Payment is out of scope in the current build (billing interface is no-op) | n/a | n/a | None |

## Not sub-processors by design
- Detection, tracking and analytics models run on the edge; no video is sent to third-party AI APIs.
- Self-hosted customers have no TableSight sub-processors for video.

## Change process
Customers receive [30] days' notice of new sub-processors via [email/dashboard]; objection rights per DPA_TEMPLATE.md section 3.4. Maintain this file with change history:

| Date | Change |
|---|---|
| [DATE] | Initial draft |
