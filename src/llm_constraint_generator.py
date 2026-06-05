"""
LLM Constraint Generator for Freshman Scheduling
Generates CP-SAT constraint code from natural language using Claude API
"""

import os
import yaml
import json
import ast
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict, Any
from dotenv import load_dotenv
import anthropic


class LLMConstraintGenerator:
    """Generate scheduling constraints from natural language using Claude."""
    
    def __init__(self, config_path: str = None):
        """Initialize with config file and API credentials."""
        # Load environment variables
        load_dotenv()
        
        # Load config
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "llm_config.yaml"
        
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        # Get API key
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in .env file")
        
        # Initialize Anthropic client
        self.client = anthropic.Anthropic(api_key=self.api_key)
        
        # Setup logging
        self.output_dir = Path(self.config['output']['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"✓ LLM Generator initialized: {self.config['llm']['model']}")
    
    def generate_constraint(self, natural_language: str, context: Dict[str, Any] = None, auto_save: bool = True) -> Tuple[bool, str, str]:
        """
        Generate constraint code from natural language.
        
        Args:
            natural_language: User's constraint description
            context: Optional context about available courses, programs, etc.
            auto_save: If True, saves valid constraint to disk immediately.
                       Set False when caller wants to confirm before saving.
        
        Returns:
            (success, code, error_message)
        """
        print(f"\n{'='*60}")
        print(f"GENERATING CONSTRAINT")
        print(f"{'='*60}")
        print(f"Input: {natural_language}")
        
        # Build prompt
        messages = self._build_prompt(natural_language, context)
        
        # Call Claude API
        try:
            response = self.client.messages.create(
                model=self.config['llm']['model'],
                max_tokens=self.config['llm']['max_tokens'],
                temperature=self.config['llm']['temperature'],
                system=self.config['system_prompt'],
                messages=messages
            )
            
            generated_code = response.content[0].text
            
            # Log the request
            if self.config['output']['log_requests']:
                self._log_request(natural_language, generated_code)
            
            # print(f"\n✓ Generated {len(generated_code)} characters of code")
            
            # Validate the code
            if self.config['validation']['syntax_check']:
                valid, error = self._validate_syntax(generated_code)
                if not valid:
                    print(f"✗ Syntax validation failed: {error}")
                    return False, generated_code, f"Syntax error: {error}"
            
            if self.config['validation']['semantic_check']:
                valid, error = self._validate_semantics(generated_code)
                if not valid:
                    print(f"✗ Semantic validation failed: {error}")
                    return False, generated_code, f"Semantic error: {error}"
            
            # Check for hallucinated program names
            if context and 'programs' in context:
                warnings = self._check_program_names(generated_code, context['programs'])
                if warnings:
                    print(f"⚠ Program name warning:")
                    for w in warnings:
                        print(f"  - {w}")
                    return False, generated_code, f"Unknown program names in code: {', '.join(warnings)}. Use exact names from the data."
            
            print(f"✓ Code validation passed")
            
            # Save if configured and auto_save is enabled
            if auto_save and self.config['output']['save_generated']:
                self.save_constraint(natural_language, generated_code)
            
            return True, generated_code, ""
            
        except Exception as e:
            error_msg = f"API call failed: {str(e)}"
            print(f"✗ {error_msg}")
            return False, "", error_msg
    
    def _build_prompt(self, natural_language: str, context: Dict[str, Any] = None) -> list:
        """Build the prompt with few-shot examples."""
        messages = []
        
        # Add few-shot examples
        for example in self.config['few_shot_examples']:
            messages.append({
                "role": "user",
                "content": example['input']
            })
            messages.append({
                "role": "assistant",
                "content": example['output']
            })
        
        # Add context if provided
        user_message = natural_language
        if context:
            context_str = "\n\nIMPORTANT — USE ONLY THESE EXACT NAMES:\n"
            if 'programs' in context:
                context_str += f"Valid program names: {', '.join(context['programs'])}\n"
                context_str += "Do NOT invent or guess program names. Use ONLY the names listed above.\n"
            if 'courses' in context:
                context_str += f"Valid courses: {', '.join(context['courses'])}\n"
            user_message += context_str
        
        # Add the actual user request
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        return messages
    
    def _validate_syntax(self, code: str) -> Tuple[bool, str]:
        """Check if the generated code is valid Python syntax."""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
    
    def _validate_semantics(self, code: str) -> Tuple[bool, str]:
        """Check if the code uses correct variable names and patterns."""
        required_patterns = ['model', 'students', 'sections', 'assignment_vars']
        forbidden_patterns = ['import ', 'exec(', 'eval(', '__']
        
        # Check for forbidden patterns (security)
        for pattern in forbidden_patterns:
            if pattern in code:
                return False, f"Forbidden pattern detected: {pattern}"
        
        # Check for proper constraint usage
        if 'model.Add' in code or 'objective_terms.append' in code:
            return True, ""
        else:
            return False, "Code doesn't add any constraints (no model.Add or objective_terms)"
    
    @staticmethod
    def _check_program_names(code: str, valid_programs: list) -> list:
        """Check if the code references program names not in the actual data.
        
        Returns list of unknown program names found (empty if all are valid).
        """
        import re
        # Find quoted strings that look like program names (e.g., 'COMPSCI-BS', "MECE-BS")
        quoted_strings = re.findall(r"""['"]([A-Z][A-Z0-9]*-[A-Z]{1,3})['"]""", code)
        
        unknown = []
        valid_set = set(valid_programs)
        for name in quoted_strings:
            if name not in valid_set and name not in unknown:
                unknown.append(name)
        
        return unknown
    
    def _log_request(self, input_text: str, output_code: str):
        """Log the API request and response."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.output_dir / f"request_{timestamp}.json"
        
        log_data = {
            'timestamp': timestamp,
            'input': input_text,
            'output': output_code,
            'model': self.config['llm']['model']
        }
        
        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)
    
    def save_constraint(self, description: str, code: str) -> Path:
        """Save generated constraint to a Python file.
        
        Returns:
            Path to the saved file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create safe filename from description
        safe_name = "".join(c if c.isalnum() or c in (' ', '_') else '' for c in description)
        safe_name = safe_name.replace(' ', '_')[:50]
        
        filename = f"{timestamp}_{safe_name}.py"
        filepath = self.output_dir / filename
        
        # Write file with header comment
        with open(filepath, 'w') as f:
            f.write(f'"""\nGenerated Constraint\n')
            f.write(f'Description: {description}\n')
            f.write(f'Generated: {timestamp}\n')
            f.write(f'"""\n\n')
            f.write(code)
        
        print(f"✓ Saved constraint to: {filepath}")
        return filepath
    
    def generate_with_retry(self, natural_language: str, context: Dict[str, Any] = None, 
                           max_retries: int = None, auto_save: bool = True) -> Tuple[bool, str, str]:
        """Generate constraint with automatic retry on failure.
        
        On retry, passes the actual error and failed code back to Claude
        so it can make a targeted fix instead of guessing.
        
        Args:
            natural_language: Constraint description
            context: Available programs/courses
            max_retries: Override default retry count
            auto_save: If True, saves to disk on success. Set False to let caller control saving.
        """
        if max_retries is None:
            max_retries = self.config['validation']['max_retries']
        
        last_error = ""
        last_code = ""
        prompt = natural_language
        
        for attempt in range(max_retries):
            if attempt > 0:
                # Wait before retrying — longer for API errors (server overloaded)
                if not last_code:
                    wait = 5 * attempt  # 5s, 10s for API errors
                    print(f"\n  API unavailable. Waiting {wait}s before retry...")
                    import time
                    time.sleep(wait)
                
                print(f"\nRetry attempt {attempt + 1}/{max_retries}")
                # Only include error feedback if we got actual code that failed validation
                # (not if the API itself was unreachable)
                if last_code:
                    prompt = (
                        f"{natural_language}\n\n"
                        f"IMPORTANT: Your previous attempt failed validation.\n"
                        f"Error: {last_error}\n"
                        f"Failed code:\n```\n{last_code}\n```\n"
                        f"Please fix this specific error and regenerate."
                    )
                else:
                    # API error (timeout, overloaded, etc.) — just retry the original prompt
                    prompt = natural_language
            
            success, code, error = self.generate_constraint(prompt, context, auto_save=False)
            
            if success:
                # Only save the successful final result if auto_save is on
                if auto_save and self.config['output']['save_generated']:
                    self.save_constraint(natural_language, code)
                return True, code, ""
            
            last_error = error
            last_code = code
            
            if attempt == max_retries - 1:
                return False, code, f"Failed after {max_retries} attempts. Last error: {error}"
        
        return False, "", "Max retries exceeded"


def main():
    """Demo the LLM constraint generator."""
    print("\n" + "#" * 60)
    print("# LLM CONSTRAINT GENERATOR - DEMO")
    print("#" * 60)
    
    # Initialize generator
    generator = LLMConstraintGenerator()
    
    # Example context
    context = {
        'programs': ['COMPSCI-BS', 'MECE-BS', 'EEEE-BS', 'BIOL-BS'],
        'courses': ['CSCI 141', 'MATH 181', 'PHYS 211', 'CHEM 124']
    }
    
    # Test constraint
    test_constraint = "Limit Engineering students to no more than 60% of any PHYS 211 section"
    
    print(f"\nTest constraint: {test_constraint}")
    
    success, code, error = generator.generate_with_retry(test_constraint, context)
    
    if success:
        print(f"\n✅ SUCCESS!")
        print(f"\nGenerated Code:")
        print("-" * 60)
        print(code)
        print("-" * 60)
    else:
        print(f"\n❌ FAILED: {error}")


if __name__ == "__main__":
    main()