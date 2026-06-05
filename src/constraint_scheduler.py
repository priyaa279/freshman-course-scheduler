"""
Step 2: Constraint-Based Scheduling - FINAL VERSION
====================================================
Schedules all students and exports results organized by program.
Now includes automatic loading and application of LLM-generated constraints.

Output Structure:
  output/YYYYMMDD_HHMMSS/
    ├── student_assignments.csv      (all assignments)
    ├── section_enrollment.csv       (section utilization)
    ├── scheduling_summary.csv       (overall metrics)
    ├── program_summary.csv          (per-program stats)
    ├── section_program_breakdown.csv (students per program per section)
    └── programs/
        ├── ACCT-BS/
        │   └── student_assignments.csv
        ├── ADPR-BS/
        │   └── student_assignments.csv
        └── ... (one folder per program)
"""

import pandas as pd
import random
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import time

from ortools.sat.python import cp_model
from constraint_loader import ConstraintLoader


class ConstraintScheduler:
    """Constraint-based scheduler with program-organized output."""
    
    def __init__(self, sections_path: str, cohorts_path: str, requirements_path: str, output_dir: str = None):
        self.sections_path = Path(sections_path)
        self.cohorts_path = Path(cohorts_path)
        self.requirements_path = Path(requirements_path)
        self.output_dir = Path(output_dir) if output_dir else self.sections_path.parent.parent / "output"
        
        self.sections_df = None
        self.cohorts_df = None
        self.requirements_df = None
        
        self.sections = {}
        self.students = []
        self.time_slots = {}
        self.conflicting_slots = defaultdict(set)
        
        self.model = None
        self.solver = None
        self.assignment_vars = {}
        self.assignments = {}
        
        self._constraint_loader = None
        
        self.stats = {
            'total_students': 0,
            'fully_scheduled': 0,
            'partially_scheduled': 0,
            'solver_status': '',
            'solve_time': 0,
            'objective_value': 0
        }
    
    def load_data(self) -> bool:
        print("\n" + "=" * 60)
        print("LOADING DATA")
        print("=" * 60)
        
        try:
            self.sections_df = pd.read_csv(self.sections_path)
            print(f"✓ Loaded {self.sections_path.name}: {len(self.sections_df)} sections")
        except Exception as e:
            print(f"✗ Failed to load sections: {e}")
            return False
        
        try:
            self.cohorts_df = pd.read_csv(self.cohorts_path)
            print(f"✓ Loaded {self.cohorts_path.name}: {len(self.cohorts_df)} programs")
        except Exception as e:
            print(f"✗ Failed to load cohorts: {e}")
            return False
        
        try:
            self.requirements_df = pd.read_csv(self.requirements_path)
            print(f"✓ Loaded {self.requirements_path.name}: {len(self.requirements_df)} requirements")
        except Exception as e:
            print(f"✗ Failed to load requirements: {e}")
            return False
        
        return True
    
    def _time_to_minutes(self, time_str: str) -> int:
        h, m = map(int, time_str.split(':'))
        return h * 60 + m
    
    def _get_time_slot_id(self, days: str, start: str, end: str) -> int:
        key = (days, start, end)
        if key not in self.time_slots:
            self.time_slots[key] = len(self.time_slots)
        return self.time_slots[key]
    
    def _compute_conflicts(self) -> None:
        slots = list(self.time_slots.items())
        
        for i, ((days1, start1, end1), id1) in enumerate(slots):
            start1_mins = self._time_to_minutes(start1)
            end1_mins = self._time_to_minutes(end1)
            
            for (days2, start2, end2), id2 in slots[i:]:
                if id1 == id2:
                    continue
                
                days_overlap = any(d in days2 for d in days1)
                if not days_overlap:
                    continue
                
                start2_mins = self._time_to_minutes(start2)
                end2_mins = self._time_to_minutes(end2)
                
                if not (end1_mins <= start2_mins or end2_mins <= start1_mins):
                    self.conflicting_slots[id1].add(id2)
                    self.conflicting_slots[id2].add(id1)
    
    def _parse_sections(self) -> None:
        print("\n" + "=" * 60)
        print("PARSING SECTIONS")
        print("=" * 60)
        
        day_cols = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        
        for _, row in self.sections_df.iterrows():
            course = f"{row['Course Subject']} {row['Course Catalog Code']}"
            days = ''.join([col[0] if row[col] == 'Y' else '' for col in day_cols])
            time_slot_id = self._get_time_slot_id(days, row['Start Time'], row['End Time'])
            
            section_info = {
                'course': course,
                'section_code': row['Class Section Code'],
                'capacity': row['Enrollment Capacity'],
                'start_time': row['Start Time'],
                'end_time': row['End Time'],
                'days': days,
                'time_slot_id': time_slot_id,
                'start_minutes': self._time_to_minutes(row['Start Time'])
            }
            
            if course not in self.sections:
                self.sections[course] = []
            self.sections[course].append(section_info)
        
        self._compute_conflicts()
        
        print(f"✓ Parsed {sum(len(s) for s in self.sections.values())} sections for {len(self.sections)} courses")
        print(f"✓ Identified {len(self.time_slots)} unique time slots")
    
    def _generate_students(self) -> None:
        print("\n" + "=" * 60)
        print("GENERATING STUDENTS")
        print("=" * 60)
        
        student_counter = 1
        
        for _, cohort in self.cohorts_df.iterrows():
            program = cohort['Student Plan']
            num_students = cohort['Number of Expected New Students']
            
            prog_reqs = self.requirements_df[self.requirements_df['Student Plan'] == program]
            
            block_courses = []
            
            for _, req in prog_reqs.iterrows():
                course = f"{req['Course Subject']} {req['Course Catalog Code']}"
                if req['Priority Type'] == 'Block for Required Core':
                    block_courses.append(course)
            
            pct_cols = [col for col in cohort.index if col.startswith('Pct in')]
            math_probs = {}
            for col in pct_cols:
                pct = cohort[col]
                if pct > 0:
                    math_num = col.replace('Pct in Math', '')
                    course = f"MATH {math_num}"
                    math_probs[course] = pct
            
            print(f"\n{program}: {num_students} students, {len(block_courses)} block courses")
            
            for i in range(num_students):
                student_id = f"{program[:4]}_{student_counter:04d}"
                student_counter += 1
                
                required = block_courses.copy()
                
                if math_probs:
                    math_course = random.choices(
                        list(math_probs.keys()),
                        weights=list(math_probs.values()),
                        k=1
                    )[0]
                    if math_course in self.sections:
                        required.append(math_course)
                
                self.students.append({
                    'student_id': student_id,
                    'program': program,
                    'required_courses': required
                })
        
        self.stats['total_students'] = len(self.students)
        print(f"\n✓ Generated {len(self.students)} students")
    
    def _apply_custom_constraints(self, objective_terms: list) -> None:
        """Load and apply LLM-generated custom constraints."""
        constraints_dir = self.output_dir.parent / "output" / "generated_constraints"
        loader = ConstraintLoader(constraints_dir)
        num_valid = loader.load_all()
        if num_valid > 0:
            loader.apply_all(
                model=self.model,
                students=self.students,
                sections=self.sections,
                assignment_vars=self.assignment_vars,
                objective_terms=objective_terms,
            )
        self._constraint_loader = loader
    
    def _build_model(self) -> None:
        print("\n" + "=" * 60)
        print("BUILDING CONSTRAINT MODEL")
        print("=" * 60)
        
        self.model = cp_model.CpModel()
        
        print("\nCreating decision variables...")
        
        for student in self.students:
            sid = student['student_id']
            self.assignment_vars[sid] = {}
            
            for course in student['required_courses']:
                if course in self.sections:
                    self.assignment_vars[sid][course] = {}
                    for idx, section in enumerate(self.sections[course]):
                        var_name = f"assign_{sid}_{course}_{idx}"
                        self.assignment_vars[sid][course][idx] = self.model.NewBoolVar(var_name)
        
        num_vars = sum(
            len(sections) 
            for student_courses in self.assignment_vars.values() 
            for sections in student_courses.values()
        )
        print(f"✓ Created {num_vars} decision variables")
        
        # HARD CONSTRAINT 1: Exactly one section per course
        print("\nAdding Hard Constraint 1: One section per course...")
        
        constraint_count = 0
        for student in self.students:
            sid = student['student_id']
            for course in student['required_courses']:
                if course in self.assignment_vars[sid]:
                    self.model.Add(
                        sum(self.assignment_vars[sid][course].values()) == 1
                    )
                    constraint_count += 1
        
        print(f"✓ Added {constraint_count} constraints")
        
        # HARD CONSTRAINT 2: No time conflicts
        print("\nAdding Hard Constraint 2: No time conflicts...")
        
        constraint_count = 0
        for student in self.students:
            sid = student['student_id']
            courses = list(self.assignment_vars[sid].keys())
            
            for i, course1 in enumerate(courses):
                for course2 in courses[i+1:]:
                    for idx1, section1 in enumerate(self.sections[course1]):
                        slot1 = section1['time_slot_id']
                        
                        for idx2, section2 in enumerate(self.sections[course2]):
                            slot2 = section2['time_slot_id']
                            
                            if slot1 == slot2 or slot2 in self.conflicting_slots[slot1]:
                                self.model.Add(
                                    self.assignment_vars[sid][course1][idx1] +
                                    self.assignment_vars[sid][course2][idx2] <= 1
                                )
                                constraint_count += 1
        
        print(f"✓ Added {constraint_count} conflict constraints")
        
        # HARD CONSTRAINT 3: Section capacity
        print("\nAdding Hard Constraint 3: Section capacity...")
        
        constraint_count = 0
        for course, sections in self.sections.items():
            for idx, section in enumerate(sections):
                students_in_section = []
                for student in self.students:
                    sid = student['student_id']
                    if course in self.assignment_vars.get(sid, {}):
                        if idx in self.assignment_vars[sid][course]:
                            students_in_section.append(
                                self.assignment_vars[sid][course][idx]
                            )
                
                if students_in_section:
                    self.model.Add(
                        sum(students_in_section) <= section['capacity']
                    )
                    constraint_count += 1
        
        print(f"✓ Added {constraint_count} capacity constraints")
        
        # SOFT CONSTRAINT: Balance enrollment across sections
        print("\nAdding Soft Constraint: Balance enrollment...")
        
        objective_terms = []
        balance_weight = 10
        
        for course, sections in self.sections.items():
            if len(sections) > 1:
                section_enrollments = []
                for idx, section in enumerate(sections):
                    enrollment = []
                    for student in self.students:
                        sid = student['student_id']
                        if course in self.assignment_vars.get(sid, {}):
                            if idx in self.assignment_vars[sid][course]:
                                enrollment.append(self.assignment_vars[sid][course][idx])
                    
                    if enrollment:
                        section_var = self.model.NewIntVar(0, section['capacity'], f"enroll_{course}_{idx}")
                        self.model.Add(section_var == sum(enrollment))
                        section_enrollments.append(section_var)
                
                if len(section_enrollments) >= 2:
                    max_enroll = self.model.NewIntVar(0, 1000, f"max_{course}")
                    min_enroll = self.model.NewIntVar(0, 1000, f"min_{course}")
                    self.model.AddMaxEquality(max_enroll, section_enrollments)
                    self.model.AddMinEquality(min_enroll, section_enrollments)
                    
                    diff = self.model.NewIntVar(0, 1000, f"diff_{course}")
                    self.model.Add(diff == max_enroll - min_enroll)
                    objective_terms.append(diff * balance_weight)
        
        # Apply any LLM-generated custom constraints
        self._apply_custom_constraints(objective_terms)
        
        if objective_terms:
            self.model.Minimize(sum(objective_terms))
            print(f"✓ Objective function with {len(objective_terms)}")
    
    def solve(self) -> bool:
        print("\n" + "=" * 60)
        print("SOLVING CONSTRAINT MODEL")
        print("=" * 60)
        
        self.solver = cp_model.CpSolver()
        
        self.solver.parameters.max_time_in_seconds = 300.0
        self.solver.parameters.num_search_workers = 8
        
        print("\nSolving... (this may take a moment)")
        start_time = time.time()
        
        status = self.solver.Solve(self.model)
        
        self.stats['solve_time'] = time.time() - start_time
        
        status_names = {
            cp_model.OPTIMAL: 'OPTIMAL',
            cp_model.FEASIBLE: 'FEASIBLE',
            cp_model.INFEASIBLE: 'INFEASIBLE',
            cp_model.MODEL_INVALID: 'MODEL_INVALID',
            cp_model.UNKNOWN: 'UNKNOWN'
        }
        
        self.stats['solver_status'] = status_names.get(status, 'UNKNOWN')
        
        print(f"\n✓ Solver finished in {self.stats['solve_time']:.2f} seconds")
        print(f"✓ Status: {self.stats['solver_status']}")
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            self.stats['objective_value'] = self.solver.ObjectiveValue()
            print(f"✓ Objective value: {self.stats['objective_value']:.0f}")
            self._extract_solution()
            return True
        else:
            print("✗ No solution found!")
            return False
    
    def _extract_solution(self) -> None:
        print("\nExtracting solution...")
        
        for student in self.students:
            sid = student['student_id']
            self.assignments[sid] = {
                'program': student['program'],
                'courses': {}
            }
            
            for course in self.assignment_vars.get(sid, {}):
                for idx in self.assignment_vars[sid][course]:
                    if self.solver.Value(self.assignment_vars[sid][course][idx]) == 1:
                        self.assignments[sid]['courses'][course] = self.sections[course][idx]
                        break
            
            if len(self.assignments[sid]['courses']) == len(student['required_courses']):
                self.stats['fully_scheduled'] += 1
            else:
                self.stats['partially_scheduled'] += 1
        
        print(f"✓ Extracted assignments for {len(self.assignments)} students")
    
    def export_results(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_folder = self.output_dir / timestamp
        output_folder.mkdir(parents=True, exist_ok=True)
        
        print("\n" + "=" * 60)
        print("EXPORTING RESULTS")
        print("=" * 60)
        
        # 1. All student assignments (combined)
        all_assignments = []
        for sid, data in self.assignments.items():
            for course, section in data['courses'].items():
                all_assignments.append({
                    'Student ID': sid,
                    'Program': data['program'],
                    'Course': course,
                    'Section': section['section_code'],
                    'Days': section['days'],
                    'Start Time': section['start_time'],
                    'End Time': section['end_time']
                })
        
        assignments_df = pd.DataFrame(all_assignments)
        assignments_df = assignments_df.sort_values(['Student ID', 'Course'])
        assignments_path = output_folder / "student_assignments.csv"
        assignments_df.to_csv(assignments_path, index=False)
        print(f"✓ {assignments_path.name} ({len(all_assignments)} assignments)")
        
        # 2. Section enrollment summary
        enrollment_data = []
        section_enrollment = defaultdict(lambda: defaultdict(int))
        
        for sid, data in self.assignments.items():
            for course, section in data['courses'].items():
                section_enrollment[course][section['section_code']] += 1
        
        for course, sections in self.sections.items():
            for section in sections:
                enrolled = section_enrollment[course][section['section_code']]
                enrollment_data.append({
                    'Course': course,
                    'Section': section['section_code'],
                    'Capacity': section['capacity'],
                    'Enrolled': enrolled,
                    'Available': section['capacity'] - enrolled,
                    'Utilization': f"{enrolled/section['capacity']*100:.1f}%"
                })
        
        enrollment_df = pd.DataFrame(enrollment_data)
        enrollment_df = enrollment_df.sort_values(['Course', 'Section'])
        enrollment_path = output_folder / "section_enrollment.csv"
        enrollment_df.to_csv(enrollment_path, index=False)
        print(f"✓ {enrollment_path.name}")
        
        # 3. Overall summary
        summary_data = [
            {'Metric': 'Total Students', 'Value': self.stats['total_students']},
            {'Metric': 'Fully Scheduled', 'Value': self.stats['fully_scheduled']},
            {'Metric': 'Partially Scheduled', 'Value': self.stats['partially_scheduled']},
            {'Metric': 'Success Rate', 'Value': f"{self.stats['fully_scheduled']/self.stats['total_students']*100:.1f}%"},
            {'Metric': 'Solver Status', 'Value': self.stats['solver_status']},
            {'Metric': 'Solve Time (sec)', 'Value': f"{self.stats['solve_time']:.2f}"},
            {'Metric': 'Objective Value', 'Value': self.stats['objective_value']},
        ]
        
        # Include custom constraint info if available
        if self._constraint_loader:
            loader_summary = self._constraint_loader.summary()
            summary_data.append({'Metric': 'Custom Constraints Loaded', 'Value': loader_summary['total_files']})
            summary_data.append({'Metric': 'Custom Constraints Applied', 'Value': loader_summary['applied']})
            summary_data.append({'Metric': 'Custom Constraints Skipped', 'Value': loader_summary['skipped']})
        
        summary_df = pd.DataFrame(summary_data)
        summary_path = output_folder / "scheduling_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        print(f"✓ {summary_path.name}")
        
        # 4. Program-specific folders with individual assignments
        print("\nCreating program-specific folders...")
        
        programs_folder = output_folder / "programs"
        programs_folder.mkdir(exist_ok=True)
        
        program_assignments = defaultdict(list)
        for sid, data in self.assignments.items():
            program = data['program']
            for course, section in data['courses'].items():
                program_assignments[program].append({
                    'Student ID': sid,
                    'Course': course,
                    'Section': section['section_code'],
                    'Days': section['days'],
                    'Start Time': section['start_time'],
                    'End Time': section['end_time']
                })
        
        for program in sorted(program_assignments.keys()):
            program_folder = programs_folder / program
            program_folder.mkdir(exist_ok=True)
            
            prog_df = pd.DataFrame(program_assignments[program])
            prog_df = prog_df.sort_values(['Student ID', 'Start Time'])
            
            prog_path = program_folder / "student_assignments.csv"
            prog_df.to_csv(prog_path, index=False)
        
        print(f"✓ Created {len(program_assignments)} program folders in programs/")
        
        # 5. Program summary
        program_summary = []
        for program in sorted(program_assignments.keys()):
            students_in_program = set()
            for assignment in program_assignments[program]:
                students_in_program.add(assignment['Student ID'])
            
            courses_per_student = len(program_assignments[program]) / len(students_in_program)
            
            program_summary.append({
                'Program': program,
                'Total Students': len(students_in_program),
                'Total Assignments': len(program_assignments[program]),
                'Courses per Student': f"{courses_per_student:.1f}"
            })
        
        program_summary_df = pd.DataFrame(program_summary)
        program_summary_path = output_folder / "program_summary.csv"
        program_summary_df.to_csv(program_summary_path, index=False)
        print(f"✓ {program_summary_path.name}")
        
        # 6. Section-program breakdown (demand allocation from input data)
        # Calculated directly from input numbers, NOT from solver assignments
        breakdown_rows = []
        
        # Get program sizes
        program_sizes = {}
        for _, row in self.cohorts_df.iterrows():
            program_sizes[row['Student Plan']] = int(row['Number of Expected New Students'])
        
        # Get math placement percentages per program
        math_cols = [c for c in self.cohorts_df.columns if c.startswith('Pct in Math')]
        program_math = {}
        for _, row in self.cohorts_df.iterrows():
            prog = row['Student Plan']
            program_math[prog] = {}
            for col in math_cols:
                pct = float(row[col])
                if pct > 0:
                    math_num = col.replace('Pct in Math', '')
                    course = f"MATH {math_num}"
                    program_math[prog][course] = pct
        
        # Get which programs need which courses (from requirements)
        course_programs = defaultdict(set)
        for _, row in self.requirements_df.iterrows():
            course = f"{row['Course Subject']} {row['Course Catalog Code']}"
            course_programs[course].add(row['Student Plan'])
        
        # For each course, calculate demand per program and distribute across sections
        math_courses = set()
        for prog_math in program_math.values():
            math_courses.update(prog_math.keys())
        
        for course, sections_list in self.sections.items():
            # Total capacity for this course
            total_cap = sum(s['capacity'] for s in sections_list)
            if total_cap == 0:
                continue
            
            # Calculate demand per program for this course
            program_demand = {}
            
            if course in math_courses:
                # Math course: use placement percentages
                for prog, math_pcts in program_math.items():
                    if course in math_pcts:
                        demand = int(round(program_sizes.get(prog, 0) * math_pcts[course]))
                        if demand > 0:
                            program_demand[prog] = demand
            else:
                # Core course: all students in that program
                for prog in course_programs.get(course, []):
                    demand = program_sizes.get(prog, 0)
                    if demand > 0:
                        program_demand[prog] = demand
            
            if not program_demand:
                continue
            
            total_demand = sum(program_demand.values())
            
            # Distribute across sections proportionally by capacity
            for section in sections_list:
                cap = section['capacity']
                cap_ratio = cap / total_cap
                
                section_total = 0
                section_programs = {}
                
                for prog, demand in sorted(program_demand.items()):
                    allocated = round(demand * cap_ratio)
                    if allocated > 0:
                        section_programs[prog] = allocated
                        section_total += allocated
                
                for prog, allocated in section_programs.items():
                    breakdown_rows.append({
                        'Course': course,
                        'Section': section['section_code'],
                        'Capacity': cap,
                        'Total Demand': total_demand,
                        'Allocated to Section': section_total,
                        'Program': prog,
                        'Program Demand': program_demand[prog],
                        'Students Blocked': allocated,
                    })
        
        breakdown_df = pd.DataFrame(breakdown_rows)
        breakdown_path = output_folder / "section_program_breakdown.csv"
        breakdown_df.to_csv(breakdown_path, index=False)
        print(f"✓ {breakdown_path.name}")
        
        print(f"\n✅ All results saved to: {output_folder}")
        
        print("\n📁 Output folder structure:")
        print(f"   {output_folder.name}/")
        print(f"   ├── student_assignments.csv")
        print(f"   ├── section_enrollment.csv")
        print(f"   ├── scheduling_summary.csv")
        print(f"   ├── program_summary.csv")
        print(f"   ├── section_program_breakdown.csv")
        print(f"   └── programs/")
        for i, program in enumerate(sorted(program_assignments.keys())[:5]):
            print(f"       ├── {program}/")
            print(f"       │   └── student_assignments.csv")
        if len(program_assignments) > 5:
            print(f"       └── ... ({len(program_assignments) - 5} more programs)")
    
    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("SCHEDULING SUMMARY")
        print("=" * 60)
        
        total = self.stats['total_students']
        fully = self.stats['fully_scheduled']
        
        print(f"\nStudents:")
        print(f"  - Total: {total}")
        print(f"  - Fully Scheduled: {fully} ({fully/total*100:.1f}%)")
        print(f"  - Partially Scheduled: {self.stats['partially_scheduled']}")
        
        print(f"\nSolver:")
        print(f"  - Status: {self.stats['solver_status']}")
        print(f"  - Solve Time: {self.stats['solve_time']:.2f} seconds")
        print(f"  - Objective Value: {self.stats['objective_value']:.0f}")
        
        # Custom constraints summary
        if self._constraint_loader:
            loader_summary = self._constraint_loader.summary()
            if loader_summary['total_files'] > 0:
                print(f"\nCustom Constraints:")
                print(f"  - Loaded: {loader_summary['total_files']}")
                print(f"  - Applied: {loader_summary['applied']}")
                print(f"  - Skipped: {loader_summary['skipped']}")
        
        if self.stats['fully_scheduled'] == total:
            print("\n✅ SUCCESS: All students fully scheduled!")
        else:
            print(f"\n⚠️ WARNING: {self.stats['partially_scheduled']} students not fully scheduled")
    
    def run(self) -> bool:
        print("\n" + "#" * 60)
        print("# CONSTRAINT-BASED SCHEDULER")
        print("#" * 60)
        
        if not self.load_data():
            return False
        
        self._parse_sections()
        self._generate_students()
        self._build_model()
        
        if not self.solve():
            return False
        
        self.export_results()
        self.print_summary()
        
        return self.stats['partially_scheduled'] == 0


def main():
    random.seed(42)
    
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    
    sections_path = data_dir / 'course_sections.csv'
    cohorts_path = data_dir / 'program_cohort_distribution.csv'
    requirements_path = data_dir / 'program_course_requirements.csv'
    
    scheduler = ConstraintScheduler(sections_path, cohorts_path, requirements_path)
    success = scheduler.run()
    
    import sys
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()