-- Stage one of the card-file redesign: dates go into the plan without a confirm step, and the
-- student can add or change one. Keep what the syllabus said next to what the student set.
--
-- due_date            the date the plan uses (the student's, once they set one)
-- extracted_due_date  the date extraction found, never changed afterwards (NULL = none found)
-- status              'unchecked' as extracted, 'edited' once the student's date differs from the
--                     extracted one, 'skipped' when they picked "Not sure yet"
--
-- Never add a column for the extended-time multiplier, free hours, or block durations.

ALTER TABLE items ADD COLUMN extracted_due_date TEXT;

UPDATE items SET extracted_due_date = due_date;
