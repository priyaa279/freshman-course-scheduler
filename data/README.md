# Data

The dataset used in this project is **synthetic**, generated to model RIT's program and course structure. It does not contain real student enrollment data, real section meeting times, or real RIT operational data.

## Dataset Summary

| Attribute | Value |
|---|---|
| Programs | 44 |
| Students | 4,155 |
| Sections | 634 |
| Courses | 148 |
| Total Capacity | 25,197 |

## Input Files

| File | Description |
|---|---|
| `course_sections.csv` | Course sections with capacity and meeting times |
| `program_course_requirements.csv` | Required courses per program |
| `program_cohort_distribution.csv` | Freshman cohort sizes per program |

> Student records are generated programmatically from `program_cohort_distribution.csv` at runtime; they are not stored as a static file.

## Note

The dataset accurately reflects RIT's program structure and course requirements (program names, course codes, requirement logic) but all numerical values — enrollment counts, section capacities, meeting times — are synthetically generated.
