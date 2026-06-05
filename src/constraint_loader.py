"""
Constraint Loader for Freshman Scheduling
==========================================
Bridges LLM-generated constraint files and the CP-SAT scheduler.

Loads saved constraint .py files from the output directory, validates them,
and executes them against the live model during scheduling.

Usage:
    loader = ConstraintLoader(constraints_dir="output/generated_constraints")
    loader.load_all()
    loader.apply_all(model, students, sections, assignment_vars, objective_terms)
"""

import ast
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class LoadedConstraint:
    """A validated constraint ready for execution."""
    filepath: Path
    code: str
    description: str = ""
    has_hard_constraints: bool = False
    has_soft_constraints: bool = False
    errors: List[str] = field(default_factory=list)


class ConstraintLoader:
    """Load and apply LLM-generated constraints to a CP-SAT model."""

    # Patterns that must never appear in constraint code
    FORBIDDEN_PATTERNS = ['import ', 'exec(', 'eval(', '__', 'open(', 'os.', 'sys.', 'subprocess']

    # Variables exposed to constraint code
    ALLOWED_CONTEXT_KEYS = {'model', 'students', 'sections', 'assignment_vars', 'objective_terms'}

    def __init__(self, constraints_dir: str = None):
        """
        Initialize the loader.

        Args:
            constraints_dir: Path to directory containing generated .py constraint files.
                             Defaults to output/generated_constraints relative to this file.
        """
        if constraints_dir is None:
            constraints_dir = Path(__file__).parent.parent / "output" / "generated_constraints"
        self.constraints_dir = Path(constraints_dir)
        self.constraints: List[LoadedConstraint] = []
        self.applied_count = 0
        self.skipped_count = 0

    # =========================================================================
    # LOADING
    # =========================================================================

    def load_all(self) -> int:
        """
        Discover and validate all constraint files in the directory.

        Returns:
            Number of valid constraints loaded.
        """
        self.constraints = []

        if not self.constraints_dir.exists():
            print(f"ℹ Constraints directory not found: {self.constraints_dir}")
            print("  No custom constraints will be applied.")
            return 0

        py_files = sorted(
            f for f in self.constraints_dir.glob("*.py")
            if f.name != "__init__.py"
        )

        if not py_files:
            print(f"ℹ No constraint files found in {self.constraints_dir}")
            return 0

        print(f"\n{'='*60}")
        print("LOADING CUSTOM CONSTRAINTS")
        print(f"{'='*60}")
        print(f"Directory: {self.constraints_dir}")
        print(f"Found {len(py_files)} file(s)\n")

        valid_count = 0
        for filepath in py_files:
            constraint = self._load_file(filepath)
            self.constraints.append(constraint)

            if not constraint.errors:
                valid_count += 1
                print(f"  ✓ {filepath.name}")
                if constraint.description:
                    print(f"    Description: {constraint.description}")
                tags = []
                if constraint.has_hard_constraints:
                    tags.append("hard")
                if constraint.has_soft_constraints:
                    tags.append("soft")
                if tags:
                    print(f"    Type: {', '.join(tags)} constraint(s)")
            else:
                print(f"  ✗ {filepath.name}")
                for err in constraint.errors:
                    print(f"    Error: {err}")

        print(f"\n✓ {valid_count}/{len(py_files)} constraints valid and ready")
        return valid_count

    def load_from_code(self, code: str, description: str = "inline") -> bool:
        """
        Load a constraint directly from a code string (useful for the interactive interface).

        Args:
            code: Python code string for the constraint.
            description: Human-readable description.

        Returns:
            True if the code passed validation.
        """
        constraint = LoadedConstraint(
            filepath=Path(f"<inline:{description}>"),
            code=code,
            description=description,
        )
        self._validate(constraint)

        self.constraints.append(constraint)
        return len(constraint.errors) == 0

    def _load_file(self, filepath: Path) -> LoadedConstraint:
        """Read and validate a single constraint file."""
        try:
            code = filepath.read_text()
        except Exception as e:
            return LoadedConstraint(
                filepath=filepath, code="", errors=[f"Could not read file: {e}"]
            )

        # Extract description from docstring if present
        description = self._extract_description(code)

        constraint = LoadedConstraint(
            filepath=filepath,
            code=code,
            description=description,
        )
        self._validate(constraint)
        return constraint

    @staticmethod
    def _extract_description(code: str) -> str:
        """Pull the 'Description:' line from the file header docstring."""
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("Description:"):
                return stripped[len("Description:"):].strip()
        return ""

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate(self, constraint: LoadedConstraint) -> None:
        """Run syntax and security checks on a constraint."""
        code = constraint.code

        # --- Syntax check ---
        try:
            ast.parse(code)
        except SyntaxError as e:
            constraint.errors.append(f"Syntax error on line {e.lineno}: {e.msg}")
            return  # No point continuing if it won't parse

        # --- Forbidden patterns (security) ---
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in code:
                constraint.errors.append(f"Forbidden pattern: '{pattern}'")

        # --- Must actually do something ---
        constraint.has_hard_constraints = 'model.Add' in code
        constraint.has_soft_constraints = 'objective_terms.append' in code

        if not (constraint.has_hard_constraints or constraint.has_soft_constraints):
            constraint.errors.append(
                "Code does not add any constraints (no model.Add or objective_terms.append)"
            )

    # =========================================================================
    # APPLICATION
    # =========================================================================

    def apply_all(
        self,
        model,
        students: List[Dict[str, Any]],
        sections: Dict[str, list],
        assignment_vars: Dict[str, Dict[str, Dict[int, Any]]],
        objective_terms: list,
    ) -> Tuple[int, int]:
        """
        Execute all valid constraints against the live model.

        Args:
            model: The CP-SAT CpModel instance.
            students: List of student dicts (student_id, program, required_courses).
            sections: Dict mapping course name -> list of section info dicts.
            assignment_vars: Nested dict  sid -> course -> section_idx -> BoolVar.
            objective_terms: Mutable list that soft constraints can append to.

        Returns:
            (applied_count, skipped_count)
        """
        valid = [c for c in self.constraints if not c.errors]

        if not valid:
            return 0, len(self.constraints)

        print(f"\nApplying {len(valid)} custom constraint(s)...")

        self.applied_count = 0
        self.skipped_count = 0

        for constraint in valid:
            success, error = self._apply_one(
                constraint, model, students, sections, assignment_vars, objective_terms
            )
            if success:
                self.applied_count += 1
                label = constraint.description or constraint.filepath.name
                print(f"  ✓ Applied: {label}")
            else:
                self.skipped_count += 1
                label = constraint.description or constraint.filepath.name
                print(f"  ✗ Failed:  {label}")
                print(f"    Error: {error}")

        # Count already-invalid ones as skipped too
        self.skipped_count += sum(1 for c in self.constraints if c.errors)

        print(f"\n✓ Constraints applied: {self.applied_count}, skipped: {self.skipped_count}")
        return self.applied_count, self.skipped_count

    # Safe built-in functions that constraint code is allowed to use
    SAFE_BUILTINS = {
        'True': True, 'False': False, 'None': None,
        'abs': abs, 'all': all, 'any': any, 'bool': bool,
        'dict': dict, 'enumerate': enumerate, 'filter': filter,
        'float': float, 'frozenset': frozenset, 'int': int,
        'isinstance': isinstance, 'len': len, 'list': list,
        'map': map, 'max': max, 'min': min, 'range': range,
        'reversed': reversed, 'round': round, 'set': set,
        'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple,
        'zip': zip,
    }

    def _apply_one(
        self,
        constraint: LoadedConstraint,
        model,
        students,
        sections,
        assignment_vars,
        objective_terms,
    ) -> Tuple[bool, str]:
        """
        Execute a single constraint's code in a sandboxed namespace.

        Returns:
            (success, error_message)
        """
        # Build a restricted namespace with only the variables the code needs
        namespace = {
            'model': model,
            'students': students,
            'sections': sections,
            'assignment_vars': assignment_vars,
            'objective_terms': objective_terms,
        }

        try:
            exec(constraint.code, {"__builtins__": self.SAFE_BUILTINS}, namespace)
            return True, ""
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    # =========================================================================
    # UTILITY
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict (useful for logging or export)."""
        return {
            'total_files': len(self.constraints),
            'valid': sum(1 for c in self.constraints if not c.errors),
            'invalid': sum(1 for c in self.constraints if c.errors),
            'applied': self.applied_count,
            'skipped': self.skipped_count,
            'constraints': [
                {
                    'file': str(c.filepath.name),
                    'description': c.description,
                    'valid': len(c.errors) == 0,
                    'hard': c.has_hard_constraints,
                    'soft': c.has_soft_constraints,
                    'errors': c.errors,
                }
                for c in self.constraints
            ],
        }

    def list_constraints(self) -> None:
        """Pretty-print all loaded constraints."""
        if not self.constraints:
            print("No constraints loaded.")
            return

        print(f"\n{'='*60}")
        print(f"LOADED CONSTRAINTS ({len(self.constraints)})")
        print(f"{'='*60}")

        for i, c in enumerate(self.constraints, 1):
            status = "✓" if not c.errors else "✗"
            label = c.description or c.filepath.name
            print(f"\n  {i}. [{status}] {label}")
            if c.errors:
                for err in c.errors:
                    print(f"       Error: {err}")