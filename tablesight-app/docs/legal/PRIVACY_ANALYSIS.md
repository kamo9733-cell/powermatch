> **DRAFT — requires review by qualified counsel; not legal advice.**

# TableSight Privacy Analysis (CLAUDE.md §2.1)

Researched 2026-10-19. Statute text changes; every citation marked "verify" or without a fetched primary source must be checked against the official text before reliance. Several primary-source sites (gdpr-info.eu, eur-lex, ilga.gov, statutes.capitol.texas.gov) could not be fetched directly from the build environment (DNS failure), so quotations below come from search-result summaries of those pages. Treat them as secondary until confirmed.

## 1. Question

Does TableSight's floor tracking (detect people, track them, optionally re-identify the same appearance across cameras for a visit) amount to biometric processing?

## 2. What the system does (design assumptions)

- Person detection and tracking per camera. On-premise processing; only metadata (zone, timestamps, track IDs) syncs to cloud.
- Optional appearance re-ID across cameras: a short-lived embedding of clothing/colour/shape cues, used only to join tracks within one visit.
- No face recognition, no face embeddings, no gait/voice, no cross-visit linking, no identity lookup, no matching to a named person.

## 3. Legal analysis by regime

### 3.1 GDPR (EU/EEA; UK GDPR is similar, verify)
- Art. 4(14) defines biometric data as personal data from "specific technical processing relating to the physical, physiological or behavioural characteristics of a natural person, which allow or confirm the unique identification of that natural person, such as facial images or dactyloscopic data". Source (secondary): https://www.thomashelbing.com/en/wissen/dsgvo-hub/begriffe-und-definitionen/1.2.14-biometrische-daten ; primary: Regulation (EU) 2016/679 on EUR-Lex (verify).
- Art. 9(1) prohibits processing "biometric data for the purpose of uniquely identifying a natural person" (special category). Note the purpose limb: the Catalan authority opinion at https://apdcat.gencat.cat/web/.content/Resolucio/Resolucions_Cercador/Dictamens/2020/Documents/en_cns_2020_021.pdf discusses the gap between "identification and authentication" in Art. 4(14) and Art. 9(1).
- Recital 51: photographs are not systematically special-category data; only when processed by specific technical means allowing unique identification or authentication. https://gdpr-info.eu/recitals/no-51/ (summary seen via search; verify).
- Assessment: Detection and anonymous per-camera tracking is ordinary personal data (a video image of a person is personal data) and likely not Art. 9. Appearance re-ID is the risk. Embeddings that single out an individual across cameras are arguably "specific technical processing" of physical characteristics that "allow ... unique identification" in the singling-out sense. Whether Art. 9 is triggered depends on whether regulators read "unique identification" as singling out (broad) or as identifying a known person (narrow). This is unsettled; European Data Protection Board guidance on video devices (Guidelines 3/2019, verify) should be read by counsel. Conservative position: treat persistent, reusable embeddings as biometric-adjacent.
- Regardless of Art. 9: a lawful basis under Art. 6 (legitimate interests with a documented balancing test is the likely basis), transparency (Arts. 13/14, signage), a DPIA under Art. 35 (systematic monitoring of a publicly accessible area is a listed trigger, verify Art. 35(3)(c)), and data minimisation/storage limitation (Art. 5).
- Employees: see section 4.
- EU AI Act (Reg. (EU) 2024/1689): has definitions of biometric data and biometric categorisation, and prohibits emotion recognition in the workplace (Art. 5(1)(f), verify). TableSight does no emotion inference. Verify whether staff-tracking features fall into any high-risk category in Annex III (employment/worker management; verify).

### 3.2 Illinois BIPA (740 ILCS 14)
- Sec. 10 defines "biometric identifier" as a retina or iris scan, fingerprint, voiceprint, or scan of hand or face geometry; photographs are excluded; "biometric information" is information based on a biometric identifier "used to identify an individual". Source: https://lig.ilga.gov/legislation/ilcs/documents/074000140K10.htm (seen via search; verify). Public Act 103-0769 amended Secs. 10 and 20 (per-person rather than per-scan accrual; electronic signature consent): https://ilga.gov/legislation/publicacts/103/103-0769.htm .
- Sec. 15 notice, written release, retention schedule; Sec. 20 private right of action with statutory damages (verify amounts; commonly cited $1,000 negligent / $5,000 reckless).
- Assessment: BIPA's list does not name "appearance embeddings" or body/clothing features. Only "scan of ... face geometry" is plausibly relevant, so any facial-geometry embedding is out. Clothing/body-shape re-ID is arguably outside the list, but plaintiffs plead aggressively and the question is not settled in our review; verify with Illinois counsel. Because BIPA exposure is per-person and class-action prone, do not offer re-ID in Illinois by default.

### 3.3 Texas CUBI (Tex. Bus. & Com. Code Sec. 503.001)
- Biometric identifier: retina/iris scan, fingerprint, voiceprint, or record of hand or face geometry. Capture for a commercial purpose requires prior notice and consent; enforcement by the Attorney General; civil penalty up to $25,000 per violation (subsec. (d)). Official text: https://statutes.capitol.texas.gov/Docs/BC/htm/BC.503.htm . Amendments effective 2026-01-01 added AI-related provisions (verify current text). Also see TRAIGA / Texas data privacy act (verify).
- Assessment: same as BIPA. Face geometry is out of scope for us; appearance-only features not clearly covered. No private right of action as of the source seen.

### 3.4 Other jurisdictions (all to verify)
- Washington biometric identifier law (RCW 19.375) and My Health My Data Act (RCW 19.373): verify scope and exclusions.
- California CCPA/CPRA: biometric information is "sensitive personal information"; employee data is in scope. Verify definition (does it cover imagery "from which an identifier template can be extracted").
- New York City commercial biometric identifier information law (NYC Admin. Code Title 22, Ch. 12, verify): signage requirement for establishments that collect biometric identifier information; relevant to restaurants.
- Colorado, Connecticut, Virginia and other comprehensive state laws treat biometric data processed to uniquely identify as sensitive; consent usually needed. Verify each.
- Canada: PIPEDA and Quebec Law 25 (biometric databases require disclosure to the Commission, verify). UK: ICO guidance on biometric and surveillance cameras (verify). Brazil LGPD, UAE/KSA (PDPL), India DPDP Act: verify, since Arabic markets are targeted (CLAUDE.md §6).

## 4. Employee monitoring (templates only; owners must check locally)

| Jurisdiction | Rule of thumb | Verify |
|---|---|---|
| Germany | Works council co-determination over technical systems capable of monitoring staff (BetrVG Sec. 87(1) no. 6); employee-data processing under BDSG Sec. 26 and GDPR Art. 88; CJEU Case C-34/21 on Sec. 26 BDSG. A works agreement is normally required before staff analytics go live. | statute numbers, current case law |
| France | CSE information/consultation; CNIL position that permanent employee surveillance is disproportionate; individual notice | CNIL guidance, Labour Code articles |
| Italy | Workers' Statute Art. 4: union agreement or labour inspectorate authorisation for camera systems | article, Jobs Act changes |
| Netherlands, Austria, Spain | Works council or representative consent/consultation; Spain has specific labour-law video-surveillance provisions | all |
| UK | Employer must notify; DPIA; ICO employment monitoring guidance | guidance current |
| US - states with employee electronic-monitoring notice laws | New York (Civil Rights Law Sec. 52-c), Connecticut (Gen. Stat. Sec. 31-48d), Delaware (19 Del. C. Sec. 705): written notice before monitoring, with signature/acknowledgement in some. Connecticut and others restrict cameras in rest areas/bathrooms. | section numbers, new 2025-26 laws |
| US - general | NLRA Sec. 7: surveillance of protected concerted activity is risky; collective bargaining agreements may restrict. California CCPA notice-at-collection to employees. Audio recording raises wiretap/two-party consent laws; TableSight must not record audio by default. | all |
| Gulf / Arab markets | Mixed; labour and PDPL rules apply. Verify per country. | all |

Design response: per-location staff analytics mode `on / anonymized / off` (default `off` or `anonymized` pending acknowledgements), required acknowledgement checkbox that the owner has given notices and completed any works-council process, and a generated STAFF_NOTICE_TEMPLATE.

## 5. Children

- GDPR Recital 38 and Art. 8 give children specific protection (Art. 8 is about consent for information-society services, which is not directly relevant here but signals regulator attitude). US COPPA covers online services directed to under-13s; in-venue cameras are generally outside it, verify. Several US state laws and the UK Age Appropriate Design Code are online-service focused, verify.
- Design rule from CLAUDE.md §2.1: no individual-level analytics on anyone who appears to be a minor. Implementation: a size/pose heuristic is unreliable, so apply conservatively: aggregate-only counts (occupancy) for all guests; individual tracks and re-ID off for tracks flagged "possible minor"; never infer age for any other purpose; document the false-positive tradeoff in the UI.

## 6. Conclusions

1. Anonymous detection, counting and per-camera tracking: personal data, not biometric under BIPA/CUBI. GDPR Art. 9 not triggered on the narrow reading. Needs notice, legitimate-interest assessment, DPIA.
2. Appearance re-ID: risk is real and unsettled; may be argued to be biometric under GDPR Art. 4(14)/9 (singling out) and under US "scan of ... geometry" language only if body/face geometry is used.
3. Faces: any facial recognition, embedding or geometry is excluded from the product.
4. Staff analytics require local labour-law steps, especially in Germany, France, Italy; US notice states.

## 7. Design rules (binding on engineering)

1. No face recognition, face embeddings, face crops stored, voiceprints, gait signatures or iris/fingerprint of any kind. Enforce with a CI check that rejects face-model dependencies.
2. Re-ID, if enabled, uses non-face appearance features only (colour histogram, coarse body shape), computed on the edge, held in RAM only, discarded at track end or after a maximum of one visit (configurable, default 2 hours), never written to disk or cloud, never linked across visits or days, never matched to POS identity or names.
3. Re-ID is a per-location setting, default OFF; automatically forced OFF in Illinois, Texas, Washington and any jurisdiction flagged "biometric-sensitive" unless an admin with counsel sign-off overrides and the consent flow is enabled. EU default OFF pending DPIA completion.
4. Metadata-only cloud sync: zone events, counts, durations with random per-visit track IDs rotated daily; no embeddings leave the edge.
5. Video: on-prem, cloud viewing opt-in, role-based blurring, audit log, configurable retention with a hard maximum, tenant export and deletion.
6. Staff: per-location `on / anonymized / off`; anonymized aggregates to roles/sections, never to named individuals; no performance scoring of an individual without explicit mode `on` and notice acknowledgement.
7. Children: aggregate-only for possible minors (section 5).
8. No emotion, demographic, age, gender or ethnicity inference.
9. No audio capture.
10. Signage, privacy policy, staff notice and DPA generated from tenant settings, with a warning that they are drafts.
11. Document every re-ID change as a DPIA update.

## 8. Open questions for counsel

- Does appearance-only embedding with a short TTL fall within GDPR Art. 9 in the lead supervisory authority's view?
- BIPA/CUBI status of body-shape features; whether "can be used to identify" language applies.
- Whether TableSight is processor or joint controller for staff analytics.
- International transfers if any cloud sync leaves the EEA.
