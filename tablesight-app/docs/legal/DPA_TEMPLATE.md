> **DRAFT — requires review by qualified counsel; not legal advice.**

> **Implementation status:** statements marked [NOT YET IMPLEMENTED] describe intended controls that do not exist in the product yet (as of this draft: no video endpoint, no blurring, no encryption of the database or backups, no minor-detection). Remove or make true before publication.


# Data Processing Agreement (Template)

Between **[CUSTOMER]** ("Controller") and **[TABLESIGHT ENTITY]** ("Processor"). Effective [DATE]. Forms part of the Master Services Agreement. Based on the structure of GDPR Art. 28(3) (verify against official text); adapt for UK GDPR, CCPA service-provider terms and other regimes.

## 1. Definitions
Terms such as personal data, processing, controller, processor, data subject and supervisory authority have their GDPR meaning. "Services" means TableSight floor intelligence.

## 2. Subject matter, duration, nature, purpose
- Subject matter: floor analytics for Controller's hospitality venues.
- Duration: term of the MSA plus return/deletion period.
- Nature: on-premise video analysis; metadata sync; optional cloud video storage; dashboards and alerts.
- Purpose: operational service quality and capacity management.
- Data subjects: guests, staff, visitors, children incidentally in view, Controller's users.
- Data types: video frames/clips (if enabled), floor metadata, staff analytics (if enabled), user account data. No biometric identifiers are processed by design; Processor will not enable any feature that does so without written instruction and a revised DPIA.

## 3. Processor obligations
1. Process only on documented instructions (this DPA, the product configuration, written instructions); inform Controller if an instruction appears unlawful.
2. Confidentiality for authorised personnel.
3. Security measures per Annex II.
4. Sub-processors: general authorisation for those in SUBPROCESSORS.md; [30] days' notice of changes; Controller may object on reasonable grounds; flow-down of equivalent obligations; Processor remains liable.
5. Assist with data-subject requests, DPIAs and prior consultation (Arts. 12-22, 35, 36; verify).
6. Breach notice to Controller without undue delay and within [48] hours of awareness, with available details.
7. Deletion or return at end of services within [30] days, plus certificate on request; backups expire within [35] days.
8. Audit: provide information necessary to demonstrate compliance; audits once a year on [30] days' notice, confidentiality applies; SOC2/ISO reports may satisfy this.
9. Transfers: only under [adequacy / SCCs Module 2 (C2P)] (verify current text); Annex III lists locations.

## 4. Controller obligations
- Has a lawful basis for the processing and has completed any DPIA required.
- Gives notice to guests (signage, see SIGNAGE_TEMPLATE) and to staff (see STAFF_NOTICE_TEMPLATE), and completes works-council, union or other consultation required locally before staff analytics are switched on.
- Does not enable features unlawful in its jurisdiction; accepts that the product disables re-identification by default.
- Does not use outputs as the sole basis for decisions with significant effect on individuals.
- Sets retention within legal limits.

## 5. Liability
Per the MSA. [Counsel to settle caps and indemnities.]

## 6. Order of precedence
This DPA prevails over the MSA on data protection.

## 7. Governing law and jurisdiction
[LAW]. SCCs as per their own terms.

## Annex I: Details of processing
Parties' contacts, DPO, supervisory authority [__], list above.

## Annex II: Technical and organisational measures
TLS in transit via the bundled reverse proxy; encrypted camera credentials (Fernet); tenant isolation tested automatically; RBAC with least privilege; encryption at rest of database and backups **[NOT YET IMPLEMENTED — must be true before publishing]**; blurring by default for non-privileged roles **[NOT YET IMPLEMENTED — must be true before publishing]**; audit log of video access; configurable retention; edge-first processing; metadata-only sync; signed updates; vulnerability scanning and patching; logging and monitoring; backup with tested restore; staff confidentiality and training; support view with no video access; incident response plan.

## Annex III: Sub-processors and locations
See SUBPROCESSORS.md.

## US state addendum (verify)
Processor acts as "service provider" or "processor": no sale/sharing, no retention or use outside the direct business relationship, certification of understanding, assist with consumer requests (CCPA/CPRA and other state laws).

## Signatures
Controller: ____ Name/Title/Date. Processor: ____ Name/Title/Date.
