# Private fields are not in this folder

This is the instructor's whole-course handoff for YVC 42052 (27 Oct 2026), with
its private parts removed because this repository is public:

- `lessons/*.json`: each `steps[].check` has had `correct_choice_id` and
  `feedback_he` removed. Checks keep their `key`, so the private values can be
  joined back by `lesson slug` + `check key`.
- `course.json`: `instructor.email` was removed. Text sources show a placeholder.

The private values (39 checks plus the instructor email) live in a separate JSON
file the instructor holds. The instructor loads it into the database, and it is
never committed. Student APIs must not return those values until the relevant
feedback stage.

Read `START-HERE.txt`, then `COURSE-HANDOFF.txt`.
