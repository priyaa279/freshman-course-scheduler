"""
Interactive LLM Interface for Constraint Generation & Data Editing
===================================================================
Allows administrators to:
  - Add, manage, and test constraints in natural language
  - Edit input data (section capacities, cohort sizes)

Constraint Commands:
  (type a constraint)  - Generate constraint code from natural language
  list                 - Show all saved constraints
  delete <number>      - Delete a saved constraint
  clear                - Delete all saved constraints

Data Commands:
  show <course>        - Show sections for a course (e.g. show MATH 181)
  show <program>       - Show cohort info (e.g. show MECE-BS)
  show programs        - Show all programs and student counts
  capacity <course> <section> <+/-amount>  - Adjust section capacity
  capacity <course> all <+/-amount>        - Adjust all sections of a course
  addsection <course> <cap> <start> <end> <days>  - Add a new section
  students <program> <+/-amount>           - Adjust cohort size
  undo                 - Undo last data change

General:
  run                  - Run the scheduler with current constraints
  help                 - Show commands
  quit                 - Exit
"""

from pathlib import Path
import shutil
from llm_constraint_generator import LLMConstraintGenerator
from data_editor import DataEditor
import pandas as pd


def load_context_from_data():
    """Load available programs and courses from data files."""
    data_dir = Path(__file__).parent.parent / "data"

    cohorts = pd.read_csv(data_dir / "program_cohort_distribution.csv")
    programs = cohorts['Student Plan'].tolist()

    sections = pd.read_csv(data_dir / "course_sections.csv")
    sections['Course'] = sections['Course Subject'] + ' ' + sections['Course Catalog Code'].astype(str)
    courses = sections['Course'].unique().tolist()

    return {'programs': programs, 'courses': courses}


def get_constraints_dir() -> Path:
    """Get the generated constraints directory."""
    return Path(__file__).parent.parent / "output" / "generated_constraints"


def list_constraints():
    """List all saved constraint files."""
    constraints_dir = get_constraints_dir()

    if not constraints_dir.exists():
        print("\n  No constraints directory found.")
        return []

    files = sorted(f for f in constraints_dir.glob("*.py") if f.name != "__init__.py")

    if not files:
        print("\n  No saved constraints.")
        return []

    print(f"\n  SAVED CONSTRAINTS ({len(files)})")
    print(f"  {'-'*55}")

    for i, filepath in enumerate(files, 1):
        # Extract description from file
        description = ""
        try:
            for line in filepath.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("Description:"):
                    description = stripped[len("Description:"):].strip()
                    break
        except Exception:
            pass

        label = description or filepath.stem
        print(f"  {i}. {label}")
        print(f"     File: {filepath.name}")

    print()
    return files


def delete_constraint(files, number):
    """Delete a constraint by its list number."""
    if not files:
        print("  No constraints to delete. Use 'list' first.")
        return

    try:
        idx = int(number) - 1
    except ValueError:
        print(f"  Invalid number: {number}")
        return

    if idx < 0 or idx >= len(files):
        print(f"  Invalid number. Choose 1-{len(files)}")
        return

    filepath = files[idx]
    name = filepath.name
    filepath.unlink()
    print(f"  Deleted: {name}")


def clear_all_constraints():
    """Delete all saved constraint files."""
    constraints_dir = get_constraints_dir()

    if not constraints_dir.exists():
        print("  No constraints to clear.")
        return

    files = list(f for f in constraints_dir.glob("*.py") if f.name != "__init__.py")

    if not files:
        print("  No constraints to clear.")
        return

    confirm = input(f"  Delete all {len(files)} constraint(s)? (y/n): ").strip().lower()
    if confirm == 'y':
        for f in files:
            f.unlink()
        print(f"  Cleared {len(files)} constraint(s).")
    else:
        print("  Cancelled.")


def run_scheduler():
    """Validate input data, then run the constraint scheduler."""
    import random
    from constraint_scheduler import ConstraintScheduler
    from data_validation import DataValidator

    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"

    sections_path = data_dir / "course_sections.csv"
    cohorts_path = data_dir / "program_cohort_distribution.csv"
    requirements_path = data_dir / "program_course_requirements.csv"

    # ---- Step 1: Validate ----
    print("\n" + "=" * 60)
    print("STEP 1: DATA VALIDATION")
    print("=" * 60)

    validator = DataValidator(sections_path, cohorts_path, requirements_path, verbose=False)

    if not validator.load_data():
        print("\n  ✗ Failed to load data for validation.")
        return

    validator.validate_sections()
    validator.validate_cohorts()
    validator.validate_requirements()
    validator.check_feasibility()
    validator.check_nway_conflicts()
    validator.check_effective_capacity()

    validation_passed = validator.print_summary()

    if not validation_passed:
        print("\n  ⛔ Validation failed. Fix errors before scheduling.")
        print("  Use 'undo' or 'reset' to revert data changes, or fix the issues shown above.")
        override = input("  Run anyway? (y/n): ").strip().lower()
        if override != 'y':
            return
        print("  Proceeding despite validation errors...")

    # ---- Step 2: Review constraints ----
    constraints_dir = script_dir.parent / "output" / "generated_constraints"
    constraint_files = []
    if constraints_dir.exists():
        constraint_files = sorted(
            f for f in constraints_dir.glob("*.py") if f.name != "__init__.py"
        )

    if constraint_files:
        print("\n" + "=" * 60)
        print("STEP 2: REVIEW CONSTRAINTS")
        print("=" * 60)
        print(f"\n  {len(constraint_files)} saved constraint(s):\n")

        for i, filepath in enumerate(constraint_files, 1):
            description = ""
            try:
                for line in filepath.read_text().splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Description:"):
                        description = stripped[len("Description:"):].strip()
                        break
            except Exception:
                pass
            label = description or filepath.stem
            print(f"    {i}. {label}")

        print(f"\n  Options:")
        print(f"    y          - Apply all")
        print(f"    n          - Skip all (run without custom constraints)")
        print(f"    1,2        - Apply only selected (comma-separated numbers)")
        print(f"    clear      - Delete all and run without")
        print(f"    cancel     - Go back without running")

        choice = input(f"\n  Choice: ").strip().lower()

        if choice in ['cancel', 'back', 'c', 'b']:
            print("  Cancelled. Returning to main menu.")
            return

        if choice == 'clear':
            for f in constraint_files:
                f.unlink()
            print("  Cleared all constraints. Running without custom constraints.")
            constraint_files = []
            _temp_constraint_dir = None
        elif choice == 'n':
            # Temporarily move ALL constraints out
            import tempfile
            temp_dir = Path(tempfile.mkdtemp())
            for f in constraint_files:
                shutil.move(str(f), str(temp_dir / f.name))
            print("  Skipping all constraints for this run.")
            constraint_files = []
            _temp_constraint_dir = temp_dir
        elif choice == 'y':
            _temp_constraint_dir = None
        else:
            # Parse selected numbers
            try:
                selected = [int(x.strip()) for x in choice.split(',')]
                valid_selection = all(1 <= s <= len(constraint_files) for s in selected)
            except ValueError:
                valid_selection = False

            if not valid_selection:
                print(f"  Invalid selection. Use numbers 1-{len(constraint_files)} separated by commas.")
                return

            # Move NON-selected constraints out temporarily
            import tempfile
            temp_dir = Path(tempfile.mkdtemp())
            skip_files = []
            for i, f in enumerate(constraint_files, 1):
                if i not in selected:
                    shutil.move(str(f), str(temp_dir / f.name))
                    skip_files.append(f.name)

            applied_count = len(selected)
            skipped_count = len(constraint_files) - applied_count
            print(f"  Applying {applied_count} constraint(s), skipping {skipped_count}.")
            _temp_constraint_dir = temp_dir
            constraint_files = [f for i, f in enumerate(constraint_files, 1) if i in selected]
    else:
        print("\n  No custom constraints saved. Running with built-in constraints only.")
        _temp_constraint_dir = None

    # ---- Step 3: Schedule ----
    print("\n" + "=" * 60)
    print(f"STEP {'3' if constraint_files else '2'}: SCHEDULING")
    print("=" * 60)

    try:
        random.seed(42)

        scheduler = ConstraintScheduler(sections_path, cohorts_path, requirements_path)

        if not scheduler.load_data():
            print("\n  Failed to load data.")
            return

        scheduler._parse_sections()
        scheduler._generate_students()
        scheduler._build_model()

        if not scheduler.solve():
            print("\n  ✗ Solver could not find a solution.")
            
            # Check if custom constraints were applied
            has_custom = (scheduler._constraint_loader and 
                         scheduler._constraint_loader.applied_count > 0)
            
            if has_custom:
                loader_summary = scheduler._constraint_loader.summary()
                applied = [c for c in loader_summary['constraints'] if c['valid']]
                
                print(f"\n  {len(applied)} custom constraint(s) were applied:")
                for c in applied:
                    ctype = []
                    if c['hard']:
                        ctype.append("hard")
                    if c['soft']:
                        ctype.append("soft")
                    print(f"    - {c['description'] or c['file']} ({', '.join(ctype)})")
                
                print("\n  One or more of these may be too restrictive.")
                print("\n  Options:")
                print("    1. Retry without custom constraints (to check if they caused it)")
                print("    2. Go back and edit/remove constraints")
                
                choice = input("\n  Retry without constraints? (y/n): ").strip().lower()
                
                if choice == 'y':
                    print("\n  Retrying without custom constraints...")
                    
                    # Move constraints out temporarily
                    import tempfile
                    retry_temp = Path(tempfile.mkdtemp())
                    for f in constraints_dir.glob("*.py"):
                        if f.name != "__init__.py":
                            shutil.move(str(f), str(retry_temp / f.name))
                    
                    # Re-run scheduler
                    random.seed(42)
                    scheduler2 = ConstraintScheduler(sections_path, cohorts_path, requirements_path)
                    scheduler2.load_data()
                    scheduler2._parse_sections()
                    scheduler2._generate_students()
                    scheduler2._build_model()
                    
                    if scheduler2.solve():
                        print("\n  ✓ Solved WITHOUT custom constraints.")
                        print("  This confirms the custom constraint(s) caused the infeasibility.")
                        print("  Use 'list' and 'delete' to remove the problematic constraint.")
                        scheduler2.export_results()
                        scheduler2.print_summary()
                    else:
                        print("\n  ✗ Still infeasible without custom constraints.")
                        print("  The issue is in the base data, not the constraints.")
                        print("  Check section capacities and student counts.")
                    
                    # Restore constraint files
                    constraints_dir.mkdir(parents=True, exist_ok=True)
                    for f in retry_temp.glob("*.py"):
                        shutil.move(str(f), str(constraints_dir / f.name))
                    try:
                        retry_temp.rmdir()
                    except Exception:
                        pass
                    return
            else:
                print("  No custom constraints were applied.")
                print("  The issue is in the base data — check section capacities and student counts.")
            return

        scheduler.export_results()
        scheduler.print_summary()

    finally:
        # Always restore temporarily moved constraints
        if _temp_constraint_dir is not None:
            constraints_dir.mkdir(parents=True, exist_ok=True)
            for f in _temp_constraint_dir.glob("*.py"):
                shutil.move(str(f), str(constraints_dir / f.name))
            try:
                _temp_constraint_dir.rmdir()
            except Exception:
                pass


def main():
    """Interactive constraint generation and data editing interface."""
    print("\n" + "=" * 60)
    print("  SCHEDULING INTERFACE")
    print("=" * 60)
    print("\n  Add constraints or edit input data. Type 'help' for commands.")
    print("\n  Constraint examples:")
    print("    Limit MECE students to no more than 50% of any MATH 181 section")
    print("    No more than 30% Engineering students in any MATH 181 section")
    print("\n  Data edit examples:")
    print("    show MATH 181              (view sections)")
    print("    capacity MATH 181 3 +5     (add 5 seats to section 3)")
    print("    students MECE-BS +20       (add 20 students)")
    print("    addsection MATH 181 35 09:00 10:15 TR  (add a section)")
    print()

    # Initialize generator and editor
    generator = LLMConstraintGenerator()
    editor = DataEditor()

    # Load context
    context = load_context_from_data()
    print(f"  Loaded {len(context['programs'])} programs and {len(context['courses'])} courses\n")

    # Track files for delete command
    last_listed_files = []

    while True:
        print("=" * 60)
        print("  Type a constraint, data edit, or command (help for options)")
        user_input = input("\n  >> ").strip()

        if not user_input:
            continue

        # Handle commands
        lower = user_input.lower()

        if lower in ['quit', 'exit', 'q']:
            print("\n  Goodbye!")
            break

        if lower in ['help', 'h', '?']:
            print("\n  CONSTRAINT COMMANDS:")
            print("    (type constraint)    - Generate CP-SAT code from natural language")
            print("    list                 - Show all saved constraints")
            print("    delete <num>         - Delete a constraint by its list number")
            print("    clear                - Delete all saved constraints")
            print("\n  DATA COMMANDS:")
            print("    show <course>        - Show sections (e.g. show MATH 181)")
            print("    show <program>       - Show cohort info (e.g. show MECE-BS)")
            print("    show programs        - Show all programs and student counts")
            print("    capacity <course> <section> <+/-N>")
            print("                         - Adjust section capacity")
            print("                           e.g. capacity MATH 181 3 +5")
            print("    capacity <course> all <+/-N>")
            print("                         - Adjust all sections of a course")
            print("                           e.g. capacity CSCI 141 all +10")
            print("    addsection <course> <capacity> <start> <end> <days>")
            print("                         - Add a new section")
            print("                           e.g. addsection MATH 181 35 09:00 10:15 TR")
            print("    students <program> <+/-N>")
            print("                         - Adjust cohort size")
            print("                           e.g. students MECE-BS +20")
            print("    undo                 - Undo last data change")
            print("    reset                - Restore all files to original state")
            print("\n  GENERAL:")
            print("    run                  - Run scheduler with current constraints")
            print("    help                 - Show this help message")
            print("    quit                 - Exit")
            continue

        # --- Constraint management commands ---

        if lower == 'list':
            last_listed_files = list_constraints()
            continue

        if lower.startswith('delete'):
            parts = lower.split()
            if len(parts) < 2:
                last_listed_files = list_constraints()
                if last_listed_files:
                    num = input("  Enter number to delete: ").strip()
                    delete_constraint(last_listed_files, num)
            else:
                if not last_listed_files:
                    last_listed_files = list_constraints()
                delete_constraint(last_listed_files, parts[1])
            continue

        if lower == 'clear':
            clear_all_constraints()
            continue

        if lower == 'run':
            print()
            run_scheduler()
            continue

        if lower == 'undo':
            editor.undo()
            continue

        if lower == 'reset':
            confirm = input("  Reset ALL data files to original? This cannot be undone. (y/n): ").strip().lower()
            if confirm == 'y':
                editor.reset()
            else:
                print("  Cancelled.")
            continue

        # --- Data show commands ---

        if lower.startswith('show '):
            target = user_input[5:].strip()

            if target.lower() == 'programs':
                editor.show_cohort()
                continue

            # Check if it's a program (ends with -BS, -MS, etc.)
            if '-' in target and target.upper() == target:
                editor.show_cohort(target)
                continue

            # Otherwise treat as a course
            editor.show_sections(target.upper())
            continue

        # --- Capacity command ---

        if lower.startswith('capacity '):
            # Parse: capacity COURSE_SUBJECT COURSE_NUM SECTION DELTA
            # e.g.  capacity MATH 181 3 +5
            # e.g.  capacity CSCI 141 all +10
            parts = user_input.split()
            if len(parts) < 5:
                print("  Usage: capacity <SUBJECT> <NUM> <section|all> <+/-amount>")
                print("  Example: capacity MATH 181 3 +5")
                continue

            course = f"{parts[1].upper()} {parts[2]}"
            section_or_all = parts[3]
            try:
                delta = int(parts[4])
            except ValueError:
                print(f"  Invalid amount: {parts[4]}. Use +5 or -5 or a number.")
                continue

            if section_or_all.lower() == 'all':
                editor.adjust_all_sections(course, delta)
            else:
                editor.adjust_section_capacity(course, section_or_all, delta)
            continue

        # --- Add section command ---

        if lower.startswith('addsection '):
            # Parse: addsection SUBJECT NUM CAPACITY START END DAYS
            # e.g.  addsection MATH 181 35 09:00 10:15 TR
            parts = user_input.split()
            if len(parts) < 7:
                print("  Usage: addsection <SUBJECT> <NUM> <capacity> <start> <end> <days>")
                print("  Example: addsection MATH 181 35 09:00 10:15 TR")
                print("  Days: M=Mon, T=Tue, W=Wed, R=Thu, F=Fri")
                continue

            course = f"{parts[1].upper()} {parts[2]}"
            try:
                capacity = int(parts[3])
            except ValueError:
                print(f"  Invalid capacity: {parts[3]}. Must be a number.")
                continue

            start_time = parts[4]
            end_time = parts[5]
            days = parts[6].upper()

            # Validate days
            valid_days = set('MTWRF')
            if not all(c in valid_days for c in days):
                print(f"  Invalid days: {days}. Use M=Mon, T=Tue, W=Wed, R=Thu, F=Fri")
                continue

            editor.add_section(course, capacity, start_time, end_time, days)
            continue

        # --- Students command ---

        if lower.startswith('students '):
            # Parse: students PROGRAM DELTA
            # e.g.  students MECE-BS +20
            parts = user_input.split()
            if len(parts) < 3:
                print("  Usage: students <PROGRAM> <+/-amount>")
                print("  Example: students MECE-BS +20")
                continue

            program = parts[1].upper()
            try:
                delta = int(parts[2])
            except ValueError:
                print(f"  Invalid amount: {parts[2]}. Use +20 or -10 or a number.")
                continue

            editor.adjust_cohort_size(program, delta)
            continue

        # --- Otherwise, treat as a constraint to generate ---

        # Clean input: strip leading >> prompt characters and extra whitespace
        clean_input = user_input.lstrip('>').strip()
        
        if not clean_input:
            print("  Empty input after cleaning. Please type a constraint.")
            continue

        # Show cleaned input and confirm before sending to LLM
        if clean_input != user_input.strip():
            print(f"\n  Cleaned input: {clean_input}")
        
        print(f"\n  Constraint: {clean_input}")
        confirm = input("  Send to LLM? (y/n): ").strip().lower()
        if confirm != 'y':
            print("  Cancelled.")
            continue

        print()
        success, code, error = generator.generate_with_retry(
            clean_input, context, auto_save=False
        )

        if not success:
            print(f"\n  FAILED: {error}")
            continue

        print(f"\n  Generated Code:")
        print(f"  {'-'*55}")
        for line in code.splitlines():
            print(f"  {line}")
        print(f"  {'-'*55}")

        # Ask before saving
        apply = input("\n  Save this constraint? (y/n): ").strip().lower()

        if apply == 'y':
            filepath = generator.save_constraint(clean_input, code)
            print(f"  Constraint saved!")

            # Offer to run scheduler immediately
            run_now = input("  Run scheduler now? (y/n): ").strip().lower()
            if run_now == 'y':
                print()
                run_scheduler()
        else:
            print("  Constraint discarded.")

        print()


if __name__ == "__main__":
    main()