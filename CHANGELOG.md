# Changelog

## 2026-09-13

- Added route-level acceptance coverage for the complete New OB patient-day
  workflow, including registration, scheduling, check-in, intake, clinical
  documentation, lab ordering, prescription safety behavior, follow-up
  scheduling, billing checkout, and billing-clerk clinical-note isolation.
- Added route-level acceptance coverage for clinic-admin correction of a
  duplicate patient, including active-view hiding, retained-row recovery, and
  delete audit verification.
- Fixed the queue's clinical patient link so it opens the latest active visit
  documented for that queue date instead of starting a blank visit.
- Added a gestational-age-based prenatal follow-up recommendation to the
  scheduling workspace and preserved the patient selection when the booking
  handoff moves from clinical staff to front desk.