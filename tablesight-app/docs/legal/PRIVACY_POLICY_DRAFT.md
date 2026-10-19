> **DRAFT — requires review by qualified counsel; not legal advice.**

> **Implementation status:** statements marked [NOT YET IMPLEMENTED] describe intended controls that do not exist in the product yet (as of this draft: no video endpoint, no blurring, no encryption of the database or backups, no minor-detection). Remove or make true before publication.


# TableSight Privacy Policy (Draft)

Effective date: [DATE]. Operator: [COMPANY LEGAL NAME, ADDRESS, REGISTRATION NO.]. Contact: [PRIVACY EMAIL]. EU/UK representative: [IF REQUIRED, verify]. DPO: [IF APPOINTED].

This policy covers our website, dashboard and cloud services. For video and floor analytics at a venue, the venue operator ("Customer") is the controller and TableSight is the processor (see the Data Processing Agreement). Venue signage and the venue's own notice explain what happens to people in the venue.

## 1. What we do

TableSight analyses camera feeds to show a venue where guests are waiting and when tables were last visited. Processing is performed on equipment at the venue ("edge"). We do not perform facial recognition and do not identify people by biometrics.

## 2. Data we process

| Category | Examples | Where | Role |
|---|---|---|---|
| Account data | name, work email, role, hashed password, 2FA data | cloud | controller |
| Venue configuration | locations, floor layouts, zones, thresholds | cloud | processor/controller |
| Floor metadata | zone occupancy, event timestamps, durations, random temporary track IDs | edge, synced to cloud | processor |
| Video | live frames and, if enabled by the Customer, clips | edge by default; cloud only if opted in | processor |
| Staff analytics | per-section or aggregate service metrics, mode on / anonymized / off | edge/cloud | processor |
| Technical data | device health, logs, IP address | cloud | controller |
| Support and billing | tickets, plan, invoices | cloud | controller |

We do not collect: face templates, fingerprints, voiceprints, audio, age, gender or ethnicity inferences. Within a single camera, the tracker uses a transient torso-colour value to keep a track ID; it is not stored. There is no cross-camera re-identification in the product. If cross-camera re-identification is ever added it must stay off by default, in device memory only, and be reviewed by counsel first (see PRIVACY_ANALYSIS.md).

## 3. Purposes and legal bases (GDPR; verify for each market)

- Providing the service: contract (Art. 6(1)(b)).
- Security, fraud prevention, product improvement: legitimate interests (Art. 6(1)(f)).
- Legal obligations: Art. 6(1)(c).
- Marketing: consent (Art. 6(1)(a)) where required.
- Customer's floor analytics: Customer's own basis, usually legitimate interests, documented in its DPIA.

## 4. Sharing and sub-processors

We share data with sub-processors listed in SUBPROCESSORS.md under written contracts. We do not sell personal data or share it for cross-context behavioural advertising. We may disclose data if legally required.

## 5. Retention

Floor metadata: 30 days default (as implemented), configurable up to the plan maximum; deleted by an hourly purge job. Video: configured by the Customer, default [7 days] on-premise, none in cloud unless opted in. Account data: life of account plus [30] days. Logs: [12 months]. Backups roll off within [35] days.

## 6. International transfers

Cloud data location: [REGION]. Where data moves outside the EEA/UK we use [adequacy decisions / Standard Contractual Clauses] (verify current mechanism).

## 7. Your rights

Depending on where you live: access, correction, deletion, restriction, portability, objection, withdrawal of consent, complaint to a supervisory authority; California residents: know, delete, correct, limit use of sensitive information, no discrimination (verify). If you appear in venue video, contact the venue first; we will assist it. Contact [PRIVACY EMAIL]. We respond within [30 days] (verify local deadline).

## 8. Children

Our dashboard is not for children. At venues, the system is intended not to run individual-level analytics on people who appear to be minors; only anonymous counts are used. **[NOT YET IMPLEMENTED — must be true before publishing]** (no minor-detection exists; today no individual-level analytics are produced at all, only team-level).

## 9. Employees at venues

Staff analytics are optional and controlled by the Customer, who must give staff notice and complete any consultation required locally (for example with works councils). See the staff notice at the venue.

## 10. Security

TLS in transit (bundled reverse proxy), encrypted camera credentials, role-based access, audit logging of data access, backups with an integrity check. Not yet implemented **[NOT YET IMPLEMENTED — must be true before publishing]**: encryption at rest of database/backups, blurred video for non-privileged roles, audit logging of video access (there is no video endpoint yet). No system is perfectly secure; breaches are notified as the law requires (GDPR Art. 33/34, verify).

## 11. Automated decision-making

TableSight produces alerts with confidence scores. It does not make decisions with legal or similarly significant effects on individuals. Customers must not use it as the sole basis for discipline (GDPR Art. 22, verify).

## 12. Changes and contact

We will post changes here and notify account holders of material changes. [COMPANY, ADDRESS, EMAIL].

## Jurisdiction add-ons (to complete with counsel)

- Illinois / Texas / Washington: statement that no biometric identifiers are collected; retention schedule if that ever changes.
- California: categories, sources, sale/share disclosure, employee notice at collection.
- EU/UK: lead supervisory authority, DPO, representative.
