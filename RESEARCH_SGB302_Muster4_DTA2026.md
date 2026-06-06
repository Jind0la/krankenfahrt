# Research Report: Statutory Billing under §302 SGB V, Muster 4, and DTA 2026

**Date:** June 6, 2026  
**Purpose:** Concise, actionable summary of legal and technical requirements for statutory health insurance billing in Germany, focusing on digital Muster 4 and DTA 2026.  
**Scope:** Sonstige Leistungserbringer (Other Service Providers) billing under §302 SGB V — specifically patient transport (Krankenfahrten / Krankentransporte).

---

## 1. Legal Basis: §302 SGB V

### 1.1 Core Statutory Text
[Official source: gesetze-im-internet.de/sgb_5/__302.html]

§302 SGB V mandates electronic billing for "Other Service Providers" (*Sonstige Leistungserbringer*) with statutory health insurance funds (*Krankenkassen*). The provision was introduced through the 1992 Health Structure Act and has been progressively tightened.

**Service providers covered (§302 Abs. 1):**
- Medical aids and supplies (*Heil- und Hilfsmittel*)
- Digital health applications (*DiGA*)
- Home nursing (*häusliche Krankenpflege*)
- Patient transport (*Krankenfahrten / Krankentransporte*)
- Midwives and maternity nurses
- Non-physician dialysis services
- Specialized palliative care (SAPV)

**Mandatory data elements (§302 Abs. 1):**
- Type, quantity, price, and date of each service
- Prescribing physician's number (LANR) and diagnosis
- Patient master data per §291a Abs. 2
- For medical aids: designations from the Hilfsmittelverzeichnis (§139) and additional costs (*Mehrkosten*)
- For nursing/intensive care: including employee number (*Beschäftigtennummer*)

### 1.2 Regulatory Framework (§302 Abs. 2–3)
The **GKV-Spitzenverband** (National Association of Statutory Health Insurance Funds) issues binding *Richtlinien* (guidelines) that define:
- Form and content of billing data
- Transmission protocols and formats
- Code directories (*Schlüsselverzeichnisse*)
- Correction and objection procedures

These guidelines take the form of:
1. **Richtlinien-Text** — legal/administrative framework document
   - [Source: gkv-datenaustausch.de/media/dokumente/.../Richtlinien-Text_061120.pdf]
2. **Technische Anlage 1 (TA1)** — data format specification (EDIFACT-based)
3. **Technische Anlage 3 (TA3)** — code directories and lookup values
4. **Technische Anlage 4** — accompanying documents for original records (*Urbelege*)
5. **Technische Anlage 5** — content requirements for original documents

### 1.3 Billing Modalities
| Aspect | Detail |
|--------|--------|
| Transmission paths | FTP, encrypted email (ITSG Trust Center PKI), CD/diskette (legacy) |
| Billing centers | Permitted; must process data only for SGB-defined purposes |
| Credit note procedure (*Gutschriftverfahren*) | Insurer issues credit note; provider reviews; objection renders it non-binding (§302 Abs. 6) |
| Correction procedures | VK 02 (supplemental claim), VK 03 (co-payment claim), VK 04 (correction invoice) |

### 1.4 Penalties for Non-Compliance
- Up to **5% reduction** of invoice amounts for providers failing to participate in electronic data exchange
- Administrative processing fees charged to providers submitting paper invoices
- [Source: Wikipedia, Datenaustausch nach §302 SGB V]

---

## 2. Muster 4: Verordnung einer Krankenbeförderung

### 2.1 Purpose and Legal Context
Muster 4 is the standardized prescription form for patient transport under §60 SGB V. It is used by physicians and psychotherapists to prescribe medically necessary transport for insured patients.

**Governing regulations:**
- **§60 SGB V** — legal basis for travel cost reimbursement
- **Krankentransport-Richtlinie (KT-RL)** of the G-BA — clinical eligibility criteria
  - Current version: May 15, 2025, effective August 6, 2025
  - [Source: g-ba.de/richtlinien/25/]
- **Vordruckvereinbarung (Anlage 2 BMV-Ä)** — form design, content, and usage rules
  - Between KBV (Kassenärztliche Bundesvereinigung) and GKV-Spitzenverband
  - Muster 4 specification at §2.4.1 of Anlage 2
  - [Source: kbv.de → Bundesmantelvertrag → Anlage 2]

### 2.2 Required Content (per KT-RL Anlage 1)
The paper Muster 4 must contain:

| Category | Fields |
|----------|--------|
| **Patient data** | Name, date of birth, address, insurance number (KVNR) |
| **Trip details** | One-way or return, date or frequency, destination facility |
| **Medical reason** | Diagnosis, treatment type (inpatient/outpatient), specific eligibility category |
| **Transport mode** | Taxi, Mietwagen, wheelchair taxi, carrying chair (*Tragestuhl*), stretcher (*Liegend*), or KTW |
| **Approval indicator** | Whether prior approval from insurer is required or exempt |
| **Validation** | Physician stamp and signature, date of issuance |

**Key rule:** Must be issued *before* the trip (except emergencies where retroactive issuance is permitted per KT-RL §4).

### 2.3 Approval vs. Exemption Rules (per KT-RL §8 and Anlage 2)

**Genehmigungsfrei (No prior approval needed):**
- Inpatient/partial inpatient hospital stays
- Pre-inpatient (up to 3 days within 5 days before) and post-inpatient (up to 7 days within 14 days after)
- Outpatient surgeries under §115b SGB V
- Patients with disability marks "aG", "Bl", "H" — for taxi/Mietwagen only
- Care levels (Pflegegrad) 4 or 5 — for taxi/Mietwagen only
- Care level 3 with permanent mobility impairment — for taxi/Mietwagen only

**Genehmigungspflichtig (Prior approval required):**
- High-frequency treatments: dialysis, chemotherapy, radiation therapy
- Any KTW (ambulance) transport
- Outpatient treatment ≥6 months with significant mobility impairment
- Exception: KTW for aG/Bl/H/PG4-5 still requires approval

### 2.4 Patient Co-payment (Zuzahlung)
- **Rate:** 10% of transport cost
- **Minimum:** €5 per trip
- **Maximum:** €10 per trip
- **Collection:** Transport provider must collect directly from patient
- **Exemption:** Only with valid *Zuzahlungsbefreiung* certificate from insurer

### 2.5 Digital Muster 4: Current Status and Roadmap

#### 2.5.1 Legal Framework for Digital Forms
The **Anlage 2b BMV-Ä** (*Vordruck-Vereinbarung digitale Vordrucke*, Stand July 1, 2025) governs digital forms in the statutory health insurance system.

**Digital Muster 4 status (Form e04):** "Electronic use possible" (*elektronische Verwendung möglich*) — voluntary, not yet mandatory.

**Technical standards for all digital forms per Anlage 2b:**
- **Format:** PDF/A or FHIR-Bundle (XML-based)
- **Signature:** Qualified electronic signature via eHBA (electronic Health Professional Card); SMC-B (Practice Identity Card) as fallback
- **Transmission:** KIM (Kommunikation im Medizinwesen) or TI-specific services
- **Security:** Transport encryption + electronic transport signature per BSI recommendations

[Source: gkv-spitzenverband.de → Anlage 2b BMV-Ä, Lesefassung 01.07.2025]

#### 2.5.2 gematik Digital Initiative (Impulspapier, September 2025)
The **gematik** (national agency for Telematics Infrastructure) published an impulse paper proposing a fully digital Muster 4 process. Key points:

**Scale of the problem:**
- ~50M patient transports/year (40M taxi/Mietwagen, 5.6M specialized KTW, 7.8M emergency)
- ~10% of paper Muster 4 forms contain errors
- 4.1M working hours of administrative burden in medical practices (2020)
- ~30 minutes to correct a single erroneous paper prescription

**Proposed 5-phase digital process:**
1. **Digital issuance** — in PVS/KIS with automated plausibility checks
2. **Approval workflow** — via central Fachdienst; real-time for approval-required trips
3. **Patient access** — digital key (QR code) for patients to authorize transport provider
4. **Execution & confirmation** — digital service confirmation (e-Leistungsbestätigung)
5. **Electronic billing** — transport company bills insurer digitally

**Implementation timeline:** Estimated **3 years** from planning to full rollout (~2028).
- Phase 1 (immediate): Requirements engineering before legal changes
- Phase 2: Pilot (*Praxischeck*)
- Still needs: adaptation of SGB V, KT-RL, and gematik Fachdienst

[Source: gematik.de/newsroom/news-detail/impulspapier-fuer-digitale-verordnung-von-krankenbefoerderung]

#### 2.5.3 Existing Pilot: AOK Digital Muster 4
AOK Rheinland/Hamburg, Nordwest, and Sachsen-Anhalt have been running a digital Muster 4 pilot since **July 2023**:
- **Result:** Rückfragequote (inquiry rate) dropped from 70% to under 10%
- Quality assurance checks during data entry eliminate most errors before submission
- Faster approval processing for patients

[Source: dmrz.de/blog/digitale-verordnung-fuer-krankenfahrten-der-weg-zum-papierlosen-muster-4]

---

## 3. DTA 2026: Datenträgeraustausch Specification

### 3.1 What is DTA?
The **Datenträgeraustausch (DTA)** is the contractual and technical framework for electronic data exchange between KBV, Kassenärztliche Vereinigungen (KVs), and Krankenkassen. It is formalized through:

- **Vertrag über den Datenaustausch (DA-Vertrag)** — Anlage 6 BMV-Ä
  - Current version: October 1, 2025
  - [Source: gkv-spitzenverband.de → Anlage 6 BMV-Ä]

**Scope of DTA:**
- Electronic transmission of billing basics (*Abrechnungsgrundlagen*) in individual case records
- Physician master data (*Arztstammdaten*)
- Data for efficiency audits (*Wirtschaftlichkeitsprüfung*)
- Random audit data (*Zufälligkeitsprüfung*)

### 3.2 DTA 2026: Key Dates and Version Changes

#### For "Other Service Providers" (§302 SGB V):

| Specification | Version | Effective | Transition Ends | Notes |
|--------------|---------|-----------|-----------------|-------|
| **Technische Anlage 1** (data format) | **V21** (Stand 15.01.2026) | Oct 1, 2025 | **Dec 31, 2025** → **Mandatory from Jan 1, 2026** | V20 deprecated |
| **Technische Anlage 3** (code directories) | **V21** (Stand 19.09.2025) | Oct 1, 2025 | Dec 31, 2025 | Mandatory from Jan 1, 2026 |
| **Technische Anlage 3** (code directories) | **V22** (Stand TBD) | Feb 1, 2027 | **Apr 30, 2027** | Next major version |
| **Anlage HKP** (home nursing, XML) | **V1.2.0** | Feb 1, 2027 | — | Replaces Sammelgruppenschlüssel C in TA1 |
| **Anhang 5** (digital rescue protocol) | — | Apr 1, 2026 | — | Emergency services |

[Source: gkv-datenaustausch.de → Sonstige Leistungserbringer]

#### Critical 2026 Deadlines:
- **January 1, 2026:** TA1 V20 data **no longer accepted**. All transmissions must use V21 format.
- **April 30, 2027:** TA3 V21 transition period ends. Only V22 accepted after this date.

### 3.3 Technical Specification: EDIFACT-Based Format

#### 3.3.1 File Structure
The billing file uses **EDIFACT UNOC:3** syntax with variable-length segments.

```
UNB+I+IK-Sender:500+IK-Empfaenger:500+Datum:Uhrzeit+Referenznummer'
  UNH+1+SLGA:19'
    ... (summary message segments)
  UNT+42+1'
  UNH+2+SLLA:19'
    ... (case detail message segments)
  UNT+23+2'
UNZ+2+Referenznummer'
```

**Control characters:**
| Character | Function |
|-----------|----------|
| `+` | Data element separator |
| `:` | Component separator (within groups) |
| `,` | Decimal mark |
| `?` | Release/escape character |
| `'` | Segment terminator |

#### 3.3.2 Message Types
| Type | Name | Purpose |
|------|------|---------|
| **SLGA** | Gesamtaufstellung (Summary) | Invoice header, totals, VAT, provider info |
| **SLLA** | Abrechnungsdaten (Case Data) | Individual service records per patient |

#### 3.3.3 Service Provider Groups (Sammelgruppenschlüssel)
Relevant for SLLA segment structure:

| Key | Group | Relevance |
|-----|-------|-----------|
| **E** | Krankentransportleistungen | Patient transport billing |
| A | Hilfsmittel | Medical aids |
| B | Heilmittel | Remedies/therapies |
| C | Häusliche Krankenpflege | Home nursing (→ migrated to HKP XML) |
| F | Hebammen | Midwives |
| O | SAPV | Specialized palliative care |

**For Krankentransport (Key E), key SLLA segments include:**
- **FKT** — processing indicator (01=original, 02=supplemental, 03=co-payment, 04=correction)
- **NAD** — patient name and address
- **VDE** — insurance data (Kasse, Versichertennummer)
- **BEF** — transport details (date, route, vehicle type, distance)
- **VER** — prescription reference (Muster 4 data: physician, diagnosis, approval)
- **POS** — service position number (6-digit, per official directory)
- **BTR** — amounts (gross, co-payment, net)

#### 3.3.4 Position Numbers for Patient Transport
6-digit structure per official GKV directory:
- **Digit 1:** Prescription type (1=emergency, 5=taxi, 8/9=air)
- **Digit 2:** Transport type (2=multi-person, 4=carrying chair)
- **Digits 3-4:** Tariff type (01+=flat, 30+=distance, 50+=time, 70+=surcharges)
- **Digits 5-6:** Specifics (01/02=to/from hospital, 10=outpatient surgery, 30-39=series)

[Source: gkv-datenaustausch.de → Positionsnummernverzeichnis Krankentransportleistungen (28.10.2021)]

#### 3.3.5 Correction Procedures (Korrekturverfahren)
Mandatory **URI segment** for all corrections (VK 02/03/04):
```
URI+Original-LE-IK+Rechnungsnummer:Einzel-Rechnungsnummer+Datum+Belegnummer'
```

#### 3.3.6 Validation Levels
| Level | Check | Failure Action |
|-------|-------|---------------|
| **1** | Physical readability, UNB/UNZ syntax | File rejection |
| **2** | Field lengths, data types, segment sequence | File rejection |
| **3** | Code validity (Anlage 3), date logic, plausibility | Message rejection |
| **4** | Insurance-specific (contract, eligibility) | Individual rejection |

### 3.4 Transmission Infrastructure

**Recommended path:** Encrypted email via ITSG Trust Center PKI
- Provider uses private key for signing
- Insurer uses provider's public key for verification
- Public keys must be certified by ITSG Trust Center

**Required identifiers:**
- **Institutionskennzeichen (IK):** 9-digit provider ID, obtained from ARGE IK (dguv.de/arge-ik)
- **Betriebsstättennummer (BSNR):** Practice identifier
- **Lebenslange Arztnummer (LANR):** 9-digit physician ID

[Source: kbs.de → Datenaustausch §302 SGB V]

### 3.5 Key Differences: TA1 V20 → V21 (2026 Transition)

While the full changelog requires direct comparison of the PDF documents, key known changes in the 2026 transition include:

- **Anlage HKP 1.0.0:** Home nursing billing migrates from EDIFACT (Sammelgruppenschlüssel C) to standalone XML-based format with XSD schema
- Provisions for digitized original documents (*ImageLink-Verfahren* per Anhang 4a/b/c)
- Updated code directories in TA3 V21 reflecting changes in G-BA guidelines and contractual adjustments
- Mandatory use of current IK/BSNR formats

[Source: gkv-datenaustausch.de → Hinweise zur TA3 V21]

---

## 4. Billing Process: §302 SGB V for Patient Transport

### 4.1 End-to-End Flow

```
1. Physician issues Muster 4
   ↓
2. Patient presents Muster 4 to transport provider
   ↓
3. Provider verifies plausibility (rough check only)
   ↓
4. Provider executes transport and documents trip data
   ↓
5. Provider generates EDIFACT billing file (SLLA group E)
   ↓
6. File transmitted via encrypted email to insurer's data acceptance point
   ↓
7. Insurer validates (4-level check)
   ↓
8. Insurer issues Gutschrift (credit note) for review
   ↓
9. Provider reviews; if accepted → payment
   If objected → Gutschrift loses validity; negotiation begins
```

### 4.2 Key Requirements for Providers
| Requirement | Detail |
|-------------|--------|
| Institutionskennzeichen (IK) | Mandatory, obtained from ARGE IK |
| DTA contract | Signed with each insurer or via billing center |
| Billing software | Must be conformant with current TA1 and TA3 versions |
| Test transmissions | Mandatory before first live submission |
| Document retention | 2 years for exchange documentation |
| Original documents | Labeled with invoice number, sorted in invoice order |
| Co-payment collection | Provider must collect directly from patient |

### 4.3 Common Pitfalls
1. **Incomplete mandatory fields** (IK, insurance data, approval flags) → formal rejection
2. **Mismatch between disposition and billing data** → delays, queries
3. **Non-conformant software formats** → technical rejection
4. **Duplicate manual entry** from paper → transcription errors
5. **Missing or wrong processing indicators** in FKT segment

[Source: sandispo.de/blog; vspv-nrw.de Unternehmerleitfaden]

---

## 5. Transitional Deadlines & Compatibility 2026

### 5.1 Immediate Deadlines (Already Passed)
| Date | Event |
|------|-------|
| **Jan 1, 2026** | TA1 V21 mandatory for all §302 transmissions. V20 no longer accepted. |
| **Dec 31, 2025** | TA3 V20 transition period ended. V21 mandatory from Jan 1, 2026. |

### 5.2 Upcoming Deadlines
| Date | Event | Action Required |
|------|-------|----------------|
| **Feb 1, 2027** | TA3 V22 effective | Update software to use new code directories |
| **Apr 30, 2027** | TA3 V21 transition ends | V21 deprecated; V22 mandatory |
| **Feb 1, 2027** | Anlage HKP V1.2.0 effective | Home nursing providers must switch to XML format |
| **~2028** | Anticipated gematik eVerordnung rollout | Digital Muster 4 may become mandatory |

### 5.3 Compatibility Considerations for 2026
- **TA1 V21 is the ONLY accepted format.** Any system still generating V20 will be rejected at Level 1.
- **TA3 V21 code directories** must be used for all lookup values (position numbers, keys).
- **IK/BSNR validity:** Ensure all identifiers are current and match the SVI registry.
- **Anlage 2b BMV-Ä** permits voluntary use of digital e04 (Muster 4) forms — providers may begin transitioning workflow even before mandate.
- **AOK pilot** demonstrates that digital Muster 4 is operationally viable and drastically reduces error rates.

---

## 6. Official References

### Legal Texts
| Source | URL | Version/Date |
|--------|-----|-------------|
| §302 SGB V (Gesetzestext) | https://www.gesetze-im-internet.de/sgb_5/__302.html | Current |
| §60 SGB V (Fahrkosten) | https://www.gesetze-im-internet.de/sgb_5/__60.html | Current |
| §301a SGB V | https://www.gesetze-im-internet.de/sgb_5/__301a.html | Current |

### G-BA Directive
| Source | URL | Version/Date |
|--------|-----|-------------|
| Krankentransport-Richtlinie (KT-RL) | https://www.g-ba.de/richtlinien/25/ | May 15, 2025, effective Aug 6, 2025 |

### BMV-Ä (Bundesmantelvertrag) Anlagen
| Source | URL | Version/Date |
|--------|-----|-------------|
| Anlage 2: Vordruckvereinbarung | https://www.kbv.de/html/vordrucke.php | Current |
| Anlage 2b: Digitale Vordrucke | https://www.gkv-spitzenverband.de/.../2025_07_Anlage_2b_BMV-Ae_Lesefassung.pdf | July 1, 2025 |
| Anlage 6: DA-Vertrag (DTA) | https://www.gkv-spitzenverband.de/.../2025_10_01_DA_Vertrag.pdf | October 1, 2025 |

### GKV-Datenaustausch Technical Specifications
| Source | URL | Version/Date |
|--------|-----|-------------|
| Portal (Sonstige Leistungserbringer) | https://www.gkv-datenaustausch.de/leistungserbringer/sonstige_leistungserbringer/ | Current |
| Technische Anlage 1 (V21) | https://www.gkv-datenaustausch.de/.../sonstige_leistungserbringer/ | Stand 15.01.2026 |
| Technische Anlage 3 (V21) | https://www.gkv-datenaustausch.de/.../sonstige_leistungserbringer/ | Stand 19.09.2025 |
| Positionsnummernverzeichnis Krankentransport | https://www.gkv-datenaustausch.de/media/dokumente/.../Krankentransportleistungen_20211028.pdf | Oct 28, 2021 |
| Richtlinien-Text §302 | https://www.gkv-datenaustausch.de/media/dokumente/.../Richtlinien-Text_061120.pdf | Current |

### Digital Muster 4 / eVerordnung
| Source | URL | Version/Date |
|--------|-----|-------------|
| gematik Impulspapier | https://www.gematik.de/newsroom/news-detail/impulspapier-fuer-digitale-verordnung-von-krankenbefoerderung | Sep 23, 2025 |
| gematik Impulspapier (PDF) | https://www.gematik.de/media/gematik/.../Impulspapier_Krankentransport.pdf | Sep 2025 |

### Practitioner Guides & Supporting Material
| Source | URL | Version/Date |
|--------|-----|-------------|
| KBV Praxisinfo Krankenbeförderung | https://www.kbv.de/praxis/verordnungen/krankenbefoerderung | Current |
| VSPV-NRW Unternehmerleitfaden | https://www.vspv-nrw.de/images/UnternehmerleitfadenKrankenfahrtenVSPV.pdf | Dec 10, 2025 |
| Sandispo Abrechnungsguide | https://sandispo.de/blog/so-funktioniert-die-abrechnung-von-krankenfahrten-nach-302-sgb-v | Current |
| DMRZ: Digitale Verordnung Muster 4 | https://www.dmrz.de/blog/digitale-verordnung-fuer-krankenfahrten-der-weg-zum-papierlosen-muster-4 | Dec 11, 2025 |
| DMRZ: Positionsnummern-Übersicht | https://www.dmrz.de/wissen/ratgeber/alle-positionsnummern-fuer-sonstige-leistungserbringer-in-der-uebersicht | Current |
| KNAPPSCHAFT DTA Guide | https://www.kbs.de/DE/Services/FuerLeistungserbringer/Datenaustausch/302/datenaustausch_node | Current |
| Wikipedia: Datenaustausch §302 SGB V | https://de.wikipedia.org/wiki/Datenaustausch_nach_%C2%A7_302_SGB_V | Current |

---

## Appendix: Glossary

| Term | Definition |
|------|-----------|
| **BSNR** | Betriebsstättennummer — practice identifier (9 digits) |
| **DTA** | Datenträgeraustausch — framework for electronic data exchange between KBV/KVs and insurers |
| **EDIFACT** | UN/EDIFACT — international standard for electronic data interchange; used as syntax basis for TA1 |
| **eHBA** | elektronischer Heilberufsausweis — electronic Health Professional Card |
| **G-BA** | Gemeinsamer Bundesausschuss — Federal Joint Committee; issues KT-RL |
| **gematik** | National agency for Telematics Infrastructure; driving digital Muster 4 initiative |
| **GKV** | Gesetzliche Krankenversicherung — Statutory Health Insurance |
| **GKV-SV** | GKV-Spitzenverband — National Association of Statutory Health Insurance Funds |
| **IK** | Institutionskennzeichen — institutional identification number (9 digits) |
| **KBV** | Kassenärztliche Bundesvereinigung — National Association of Statutory Health Insurance Physicians |
| **KIM** | Kommunikation im Medizinwesen — secure messaging service for healthcare |
| **KT-RL** | Krankentransport-Richtlinie — G-BA directive on medical transport |
| **KTW** | Krankentransportwagen — specialized medical transport vehicle |
| **LANR** | Lebenslange Arztnummer — lifelong physician identification number (9 digits) |
| **Muster 4** | Vordruckmuster 4 — standardized prescription form for patient transport |
| **SGB V** | Sozialgesetzbuch, Fünftes Buch — Social Code Book V (statutory health insurance) |
| **SLLA** | Message type for detailed billing case data in EDIFACT format |
| **SLGA** | Message type for summary invoice data in EDIFACT format |
| **SMC-B** | Security Module Card Type B — practice identity card |
| **TA1 / TA3** | Technische Anlage 1 (data format) / Technische Anlage 3 (code directories) |
| **TI** | Telematikinfrastruktur — national healthcare telematics infrastructure |
| **VK** | Verarbeitungskennzeichen — processing indicator (01-04) |
