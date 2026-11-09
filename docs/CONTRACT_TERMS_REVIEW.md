# Fixed contract terms — template v2

Requested scope: remove booking-specific variables from the general terms and
review their drafting in an Omani legal context. Implemented on the local instance;
this is drafting assistance, not a legal opinion that the property is licensed or
that this document alone satisfies registration, enforceability or signing needs.

## Structure

`terms_v2.html` contains nine literal HTML pages, with no Django variables or
template tags. Names, identity details, unit, dates, rent and deposit appear on the
data/signature pages. The general terms define “contract data”, “lessor”, “guest”
and “unit” and refer to that data and written, accepted annexes. Missing information
does not become an invented agreement. A regression test changes booking details
and verifies that the entire rendered general-terms block remains byte-identical.

## Drafting changes

- Defined incorporation and priority of documents; added article 9 to the previous
  numbering gap. Mandatory law prevails. Internal system notes or unpublished
  policies do not unilaterally change an agreement.
- Separated rent, deposits and evidence of receipt. Deposit deductions require
  stated reasons and supporting evidence; ordinary wear is excluded.
- Removed assumed guest counts and service inclusions; the actual booking and
  agreed service annex govern them. Annexes are not claimed to exist by default.
- Qualified late departure, cancellation and extra-service charges by disclosed,
  accepted arrangements and applicable law; no automatic forfeiture or invented fee.
- Preserved maintenance duties, privacy, lawful access and actual-damage limits.
  No self-help eviction, seizure or utility disconnection is authorized.
- Clarified legal classification, registration and competent forum without
  assuming every stay is legally identical to a residential tenancy or hotel stay.
- Distinguished signature-image placement from proof of tenant acceptance,
  payment or possession. Later system versions do not automatically amend a
  previously agreed contract.

## Sources consulted, 2026-11-09

- [Civil Transactions Law, Royal Decree 29/2013](https://qanoon.om/p/2013/rd2013029/):
  articles 1, 155–159, 165–172 and 264–267 informed the drafting checks on contractual
  duties, interpretation, changes, force majeure and compensation.
- [Tenancy provisions, Royal Decree 6/89, consolidated through 12/2025](https://qanoon.om/p/1989/l1989006/):
  checked registration, delivery/maintenance, ordinary wear and the possibility
  that special tenancy rules override a generic stay form. Applicability depends
  on the actual legal relationship; the form does not decide it.
- The ministry legislation and PDF endpoints returned timeouts in this session;
  the published statutory text on Qanoon was consulted. This is not an assertion
  that all later amendments or property-specific licensing requirements were verified.

## Version handling

New snapshots use `atheer-short-v2`. The v1 template and assets remain available
for historical snapshots. Existing generated contracts may receive a new version;
previous snapshots, PDFs and uploaded agreements are never replaced by this change.
The lessor signature remains populated from the authorized private profile image;
tenant signature fields remain blank.
# Plain-language revision (atheer-v5 / terms_v3)

The 35 articles retain their numbering and subjects, with shorter sentences and fewer examples. The terms remain static and independent of guest, price and date fields. Earlier templates and PDF revisions remain available; generating a new revision does not amend an existing agreement by itself.

The comparison retained: payment evidence and independent deposit (3–4); documented services and ordinary-wear exclusions (6–8); mandatory-law and agreed-document priority (9); proportionate damage liability (10–19, 29); maintenance, privacy and emergency limits (20–21); lawful departure and no automatic penalty (25–26); accepted cancellation terms and evidence-based early-departure settlement (27–28); inventory and hidden-defect rights (30); prior approval of extra services and fees (31–32); force-majeure effects determined by law (33); competent forum and no unlawful self-help (34); acceptance, revision history and limits of the lessor signature image as evidence (35).

This is a language simplification, not a legal opinion guaranteeing equivalent enforceability. The earlier legal-review limitations and sources still apply; final review requires an Omani lawyer familiar with the property's licensing and actual use.
