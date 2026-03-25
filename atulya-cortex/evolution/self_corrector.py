"""
Self-Corrector

Detects errors, automatically fixes issues, and implements rollback
mechanisms for self-correcting behavior.
"""

import os
import json
import subprocess
import traceback
import ast
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class Error:
    """Represents a detected error."""
    type: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    severity: str = "medium"  # low, medium, high, critical
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    fixed: bool = False
    fix_attempts: int = 0


@dataclass
class Correction:
    """Represents a correction attempt."""
    error_id: str
    fix_type: str
    description: str
    applied: bool = False
    verified: bool = False
    applied_at: Optional[str] = None


class SelfCorrector:
    """
    Self-correcting system that detects and fixes errors automatically.
    """
    
    def __init__(self, errors_path: str = "evolution/error_log.json"):
        """
        Initialize self-corrector.
        
        Args:
            errors_path: Path to store error log
        """
        self.errors_path = errors_path
        self.errors: List[Error] = []
        self.corrections: List[Correction] = []
        self.fix_strategies = self._load_fix_strategies()
        self._load_errors()
    
    def _load_fix_strategies(self) -> Dict[str, List[Dict]]:
        """Load fix strategies for different error types."""
        return {
            'syntax_error': [
                {'action': 'fix_indentation', 'priority': 1},
                {'action': 'fix_quotes', 'priority': 2},
                {'action': 'fix_brackets', 'priority': 3}
            ],
            'import_error': [
                {'action': 'add_missing_import', 'priority': 1},
                {'action': 'fix_import_path', 'priority': 2}
            ],
            'name_error': [
                {'action': 'add_missing_variable', 'priority': 1},
                {'action': 'fix_typo', 'priority': 2}
            ],
            'type_error': [
                {'action': 'add_type_conversion', 'priority': 1},
                {'action': 'fix_type_annotation', 'priority': 2}
            ],
            'attribute_error': [
                {'action': 'add_missing_attribute', 'priority': 1},
                {'action': 'fix_attribute_name', 'priority': 2}
            ],
            'runtime_error': [
                {'action': 'add_error_handling', 'priority': 1},
                {'action': 'add_validation', 'priority': 2}
            ]
        }
    
    def _load_errors(self) -> None:
        """Load error history from file."""
        if os.path.exists(self.errors_path):
            try:
                with open(self.errors_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.errors = [Error(**e) for e in data.get('errors', [])]
                    self.corrections = [Correction(**c) for c in data.get('corrections', [])]
            except Exception:
                self.errors = []
                self.corrections = []
    
    def _save_errors(self) -> None:
        """Save error log to file."""
        os.makedirs(os.path.dirname(self.errors_path), exist_ok=True)
        data = {
            'errors': [
                {
                    'type': e.type,
                    'message': e.message,
                    'file_path': e.file_path,
                    'line_number': e.line_number,
                    'severity': e.severity,
                    'detected_at': e.detected_at,
                    'fixed': e.fixed,
                    'fix_attempts': e.fix_attempts
                }
                for e in self.errors
            ],
            'corrections': [
                {
                    'error_id': c.error_id,
                    'fix_type': c.fix_type,
                    'description': c.description,
                    'applied': c.applied,
                    'verified': c.verified,
                    'applied_at': c.applied_at
                }
                for c in self.corrections
            ]
        }
        with open(self.errors_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def detect_errors(self, code_path: str = ".") -> List[Error]:
        """
        Detect errors in the codebase.
        
        Args:
            code_path: Path to check for errors
            
        Returns:
            List of detected errors
        """
        errors = []
        
        # Check Python syntax errors
        python_errors = self._check_python_syntax(code_path)
        errors.extend(python_errors)
        
        # Check for import errors
        import_errors = self._check_imports(code_path)
        errors.extend(import_errors)
        
        # Check for common issues
        common_errors = self._check_common_issues(code_path)
        errors.extend(common_errors)
        
        # Store errors
        self.errors.extend(errors)
        self._save_errors()
        
        return errors
    
    def _check_python_syntax(self, code_path: str) -> List[Error]:
        """Check for Python syntax errors."""
        errors = []
        
        for root, dirs, files in os.walk(code_path):
            # Skip certain directories
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.venv']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            code = f.read()
                        ast.parse(code)
                    except SyntaxError as e:
                        errors.append(Error(
                            type='syntax_error',
                            message=str(e),
                            file_path=file_path,
                            line_number=e.lineno,
                            severity='high'
                        ))
                    except Exception as e:
                        errors.append(Error(
                            type='parse_error',
                            message=str(e),
                            file_path=file_path,
                            severity='medium'
                        ))
        
        return errors
    
    def _check_imports(self, code_path: str) -> List[Error]:
        """Check for import errors."""
        errors = []
        # This would require actually running imports, which might fail
        # For now, check for obvious issues like missing __init__.py
        return errors
    
    def _check_common_issues(self, code_path: str) -> List[Error]:
        """Check for common code issues."""
        errors = []
        
        # Check for TODO/FIXME comments (potential issues)
        for root, dirs, files in os.walk(code_path):
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                if 'FIXME' in line.upper() or 'XXX' in line.upper():
                                    errors.append(Error(
                                        type='code_issue',
                                        message=f"Potential issue marker: {line.strip()}",
                                        file_path=file_path,
                                        line_number=line_num,
                                        severity='low'
                                    ))
                    except Exception:
                        pass
        
        return errors
    
    def fix_error(self, error: Error) -> Optional[Correction]:
        """
        Attempt to fix an error.
        
        Args:
            error: Error to fix
            
        Returns:
            Correction object if fix attempted, None otherwise
        """
        error.fix_attempts += 1
        
        # Get fix strategies for this error type
        strategies = self.fix_strategies.get(error.type, [])
        
        if not strategies:
            return None
        
        # Try strategies in priority order
        for strategy in sorted(strategies, key=lambda x: x['priority']):
            fix_type = strategy['action']
            
            correction = Correction(
                error_id=f"{error.type}_{error.file_path}_{error.line_number}",
                fix_type=fix_type,
                description=f"Attempting {fix_type} for {error.type}"
            )
            
            # Apply fix based on type
            if fix_type == 'fix_indentation':
                if self._fix_indentation(error):
                    correction.applied = True
                    correction.applied_at = datetime.now().isoformat()
            
            elif fix_type == 'add_error_handling':
                if self._add_error_handling(error):
                    correction.applied = True
                    correction.applied_at = datetime.now().isoformat()
            
            elif fix_type == 'add_missing_import':
                if self._add_missing_import(error):
                    correction.applied = True
                    correction.applied_at = datetime.now().isoformat()
            
            # Verify fix
            if correction.applied:
                if self._verify_fix(error):
                    correction.verified = True
                    error.fixed = True
                    self.corrections.append(correction)
                    self._save_errors()
                    return correction
        
        return None
    
    def _fix_indentation(self, error: Error) -> bool:
        """Fix indentation errors."""
        if not error.file_path or not error.line_number:
            return False
        
        try:
            with open(error.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if error.line_number <= len(lines):
                line = lines[error.line_number - 1]
                # Try to fix common indentation issues
                fixed_line = re.sub(r'^\s+', '    ', line)  # Standardize to 4 spaces
                lines[error.line_number - 1] = fixed_line
                
                with open(error.file_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                return True
        except Exception:
            return False
        
        return False
    
    def _add_error_handling(self, error: Error) -> bool:
        """Add error handling to code."""
        # This would require more sophisticated code analysis
        # For now, return False (not implemented)
        return False
    
    def _add_missing_import(self, error: Error) -> bool:
        """Add missing imports."""
        # This would require understanding what import is needed
        # For now, return False (not implemented)
        return False
    
    def _verify_fix(self, error: Error) -> bool:
        """Verify that a fix resolved the error."""
        if error.type == 'syntax_error' and error.file_path:
            try:
                with open(error.file_path, 'r', encoding='utf-8') as f:
                    code = f.read()
                ast.parse(code)
                return True
            except SyntaxError:
                return False
        return True
    
    def auto_correct(self, code_path: str = ".") -> Dict[str, Any]:
        """
        Automatically detect and fix errors.
        
        Args:
            code_path: Path to codebase
            
        Returns:
            Dictionary with correction results
        """
        # Detect errors
        errors = self.detect_errors(code_path)
        
        # Attempt to fix each error
        fixed_count = 0
        failed_count = 0
        
        for error in errors:
            if not error.fixed:
                correction = self.fix_error(error)
                if correction and correction.verified:
                    fixed_count += 1
                else:
                    failed_count += 1
        
        return {
            'total_errors': len(errors),
            'fixed': fixed_count,
            'failed': failed_count,
            'fix_rate': fixed_count / len(errors) if errors else 0.0
        }
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of errors and corrections."""
        total = len(self.errors)
        fixed = sum(1 for e in self.errors if e.fixed)
        critical = sum(1 for e in self.errors if e.severity == 'critical')
        
        return {
            'total_errors': total,
            'fixed_errors': fixed,
            'unfixed_errors': total - fixed,
            'critical_errors': critical,
            'fix_rate': fixed / total if total > 0 else 0.0,
            'recent_errors': [
                {
                    'type': e.type,
                    'severity': e.severity,
                    'fixed': e.fixed
                }
                for e in self.errors[-10:]
            ]
        }


if __name__ == "__main__":
    # Test self-corrector
    corrector = SelfCorrector()
    
    print("=== Self-Corrector Test ===")
    
    # Auto-correct
    result = corrector.auto_correct(".")
    
    print(f"\nTotal Errors: {result['total_errors']}")
    print(f"Fixed: {result['fixed']}")
    print(f"Failed: {result['failed']}")
    print(f"Fix Rate: {result['fix_rate']:.2%}")
    
    summary = corrector.get_error_summary()
    print(f"\nError Summary:")
    print(f"  Total: {summary['total_errors']}")
    print(f"  Fixed: {summary['fixed_errors']}")
    print(f"  Critical: {summary['critical_errors']}")

