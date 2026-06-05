"""
End-to-End Scheduling Pipeline
================================
Runs the full scheduling workflow in one command:

  1. Data Validation   — Check input files for errors
  2. Scheduling        — Build model, load custom constraints, solve
  3. Export            — Save results organized by program

Usage:
  python pipeline.py                     # Run full pipeline
  python pipeline.py -v                  # Verbose validation output
  python pipeline.py --skip-validation   # Skip validation (use with caution)
  python pipeline.py --dry-run           # Validate only, don't schedule

Exit Codes:
  0 = Success (all students scheduled)
  1 = Validation failed (fix data before scheduling)
  2 = Scheduling failed (solver could not find solution)
  3 = Partial success (some students not fully scheduled)
"""

import sys
import argparse
import random
import time
from pathlib import Path

from data_validation import DataValidator
from constraint_scheduler import ConstraintScheduler


def run_pipeline(args) -> int:
    """
    Run the full scheduling pipeline.
    
    Returns exit code:
        0 = full success
        1 = validation failed
        2 = scheduling failed
        3 = partial scheduling
    """
    start_time = time.time()
    
    # Resolve paths
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    
    sections_path = data_dir / "course_sections.csv"
    cohorts_path = data_dir / "program_cohort_distribution.csv"
    requirements_path = data_dir / "program_course_requirements.csv"
    
    # Allow command line overrides
    if args.files and len(args.files) >= 3:
        sections_path, cohorts_path, requirements_path = [Path(f) for f in args.files[:3]]
    
    # Check files exist
    for path in [sections_path, cohorts_path, requirements_path]:
        if not path.exists():
            print(f"\n❌ File not found: {path}")
            print("Please check your data directory and file paths.")
            return 1
    
    print("\n" + "#" * 60)
    print("# FRESHMAN SCHEDULING PIPELINE")
    print("#" * 60)
    print(f"\nData directory: {data_dir}")
    print(f"  • Sections:     {sections_path.name}")
    print(f"  • Cohorts:      {cohorts_path.name}")
    print(f"  • Requirements: {requirements_path.name}")
    
    # =========================================================================
    # STEP 1: DATA VALIDATION
    # =========================================================================
    
    if not args.skip_validation:
        print("\n")
        print("=" * 60)
        print("STEP 1: DATA VALIDATION")
        print("=" * 60)
        
        validator = DataValidator(
            sections_path,
            cohorts_path,
            requirements_path,
            verbose=args.verbose
        )
        
        # Load and validate
        if not validator.load_data():
            validator.print_summary()
            return 1
        
        validator.validate_sections()
        validator.validate_cohorts()
        validator.validate_requirements()
        validator.check_feasibility()
        validator.check_nway_conflicts()
        validator.check_effective_capacity()
        validator.export_audit_csvs()
        
        validation_passed = validator.print_summary()
        
        if not validation_passed:
            print("\n⛔ Pipeline stopped: Fix validation errors before scheduling.")
            print("   Run with --skip-validation to override (not recommended).")
            return 1
        
        if args.dry_run:
            print("\n🏁 Dry run complete. Validation passed, no scheduling performed.")
            elapsed = time.time() - start_time
            print(f"   Total time: {elapsed:.1f} seconds")
            return 0
    else:
        print("\n⚠️  Skipping validation (--skip-validation flag set)")
        if args.dry_run:
            print("   Nothing to do with --dry-run and --skip-validation together.")
            return 0
    
    # =========================================================================
    # STEP 2: SCHEDULING
    # =========================================================================
    
    print("\n")
    print("=" * 60)
    print("STEP 2: SCHEDULING")
    print("=" * 60)
    
    random.seed(args.seed)
    print(f"\nRandom seed: {args.seed}")
    
    scheduler = ConstraintScheduler(
        sections_path,
        cohorts_path,
        requirements_path
    )
    
    if not scheduler.load_data():
        print("\n❌ Failed to load data for scheduling.")
        return 2
    
    scheduler._parse_sections()
    scheduler._generate_students()
    scheduler._build_model()
    
    if not scheduler.solve():
        print("\n❌ Solver could not find a solution.")
        print("   This may be due to conflicting constraints or insufficient capacity.")
        return 2
    
    # =========================================================================
    # STEP 3: EXPORT
    # =========================================================================
    
    print("\n")
    print("=" * 60)
    print("STEP 3: EXPORT RESULTS")
    print("=" * 60)
    
    scheduler.export_results()
    scheduler.print_summary()
    
    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    
    elapsed = time.time() - start_time
    
    print("\n" + "#" * 60)
    print("# PIPELINE COMPLETE")
    print("#" * 60)
    print(f"\n  Total time: {elapsed:.1f} seconds")
    print(f"  Students:   {scheduler.stats['total_students']}")
    print(f"  Scheduled:  {scheduler.stats['fully_scheduled']}")
    print(f"  Solver:     {scheduler.stats['solver_status']}")
    
    if scheduler.stats['partially_scheduled'] > 0:
        print(f"\n  ⚠️  {scheduler.stats['partially_scheduled']} students not fully scheduled")
        return 3
    else:
        print(f"\n  ✅ All students fully scheduled!")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run the full freshman scheduling pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py                     # Full pipeline
  python pipeline.py -v                  # Verbose validation
  python pipeline.py --dry-run           # Validate only
  python pipeline.py --skip-validation   # Skip validation
  python pipeline.py --seed 123          # Custom random seed

Exit Codes:
  0 = All students scheduled successfully
  1 = Validation failed
  2 = Scheduling failed (no solution)
  3 = Partial success (some students not scheduled)
        """
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed validation output'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run validation only, do not schedule'
    )
    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip data validation (not recommended)'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for student generation (default: 42)'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Optional: paths to sections, cohorts, requirements CSV files'
    )
    
    args = parser.parse_args()
    
    exit_code = run_pipeline(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()