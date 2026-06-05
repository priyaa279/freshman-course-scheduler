"""
Verify Generated Constraints
Checks syntax and structure of all generated constraint files
"""

from pathlib import Path
import ast

def verify_constraint_file(filepath: Path) -> dict:
    """Verify a single constraint file."""
    result = {
        'file': filepath.name,
        'syntax_valid': False,
        'has_model_add': False,
        'has_objective_terms': False,
        'line_count': 0,
        'errors': []
    }
    
    try:
        # Read file
        with open(filepath) as f:
            content = f.read()
        
        # Count lines
        result['line_count'] = len(content.split('\n'))
        
        # Check syntax
        try:
            ast.parse(content)
            result['syntax_valid'] = True
        except SyntaxError as e:
            result['errors'].append(f"Syntax error: {e}")
        
        # Check for required patterns
        if 'model.Add' in content:
            result['has_model_add'] = True
        
        if 'objective_terms.append' in content:
            result['has_objective_terms'] = True
        
        # Must have at least one constraint type
        if not (result['has_model_add'] or result['has_objective_terms']):
            result['errors'].append("No constraints found (no model.Add or objective_terms)")
        
    except Exception as e:
        result['errors'].append(f"Error reading file: {e}")
    
    return result


def main():
    """Verify all generated constraints."""
    constraints_dir = Path("output/generated_constraints")
    
    if not constraints_dir.exists():
        print("❌ No constraints directory found!")
        return
    
    # Find all .py files (exclude __init__.py)
    constraint_files = [f for f in constraints_dir.glob("*.py") if f.name != "__init__.py"]
    
    if not constraint_files:
        print("❌ No constraint files found!")
        return
    
    print("\n" + "=" * 70)
    print("CONSTRAINT VERIFICATION REPORT")
    print("=" * 70)
    
    all_valid = True
    
    for filepath in sorted(constraint_files):
        result = verify_constraint_file(filepath)
        
        print(f"\n📄 {result['file']}")
        print(f"   Lines: {result['line_count']}")
        print(f"   Syntax: {'✅ Valid' if result['syntax_valid'] else '❌ Invalid'}")
        
        if result['has_model_add']:
            print(f"   Hard Constraints: ✅ Yes (model.Add)")
        if result['has_objective_terms']:
            print(f"   Soft Constraints: ✅ Yes (objective_terms)")
        
        if result['errors']:
            all_valid = False
            print(f"   Errors:")
            for error in result['errors']:
                print(f"      ❌ {error}")
    
    print("\n" + "=" * 70)
    if all_valid:
        print("✅ ALL CONSTRAINTS VALID!")
    else:
        print("⚠️  Some constraints have issues")
    print("=" * 70 + "\n")
    
    # Summary
    print(f"Total constraints: {len(constraint_files)}")
    print(f"Valid syntax: {sum(1 for f in constraint_files if verify_constraint_file(f)['syntax_valid'])}")
    print(f"With hard constraints: {sum(1 for f in constraint_files if verify_constraint_file(f)['has_model_add'])}")
    print(f"With soft constraints: {sum(1 for f in constraint_files if verify_constraint_file(f)['has_objective_terms'])}")


if __name__ == "__main__":
    main()