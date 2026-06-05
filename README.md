# Automated Freshman Course Scheduling — LLM-Generated Constraints + CP-SAT Optimization

An end-to-end course-scheduling system that assigns **4,155 freshmen to 634 sections** under hard institutional policies — where the policies are written in plain English by an administrator and translated into verified solver constraints by an LLM, then optimized with Google OR-Tools CP-SAT.

**Stack:** Python · Google OR-Tools (CP-SAT) · Anthropic Claude API · Power BI.

> Capstone Project — Rochester Institute of Technology, Golisano College of Computing and Information Sciences.

---

## Why this project

Freshman scheduling has a structural gap: the people who *own* the policies aren't the people who can *encode* them. An administrator knows "no more than a quarter of an intro CS section should be CS majors, so other programs can get seats" — but turning that sentence into a correct constraint over hundreds of thousands of decision variables requires optimization expertise they don't have. So policies get applied by hand, slowly, and inconsistently.

This project closes that gap. It is built around one idea: **let the administrator write the policy in English, and make the machine responsible for translating it correctly and proving it's safe to run.** The system is three layers in service of that:

1. **Natural-language constraint generation** — an LLM turns a plain-English policy into CP-SAT constraint code.
2. **Verification** — generated code is validated for syntax and safety *before* it ever touches the solver.
3. **Optimization** — CP-SAT assigns students to sections, respecting every active constraint, with zero time conflicts.

---

## Architecture

```
Plain-English policy
        │  llm_interface.py
        ▼
LLM constraint generation        (Claude API; 44 exact program names injected)
        │  llm_constraint_generator.py
        ▼
Verification                     (syntax check + regex reject of unknown program codes)
        │  verify_constraints.py
        ▼
Constraint loading               (inject validated constraints into the model)
        │  constraint_loader.py
        ▼
CP-SAT optimization              (8 workers · 300s limit · zero time conflicts)
        │  constraint_scheduler.py  +  data_validation.py
        ▼
Orchestration → output CSVs      (pipeline.py)
        │
        ▼
Power BI dashboard (3 pages)
```

---

## Analytical & engineering products

### 1. Natural-language → CP-SAT constraint generation

An administrator types a policy; the LLM returns runnable constraint code. Example:

**Input:**
```
No more than 25% of seats in any CSCI 141 section should go to Computer Science BS students.
```

**Generated:**
```python
# 25% cap: COMPSCI-BS students per CSCI-141 section
for section_id in csci141_sections:
    cap = int(section_capacities[section_id] * 0.25)
    model.Add(
        sum(x[s, section_id] for s in compsci_bs_students
            if (s, section_id) in x) <= cap
    )
```

Across the tested constraint types, generated code hit **100% syntax validity**.

### 2. Hallucination prevention — the part that actually matters

An LLM writing code against a real schema will invent program names that don't exist, and a single bad identifier silently breaks a constraint. Two defenses handle this:

- **All 44 program names are injected into the prompt** with strict instructions to use only those.
- **Post-generation regex validation** rejects any code referencing a program code not in the known set — the generated constraint is thrown out *before* it reaches the solver, not after it corrupts a run.

This is the difference between a demo and something an administrator could trust.

### 3. CP-SAT scheduling model

The solver assigns students to sections under capacity, program-requirement, and time-conflict constraints. It runs with **8 search workers** (of 16 cores — deliberately capped to preserve system responsiveness and absorb CP-SAT coordination overhead) and a **300-second** time limit.

---

## Key findings

- **The 25% CSCI 141 cap is the headline result.** Applying it cut maximum section enrollment from **28 → 10 students** across 10 previously over-cap sections — a concrete, visible redistribution driven entirely by an English-language policy.
- **Hard constraints beat soft constraints for distribution.** A soft-constraint formulation could actually *worsen* the spread (standard deviation went up); the hard cap improved it. A useful, slightly counterintuitive finding about when "soft" isn't safer.
- **Constraint stacking has a ceiling.** Two simultaneous constraints solved cleanly; three or more pushed the solver past its time limit (~310s). A real scalability boundary, reported as found.
- **Infeasibility is detected, not faked.** Deliberately tight capacity correctly drives the solver to UNKNOWN/infeasible rather than returning a silently-wrong schedule.

---

## Engineering & data-quality notes

- **API error handling distinguishes failure types.** A 529 overload error retries with a clean prompt; a validation error retries with the error fed back in. Retry delays are staged (5s / 10s). Treating these the same would either waste retries or fail to self-correct.
- **Demand allocation is computed from input, independent of solver output.** `section_program_breakdown.csv` is derived purely from input data, so it stays valid even if the synthetic student-generation step is removed — the analysis doesn't secretly depend on one particular solver run.
- **Dashboard source discipline.** Power BI reads only *output* files, never input files, so the dashboard always reflects an actual scheduling result rather than pre-solve assumptions.
- **Reproducibility caveat.** The baseline objective value is **not stable between runs**, so it is not reported as a headline metric — the stable, reportable facts are 100% feasibility, zero time conflicts, and zero violations.

---

## Honest limitations

This is a **synthetic dataset**, modeled on RIT's program structure but not real enrollment. Program names, course codes, and requirement logic mirror RIT; all numeric values — enrollment counts, section capacities, meeting times — are generated.

The solver returns **FEASIBLE, not OPTIMAL**, within the 300s budget — appropriate for an NP-hard timetabling problem at this scale, but worth stating plainly. And as noted above, three-plus stacked constraints can time out.

This is reported as-is. The value of the project is the **end-to-end capability** — natural-language policy capture, verified constraint generation, and optimization at realistic scale — applied correctly. On real enrollment data, the same pipeline carries over directly.

---

## Dataset

| Attribute | Value |
|---|---|
| Programs | 44 |
| Students | 4,155 |
| Sections | 634 |
| Courses | 148 |
| Total capacity | 25,197 |

Input files: `course_sections.csv`, `program_course_requirements.csv`, `program_cohort_distribution.csv`. Student records are generated at runtime from the cohort distribution.

---

## Repository structure

```
src/
  pipeline.py                  End-to-end orchestration
  data_validation.py           Input validation
  constraint_scheduler.py      Core CP-SAT scheduling model
  constraint_loader.py         Injects validated constraints into the model
  llm_interface.py             Admin-facing plain-English interface
  llm_constraint_generator.py  Claude API → CP-SAT constraint code
  verify_constraints.py        Syntax + safety validation
config/
  llm_config.yaml              LLM configuration
data/
  course_sections.csv          Synthetic — see data/README.md
  program_course_requirements.csv
  program_cohort_distribution.csv
outputs/
  20260419_203351/             Sample baseline run
dashboard/
  scheduler_dashboard.pbix     Power BI dashboard (3 pages)
  screenshots/                 Dashboard page exports
docs/
  poster.pptx                  Capstone poster
  poster_final.pdf
```

---

## Setup

```bash
git clone https://github.com/priyaa279/freshman-course-scheduler.git
cd freshman-course-scheduler
pip install -r requirements.txt
cp .env.example .env          # add your Anthropic API key
```

Run the baseline (no constraints):
```bash
python src/pipeline.py
```

Run with plain-English constraints:
```bash
python src/llm_interface.py
```

---

## Dashboard

Three pages in Power BI Desktop, built from output CSVs only.

### Blocked Students

![Blocked Students](dashboard/screenshots/blocked_students.png)

Students blocked or redistributed by the active cap constraints — the visible effect of an English-language policy on section assignments.

### Program Enrollment

![Program Enrollment](dashboard/screenshots/program_enrollment.png)

Per-program assignment analysis across sections.

### Section Utilization

![Section Utilization](dashboard/screenshots/section_utilization.png)

Capacity utilization rates per section.

---

## One-line summary

> Built an end-to-end freshman course scheduler (4,155 students, 634 sections) that lets administrators write scheduling policies in plain English — an LLM translates them into verified CP-SAT constraints with hallucination guards, and Google OR-Tools optimizes the assignment with zero time conflicts. A single English policy (25% CS cap on intro CS) cut max section enrollment from 28 to 10.

---

## License

MIT
