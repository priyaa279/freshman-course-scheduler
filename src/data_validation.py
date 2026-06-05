"""
Step 1: Data Validation for Freshman Course Scheduling (FINAL)
==============================================================
Comprehensive validation script that checks all aspects of input data
before attempting to run the scheduler.

VALIDATION CHECKS:
1. File Structure    - Required columns, data types, null values
2. Data Integrity    - Duplicates, valid values (Y/N for days, positive capacity)
3. Math Percentages  - Sum to 1.0 for programs with math requirements
4. Course Existence  - Required courses have sections available
5. Feasibility       - Total capacity >= total demand for each course
6. N-Way Conflicts   - All block courses can be scheduled together
7. Effective Capacity - Enough capacity in valid section combinations

Input Files:
- course_sections.csv: Available sections with capacity and timings
- program_cohort_distribution.csv: Student counts and math placement %
- program_course_requirements.csv: Required courses per program

Output:
- Console summary (or verbose detailed output with -v flag)
- Audit CSV files in timestamped folder

Usage:
  python data_validation.py              # Summary mode (default)
  python data_validation.py -v           # Verbose mode
  python data_validation.py --verbose    # Verbose mode (long form)
"""

import pandas as pd
import sys
from pathlib import Path
from datetime import datetime
import argparse
from collections import defaultdict


class DataValidator:
    """Comprehensive validator for freshman scheduling input data."""
    
    def __init__(self, sections_path: str, cohorts_path: str, requirements_path: str, 
                 output_dir: str = None, verbose: bool = False):
        """Initialize with paths to the three input CSV files."""
        self.sections_path = Path(sections_path)
        self.cohorts_path = Path(cohorts_path)
        self.requirements_path = Path(requirements_path)
        self.output_dir = Path(output_dir) if output_dir else self.sections_path.parent.parent / "audit"
        self.verbose = verbose
        
        # DataFrames
        self.sections = None
        self.cohorts = None
        self.requirements = None
        
        # Issues tracking
        self.errors = []
        self.warnings = []
        
        # Statistics
        self.stats = {
            'sections_count': 0,
            'courses_count': 0,
            'total_capacity': 0,
            'total_demand': 0,
            'programs_count': 0,
            'students_count': 0,
            'requirements_count': 0,
            'feasibility_issues': 0,
            'programs_with_conflicts': 0,
            'programs_no_conflicts': 0,
            'impossible_programs': 0,
            'capacity_issues': 0,
            'math_pct_issues': 0,
        }
        
        # Audit data for CSV export
        self.audit_data = {
            'feasibility_report': [],
            'nway_conflict_report': [],
            'effective_capacity_report': [],
            'demand_by_program': [],
            'section_utilization': [],
        }
        
        # Helper data structures
        self.day_cols = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        self.section_data = {}  # course -> list of section rows
        self.demand = {}  # course -> total demand
        
    # =========================================================================
    # DATA LOADING
    # =========================================================================
    
    def load_data(self) -> bool:
        """Load all CSV files. Returns True if successful."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("LOADING DATA FILES")
            print("=" * 60)
        
        # Load sections
        try:
            self.sections = pd.read_csv(self.sections_path)
            self.stats['sections_count'] = len(self.sections)
            if self.verbose:
                print(f"✓ Loaded {self.sections_path.name}: {len(self.sections)} rows")
        except Exception as e:
            self.errors.append(f"Failed to load {self.sections_path.name}: {e}")
            return False
        
        # Load cohorts
        try:
            self.cohorts = pd.read_csv(self.cohorts_path)
            self.stats['programs_count'] = len(self.cohorts)
            self.stats['students_count'] = int(self.cohorts['Number of Expected New Students'].sum())
            if self.verbose:
                print(f"✓ Loaded {self.cohorts_path.name}: {len(self.cohorts)} rows")
        except Exception as e:
            self.errors.append(f"Failed to load {self.cohorts_path.name}: {e}")
            return False
        
        # Load requirements
        try:
            self.requirements = pd.read_csv(self.requirements_path)
            self.stats['requirements_count'] = len(self.requirements)
            if self.verbose:
                print(f"✓ Loaded {self.requirements_path.name}: {len(self.requirements)} rows")
        except Exception as e:
            self.errors.append(f"Failed to load {self.requirements_path.name}: {e}")
            return False
        
        # Preprocess sections for quick lookup
        self._preprocess_sections()
        
        return True
    
    def _preprocess_sections(self) -> None:
        """Create helper columns and data structures."""
        # Create combined course column
        self.sections['Course'] = (
            self.sections['Course Subject'] + ' ' + 
            self.sections['Course Catalog Code'].astype(str)
        )
        
        # Parse times
        self.sections['Start'] = pd.to_datetime(self.sections['Start Time'], format='%H:%M')
        self.sections['End'] = pd.to_datetime(self.sections['End Time'], format='%H:%M')
        
        # Create days string (e.g., "MWF", "TT")
        self.sections['Days'] = self.sections[self.day_cols].apply(
            lambda row: ''.join([d[0] if row[d] == 'Y' else '' for d in self.day_cols]),
            axis=1
        )
        
        # Build section lookup by course
        for _, row in self.sections.iterrows():
            course = row['Course']
            if course not in self.section_data:
                self.section_data[course] = []
            self.section_data[course].append(row)
        
        self.stats['courses_count'] = len(self.section_data)
        self.stats['total_capacity'] = int(self.sections['Enrollment Capacity'].sum())
    
    # =========================================================================
    # VALIDATION: FILE STRUCTURE & DATA INTEGRITY
    # =========================================================================
    
    def validate_sections(self) -> None:
        """Validate course_sections.csv structure and data."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("VALIDATING: course_sections.csv")
            print("=" * 60)
        
        # Check required columns
        required_cols = [
            'Course Subject', 'Course Catalog Code', 'Class Section Code',
            'Enrollment Capacity', 'Start Time', 'End Time',
            'Mon', 'Tue', 'Wed', 'Thu', 'Fri'
        ]
        missing_cols = [col for col in required_cols if col not in self.sections.columns]
        if missing_cols:
            self.errors.append(f"Sections file missing columns: {missing_cols}")
        elif self.verbose:
            print("✓ All required columns present")
        
        # Check for null values in critical columns
        critical_cols = ['Course Subject', 'Course Catalog Code', 'Enrollment Capacity', 'Start Time', 'End Time']
        for col in critical_cols:
            if col in self.sections.columns:
                null_count = self.sections[col].isnull().sum()
                if null_count > 0:
                    self.errors.append(f"Sections: {null_count} null values in '{col}'")
        
        # Check capacity is positive
        if 'Enrollment Capacity' in self.sections.columns:
            invalid = self.sections[self.sections['Enrollment Capacity'] <= 0]
            if len(invalid) > 0:
                self.errors.append(f"Sections: {len(invalid)} sections with invalid capacity (<=0)")
            elif self.verbose:
                print("✓ All sections have valid capacity (> 0)")
        
        # Check time format
        try:
            pd.to_datetime(self.sections['Start Time'], format='%H:%M')
            pd.to_datetime(self.sections['End Time'], format='%H:%M')
            if self.verbose:
                print("✓ Time format is valid (HH:MM)")
        except:
            self.warnings.append("Some time values may have invalid format (expected HH:MM)")
        
        # Check day columns have valid values (Y/N)
        for col in self.day_cols:
            if col in self.sections.columns:
                invalid = self.sections[~self.sections[col].isin(['Y', 'N'])]
                if len(invalid) > 0:
                    self.warnings.append(f"Column '{col}' has {len(invalid)} values other than Y/N")
        
        # Check for duplicate sections
        dup_cols = ['Course Subject', 'Course Catalog Code', 'Class Section Code']
        if all(col in self.sections.columns for col in dup_cols):
            duplicates = self.sections.duplicated(subset=dup_cols, keep=False)
            if duplicates.any():
                dup_count = duplicates.sum() // 2  # Each duplicate counted twice
                self.errors.append(f"Sections: {dup_count} duplicate section entries")
            elif self.verbose:
                print("✓ No duplicate sections found")
        
        if self.verbose:
            print(f"\nSummary:")
            print(f"  • Unique courses: {self.stats['courses_count']}")
            print(f"  • Total sections: {self.stats['sections_count']}")
            print(f"  • Total capacity: {self.stats['total_capacity']:,} seats")
    
    def validate_cohorts(self) -> None:
        """Validate program_cohort_distribution.csv structure and data."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("VALIDATING: program_cohort_distribution.csv")
            print("=" * 60)
        
        # Check required columns
        required_cols = ['Student Plan', 'Number of Expected New Students']
        missing_cols = [col for col in required_cols if col not in self.cohorts.columns]
        if missing_cols:
            self.errors.append(f"Cohorts file missing columns: {missing_cols}")
        elif self.verbose:
            print("✓ Required columns present")
        
        # Check student counts are positive
        if 'Number of Expected New Students' in self.cohorts.columns:
            invalid = self.cohorts[self.cohorts['Number of Expected New Students'] <= 0]
            if len(invalid) > 0:
                self.errors.append(f"Cohorts: {len(invalid)} programs with invalid student count (<=0)")
            elif self.verbose:
                print("✓ All programs have valid student counts")
        
        # Check math percentages sum to 1.0 for programs with math requirements
        self._validate_math_percentages()
        
        if self.verbose:
            print(f"\nSummary:")
            print(f"  • Programs: {self.stats['programs_count']}")
            print(f"  • Total students: {self.stats['students_count']:,}")
    
    def _validate_math_percentages(self) -> None:
        """Check that math placement percentages sum to 1.0 for programs requiring math."""
        pct_cols = [col for col in self.cohorts.columns if col.startswith('Pct in Math')]
        
        if not pct_cols:
            if self.verbose:
                print("ℹ No math placement columns found")
            return
        
        # Get programs that have math requirements
        self.requirements['Course'] = (
            self.requirements['Course Subject'] + ' ' + 
            self.requirements['Course Catalog Code'].astype(str)
        )
        math_reqs = self.requirements[self.requirements['Course Subject'] == 'MATH']
        programs_with_math = set(math_reqs['Student Plan'].unique())
        
        math_issues = []
        
        for _, row in self.cohorts.iterrows():
            program = row['Student Plan']
            pct_sum = sum(row[col] for col in pct_cols if pd.notna(row[col]))
            
            if program in programs_with_math:
                # Program requires math - percentages should sum to 1.0
                if abs(pct_sum - 1.0) > 0.01:
                    math_issues.append((program, pct_sum))
                    self.warnings.append(
                        f"Program '{program}': Math percentages sum to {pct_sum:.2f}, not 1.0"
                    )
            else:
                # Program doesn't require math - 0.0 is expected
                if pct_sum > 0.01:
                    self.warnings.append(
                        f"Program '{program}': Has math percentages ({pct_sum:.2f}) but no math requirement"
                    )
        
        self.stats['math_pct_issues'] = len(math_issues)
        
        if self.verbose:
            if not math_issues:
                print(f"✓ Math percentages valid for all {len(programs_with_math)} programs with math requirements")
            else:
                print(f"⚠ {len(math_issues)} programs have invalid math percentage sums")
    
    def validate_requirements(self) -> None:
        """Validate program_course_requirements.csv structure and data."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("VALIDATING: program_course_requirements.csv")
            print("=" * 60)
        
        # Check required columns
        required_cols = ['Student Plan', 'Course Subject', 'Course Catalog Code', 'Priority Type']
        missing_cols = [col for col in required_cols if col not in self.requirements.columns]
        if missing_cols:
            self.errors.append(f"Requirements file missing columns: {missing_cols}")
        elif self.verbose:
            print("✓ All required columns present")
        
        # Check Priority Type values
        valid_priorities = ['Block for Required Core', 'Needs Scheduling']
        if 'Priority Type' in self.requirements.columns:
            invalid = self.requirements[~self.requirements['Priority Type'].isin(valid_priorities)]
            if len(invalid) > 0:
                self.warnings.append(f"Requirements: {len(invalid)} rows with unexpected Priority Type")
            elif self.verbose:
                print("✓ All Priority Type values are valid")
        
        # Check that required courses exist in sections
        required_courses = set(self.requirements['Course'].unique())
        available_courses = set(self.section_data.keys())
        
        # Calculate demand to see which missing courses matter
        self._calculate_demand()
        
        missing_courses = required_courses - available_courses
        missing_with_demand = {c for c in missing_courses if self.demand.get(c, 0) > 0}
        
        if missing_with_demand:
            self.errors.append(f"Required courses with no sections: {missing_with_demand}")
        elif self.verbose:
            print("✓ All required courses with demand have sections available")
        
        if self.verbose:
            print(f"\nSummary:")
            print(f"  • Total requirements: {self.stats['requirements_count']}")
            print(f"  • Unique courses required: {len(required_courses)}")
    
    # =========================================================================
    # DEMAND CALCULATION
    # =========================================================================
    
    def _calculate_demand(self) -> None:
        """Calculate demand for each course based on cohorts and requirements."""
        self.demand = {}
        demand_details = []
        
        for _, cohort in self.cohorts.iterrows():
            program = cohort['Student Plan']
            num_students = int(cohort['Number of Expected New Students'])
            
            prog_reqs = self.requirements[self.requirements['Student Plan'] == program]
            
            for _, req in prog_reqs.iterrows():
                course = req['Course']
                priority = req['Priority Type']
                
                if priority == 'Block for Required Core':
                    # All students in this program take this course
                    self.demand[course] = self.demand.get(course, 0) + num_students
                    demand_details.append({
                        'Program': program,
                        'Course': course,
                        'Type': 'Block',
                        'Students': num_students,
                        'Percentage': '100%',
                        'Demand': num_students
                    })
                else:
                    # Math courses based on placement percentages
                    parts = course.split()
                    if len(parts) == 2 and parts[0] == 'MATH':
                        col_name = f"Pct in Math{parts[1]}"
                        if col_name in cohort.index and pd.notna(cohort[col_name]):
                            pct = cohort[col_name]
                            course_demand = int(num_students * pct)
                            if course_demand > 0:
                                self.demand[course] = self.demand.get(course, 0) + course_demand
                                demand_details.append({
                                    'Program': program,
                                    'Course': course,
                                    'Type': 'Math Placement',
                                    'Students': num_students,
                                    'Percentage': f"{pct:.0%}",
                                    'Demand': course_demand
                                })
        
        self.audit_data['demand_by_program'] = demand_details
        self.stats['total_demand'] = sum(self.demand.values())
    
    # =========================================================================
    # FEASIBILITY CHECK
    # =========================================================================
    
    def check_feasibility(self) -> None:
        """Check if total capacity >= total demand for each course."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("FEASIBILITY CHECK: Demand vs Capacity")
            print("=" * 60)
        
        # Get capacity by course
        capacity = self.sections.groupby('Course')['Enrollment Capacity'].sum().to_dict()
        num_sections = self.sections.groupby('Course').size().to_dict()
        
        feasibility_issues = []
        feasibility_report = []
        
        if self.verbose:
            print(f"\n{'Course':<15} {'Sections':>8} {'Capacity':>10} {'Demand':>10} {'Status':<15}")
            print("-" * 60)
        
        for course in sorted(set(self.demand.keys()) | set(capacity.keys())):
            course_demand = self.demand.get(course, 0)
            course_capacity = capacity.get(course, 0)
            course_sections = num_sections.get(course, 0)
            gap = max(0, course_demand - course_capacity)
            
            # Determine status
            if course_demand == 0:
                status = 'No demand'
            elif course_capacity == 0:
                status = 'NO SECTIONS'
                feasibility_issues.append((course, course_demand, 0))
            elif gap > 0:
                status = f'SHORT BY {gap}'
                feasibility_issues.append((course, course_demand, course_capacity))
            else:
                status = 'OK'
            
            # Calculate utilization
            util = (course_demand / course_capacity * 100) if course_capacity > 0 else 0
            
            if self.verbose and course_demand > 0:
                print(f"{course:<15} {course_sections:>8} {course_capacity:>10,} {course_demand:>10,} {status:<15}")
            
            # Store for audit
            if course_demand > 0 or course_capacity > 0:
                feasibility_report.append({
                    'Course': course,
                    'Sections': course_sections,
                    'Total Capacity': course_capacity,
                    'Total Demand': course_demand,
                    'Gap': gap,
                    'Utilization %': f"{util:.1f}%",
                    'Status': status,
                    'Has Error': 'YES' if gap > 0 else 'NO'
                })
        
        self.audit_data['feasibility_report'] = feasibility_report
        self.stats['feasibility_issues'] = len(feasibility_issues)
        
        if feasibility_issues:
            # Add specific error for each course with shortage
            for course, demand, capacity in feasibility_issues:
                gap = demand - capacity
                self.errors.append(f"CAPACITY SHORTAGE: {course} has {capacity} seats but {demand} students need it. Add {gap} more seats.")
            if self.verbose:
                print(f"\n⚠ {len(feasibility_issues)} courses have insufficient capacity")
        elif self.verbose:
            print("\n✓ All courses have sufficient total capacity")
    
    # =========================================================================
    # N-WAY CONFLICT CHECK
    # =========================================================================
    
    def _check_conflict(self, s1, s2) -> bool:
        """Check if two sections have a time conflict."""
        # Check if days overlap
        days_overlap = any(s1[d] == 'Y' and s2[d] == 'Y' for d in self.day_cols)
        if not days_overlap:
            return False
        
        # Check if times overlap
        return not (s1['End'] <= s2['Start'] or s2['End'] <= s1['Start'])
    
    def check_nway_conflicts(self) -> None:
        """Check that ALL block courses for each program can be scheduled together."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("N-WAY CONFLICT CHECK")
            print("=" * 60)
            print("Checking if all block courses can be scheduled together...")
        
        nway_report = []
        impossible_programs = []
        programs_with_conflicts = 0
        programs_no_conflicts = 0
        
        for _, cohort in self.cohorts.iterrows():
            program = cohort['Student Plan']
            num_students = int(cohort['Number of Expected New Students'])
            
            # Get block courses for this program
            prog_reqs = self.requirements[self.requirements['Student Plan'] == program]
            block_courses = [
                f"{req['Course Subject']} {req['Course Catalog Code']}"
                for _, req in prog_reqs.iterrows()
                if req['Priority Type'] == 'Block for Required Core'
            ]
            
            if len(block_courses) < 2:
                # Can't have conflicts with 0 or 1 course
                programs_no_conflicts += 1
                continue
            
            # Check for missing courses
            missing = [c for c in block_courses if c not in self.section_data]
            if missing:
                nway_report.append({
                    'Program': program,
                    'Students': num_students,
                    'Block Courses': len(block_courses),
                    'Valid Combinations': 0,
                    'Status': 'MISSING SECTIONS',
                    'Has Error': 'YES',
                    'Details': f"Missing: {', '.join(missing)}"
                })
                impossible_programs.append(program)
                continue
            
            # Find valid combinations
            valid_combos = self._find_valid_combinations(block_courses, max_combos=100)
            
            if len(valid_combos) == 0:
                nway_report.append({
                    'Program': program,
                    'Students': num_students,
                    'Block Courses': len(block_courses),
                    'Valid Combinations': 0,
                    'Status': 'IMPOSSIBLE',
                    'Has Error': 'YES',
                    'Details': f"No valid schedule for {len(block_courses)} courses"
                })
                impossible_programs.append(program)
                
                if self.verbose:
                    print(f"\n❌ {program}: IMPOSSIBLE - No valid schedule!")
                    self._explain_conflict(block_courses)
            else:
                has_partial = self._has_partial_conflicts(block_courses)
                if has_partial:
                    programs_with_conflicts += 1
                else:
                    programs_no_conflicts += 1
                
                nway_report.append({
                    'Program': program,
                    'Students': num_students,
                    'Block Courses': len(block_courses),
                    'Valid Combinations': len(valid_combos) if len(valid_combos) < 100 else '100+',
                    'Status': 'OK',
                    'Has Error': 'NO',
                    'Details': ''
                })
        
        self.audit_data['nway_conflict_report'] = nway_report
        self.stats['impossible_programs'] = len(impossible_programs)
        self.stats['programs_with_conflicts'] = programs_with_conflicts
        self.stats['programs_no_conflicts'] = programs_no_conflicts
        
        for program in impossible_programs:
            self.errors.append(f"IMPOSSIBLE SCHEDULE: {program} block courses all conflict with each other. No valid schedule exists. Add sections at different times.")
        
        if self.verbose:
            if not impossible_programs:
                print(f"\n✓ All programs have valid schedule combinations")
            print(f"  • {programs_no_conflicts} programs with no conflicts")
            print(f"  • {programs_with_conflicts} programs with partial conflicts (but schedulable)")
            print(f"  • {len(impossible_programs)} programs IMPOSSIBLE to schedule")
    
    def _find_valid_combinations(self, courses: list, max_combos: int = 100) -> list:
        """Find valid section combinations for a list of courses."""
        valid_combos = []
        
        def search(course_idx: int, assigned: list, combo: dict):
            if len(valid_combos) >= max_combos:
                return
            if course_idx >= len(courses):
                valid_combos.append(combo.copy())
                return
            
            course = courses[course_idx]
            for section in self.section_data.get(course, []):
                if not any(self._check_conflict(section, a) for a in assigned):
                    combo[course] = section['Class Section Code']
                    search(course_idx + 1, assigned + [section], combo)
        
        search(0, [], {})
        return valid_combos
    
    def _has_partial_conflicts(self, courses: list) -> bool:
        """Check if any pair of courses has some conflicting sections."""
        for i, c1 in enumerate(courses):
            for c2 in courses[i+1:]:
                secs1 = self.section_data.get(c1, [])
                secs2 = self.section_data.get(c2, [])
                for s1 in secs1:
                    for s2 in secs2:
                        if self._check_conflict(s1, s2):
                            return True
        return False
    
    def _explain_conflict(self, courses: list) -> None:
        """Print details about why courses conflict."""
        print(f"   Courses: {courses}")
        for course in courses:
            sections = self.section_data.get(course, [])
            print(f"   {course}: {len(sections)} section(s)")
            for sec in sections[:3]:  # Show max 3
                print(f"      {sec['Days']} {sec['Start Time']}-{sec['End Time']}")
            if len(sections) > 3:
                print(f"      ... and {len(sections) - 3} more")
    
    # =========================================================================
    # EFFECTIVE CAPACITY CHECK
    # =========================================================================
    
    def check_effective_capacity(self) -> None:
        """Check that effective capacity (in valid combinations) >= students needed."""
        if self.verbose:
            print("\n" + "=" * 60)
            print("EFFECTIVE CAPACITY CHECK")
            print("=" * 60)
            print("Checking if valid combinations have enough total capacity...")
        
        capacity_report = []
        capacity_issues = []
        
        # Get total capacity per course (for bottleneck calculation)
        course_total_capacity = self.sections.groupby('Course')['Enrollment Capacity'].sum().to_dict()
        
        for _, cohort in self.cohorts.iterrows():
            program = cohort['Student Plan']
            num_students = int(cohort['Number of Expected New Students'])
            
            # Get block courses
            prog_reqs = self.requirements[self.requirements['Student Plan'] == program]
            block_courses = [
                f"{req['Course Subject']} {req['Course Catalog Code']}"
                for _, req in prog_reqs.iterrows()
                if req['Priority Type'] == 'Block for Required Core'
            ]
            
            if len(block_courses) < 2:
                continue
            
            # Skip if missing courses
            if any(c not in self.section_data for c in block_courses):
                continue
            
            # Find valid combos and their capacities
            combo_capacities = self._find_combo_capacities(block_courses)
            
            if combo_capacities:
                # Sum of combo capacities
                sum_combo_caps = sum(combo_capacities)
                
                # Bottleneck = smallest total capacity among all block courses
                bottleneck_cap = min(course_total_capacity.get(c, 0) for c in block_courses)
                
                # Effective capacity cannot exceed the bottleneck
                effective_cap = min(sum_combo_caps, bottleneck_cap)
                
                capacity_report.append({
                    'Program': program,
                    'Students': num_students,
                    'Block Courses': len(block_courses),
                    'Valid Combinations': len(combo_capacities),
                    'Effective Capacity': effective_cap,
                    'Bottleneck Capacity': bottleneck_cap,
                    'Surplus/Deficit': effective_cap - num_students,
                    'Status': 'OK' if effective_cap >= num_students else 'INSUFFICIENT',
                    'Has Error': 'YES' if effective_cap < num_students else 'NO'
                })
                
                if effective_cap < num_students:
                    capacity_issues.append((program, num_students, effective_cap))
                    if self.verbose:
                        print(f"❌ {program}: Need {num_students} but only {effective_cap} effective capacity")
        
        self.audit_data['effective_capacity_report'] = capacity_report
        self.stats['capacity_issues'] = len(capacity_issues)
        
        for program, students, cap in capacity_issues:
            self.errors.append(f"SCHEDULING BOTTLENECK: {program} has {students} students but only {cap} can be scheduled due to limited seats/time conflicts. Add more sections.")
        
        if self.verbose:
            if not capacity_issues:
                print(f"\n✓ All programs have sufficient effective capacity")
            else:
                print(f"\n⚠ {len(capacity_issues)} programs have insufficient effective capacity")
    
    def _find_combo_capacities(self, courses: list) -> list:
        """Find all valid combinations and return their effective capacities."""
        capacities = []
        
        def search(course_idx: int, assigned: list, caps: list):
            if course_idx >= len(courses):
                # Effective capacity of combo = minimum section capacity
                capacities.append(min(caps))
                return
            
            course = courses[course_idx]
            for section in self.section_data.get(course, []):
                if not any(self._check_conflict(section, a) for a in assigned):
                    search(course_idx + 1, assigned + [section], 
                           caps + [section['Enrollment Capacity']])
        
        search(0, [], [])
        return capacities
    
    # =========================================================================
    # EXPORT & SUMMARY
    # =========================================================================
    
    def export_audit_csvs(self) -> None:
        """Export all audit data to CSV files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit_folder = self.output_dir / timestamp
        audit_folder.mkdir(parents=True, exist_ok=True)
        
        if self.verbose:
            print("\n" + "=" * 60)
            print("EXPORTING AUDIT FILES")
            print("=" * 60)
        
        self.exported_files = {}
        
        # Validation summary
        summary_data = []
        for error in self.errors:
            summary_data.append({'Type': 'ERROR', 'Message': error})
        for warning in self.warnings:
            summary_data.append({'Type': 'WARNING', 'Message': warning})
        if not self.errors and not self.warnings:
            summary_data.append({'Type': 'INFO', 'Message': 'All validations passed'})
        
        self._export_csv(audit_folder, 'validation_summary', summary_data)
        
        # Other reports
        reports = [
            ('feasibility_report', self.audit_data['feasibility_report']),
            ('nway_conflict_report', self.audit_data['nway_conflict_report']),
            ('effective_capacity_report', self.audit_data['effective_capacity_report']),
            ('demand_by_program', self.audit_data['demand_by_program']),
        ]
        
        for name, data in reports:
            if data:
                self._export_csv(audit_folder, name, data)
        
        self.audit_folder = audit_folder
        
        if self.verbose:
            print(f"\nAll files saved to: {audit_folder}")
    
    def _export_csv(self, folder: Path, name: str, data: list) -> None:
        """Export a single CSV file."""
        df = pd.DataFrame(data)
        path = folder / f"{name}.csv"
        df.to_csv(path, index=False)
        self.exported_files[name] = path
        if self.verbose:
            print(f"✓ Exported: {name}.csv ({len(data)} rows)")
    
    def print_summary(self) -> bool:
        """Print final validation summary. Returns True if no errors."""
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        
        # Data overview
        print(f"\n📊 Data Overview:")
        print(f"   • Sections: {self.stats['sections_count']:,} ({self.stats['courses_count']} unique courses)")
        print(f"   • Programs: {self.stats['programs_count']}")
        print(f"   • Students: {self.stats['students_count']:,}")
        print(f"   • Total Capacity: {self.stats['total_capacity']:,} seats")
        print(f"   • Total Demand: {self.stats['total_demand']:,} enrollments")
        if self.stats['total_capacity'] > 0:
            util = self.stats['total_demand'] / self.stats['total_capacity'] * 100
            print(f"   • Overall Utilization: {util:.1f}%")
        
        # Validation results
        print(f"\n📋 Validation Results:")
        
        # Feasibility
        if self.stats['feasibility_issues'] == 0:
            print(f"   ✓ Feasibility: All courses have sufficient capacity")
        else:
            print(f"   ✗ Feasibility: {self.stats['feasibility_issues']} course(s) with capacity shortage")
        
        # N-Way conflicts
        if self.stats['impossible_programs'] == 0:
            print(f"   ✓ N-Way Conflicts: All programs can schedule all courses")
            print(f"      ({self.stats['programs_with_conflicts']} with partial conflicts, "
                  f"{self.stats['programs_no_conflicts']} with none)")
        else:
            print(f"   ✗ N-Way Conflicts: {self.stats['impossible_programs']} program(s) IMPOSSIBLE!")
        
        # Effective capacity
        if self.stats['capacity_issues'] == 0:
            print(f"   ✓ Effective Capacity: All programs have sufficient capacity")
        else:
            print(f"   ✗ Effective Capacity: {self.stats['capacity_issues']} program(s) insufficient")
        
        # Math percentages
        if self.stats['math_pct_issues'] > 0:
            print(f"   ⚠ Math Percentages: {self.stats['math_pct_issues']} program(s) don't sum to 1.0")
        
        # Errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"   • {error}")
        else:
            print(f"\n✓ No errors found")
        
        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   • {warning}")
        else:
            print(f"✓ No warnings")
        
        # Audit folder
        if hasattr(self, 'audit_folder'):
            print(f"\n📁 Detailed reports saved to: {self.audit_folder}")
        
        # Final status
        if not self.errors:
            print("\n" + "=" * 60)
            print("✅ DATA VALIDATION PASSED - Ready for scheduling")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ DATA VALIDATION FAILED - Please fix errors before proceeding")
            print("=" * 60)
        
        return len(self.errors) == 0
    
    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================
    
    def run_all_validations(self) -> bool:
        """Run all validation checks and return True if passed."""
        print("\n" + "#" * 60)
        print("# FRESHMAN SCHEDULING - DATA VALIDATION")
        print("#" * 60)
        
        if not self.load_data():
            self.print_summary()
            return False
        
        # Run all validations
        self.validate_sections()
        self.validate_cohorts()
        self.validate_requirements()
        self.check_feasibility()
        self.check_nway_conflicts()
        self.check_effective_capacity()
        
        # Export results
        self.export_audit_csvs()
        
        return self.print_summary()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validate input data for freshman course scheduling',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python data_validation.py              # Summary mode
  python data_validation.py -v           # Verbose mode
  python data_validation.py --verbose    # Verbose mode (long form)
        """
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed validation output'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Optional: paths to sections, cohorts, requirements CSV files'
    )
    
    args = parser.parse_args()
    
    # Default file paths
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    
    sections_path = data_dir / 'course_sections.csv'
    cohorts_path = data_dir / 'program_cohort_distribution.csv'
    requirements_path = data_dir / 'program_course_requirements.csv'
    
    # Allow command line overrides
    if len(args.files) >= 3:
        sections_path, cohorts_path, requirements_path = [Path(f) for f in args.files[:3]]
    
    # Run validation
    validator = DataValidator(
        sections_path,
        cohorts_path,
        requirements_path,
        verbose=args.verbose
    )
    success = validator.run_all_validations()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()