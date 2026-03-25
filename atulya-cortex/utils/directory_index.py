"""
Directory Index Utility

Provides queryable directory structure indexing and search capabilities
for agents to understand and navigate the codebase file paths.
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime


class DirectoryIndex:
    """
    Queryable directory structure index for the codebase.
    
    Generates and maintains a searchable index of all files and directories,
    allowing agents to quickly find files by name, extension, path pattern, etc.
    """
    
    def __init__(self, root_path: str = "."):
        """
        Initialize directory index.
        
        Args:
            root_path: Root directory to index (default: current directory)
        """
        self.root_path = Path(root_path).resolve()
        self.index: Dict[str, Dict] = {}
        self.file_index: Dict[str, List[str]] = {}
        self.extension_index: Dict[str, List[str]] = {}
        
    def build_index(self, exclude_patterns: Optional[List[str]] = None) -> Dict:
        """
        Build complete directory index.
        
        Args:
            exclude_patterns: List of patterns to exclude (e.g., ['__pycache__', '*.pyc'])
            
        Returns:
            Dictionary containing full directory structure
        """
        if exclude_patterns is None:
            exclude_patterns = ['__pycache__', '*.pyc', '*.pyo', '.git', '.vscode', '.idea']
        
        exclude_set = set(exclude_patterns)
        structure = {
            'root': str(self.root_path),
            'generated_at': datetime.now().isoformat(),
            'files': [],
            'directories': [],
            'by_extension': {},
            'by_directory': {}
        }
        
        # Walk through directory tree
        for root, dirs, files in os.walk(self.root_path):
            # Filter excluded directories
            dirs[:] = [d for d in dirs if not any(
                pattern in d or d.endswith(pattern.replace('*', '')) 
                for pattern in exclude_set
            )]
            
            rel_root = os.path.relpath(root, self.root_path)
            if rel_root == '.':
                rel_root = ''
            
            # Process directories
            for dir_name in dirs:
                dir_path = os.path.join(rel_root, dir_name) if rel_root else dir_name
                structure['directories'].append(dir_path)
                
                if rel_root not in structure['by_directory']:
                    structure['by_directory'][rel_root] = {'files': [], 'subdirs': []}
                structure['by_directory'][rel_root]['subdirs'].append(dir_name)
            
            # Process files
            for file_name in files:
                # Skip excluded files
                if any(file_name.endswith(pattern.replace('*', '')) for pattern in exclude_set):
                    continue
                
                file_path = os.path.join(rel_root, file_name) if rel_root else file_name
                full_path = os.path.join(root, file_name)
                
                file_info = {
                    'name': file_name,
                    'path': file_path.replace('\\', '/'),  # Normalize path separators
                    'full_path': str(full_path),
                    'extension': os.path.splitext(file_name)[1] or 'no_extension',
                    'directory': rel_root.replace('\\', '/') if rel_root else '.',
                    'size': os.path.getsize(full_path) if os.path.exists(full_path) else 0
                }
                
                structure['files'].append(file_info)
                
                # Index by extension
                ext = file_info['extension']
                if ext not in structure['by_extension']:
                    structure['by_extension'][ext] = []
                structure['by_extension'][ext].append(file_info['path'])
                
                # Index by directory
                dir_key = rel_root if rel_root else '.'
                if dir_key not in structure['by_directory']:
                    structure['by_directory'][dir_key] = {'files': [], 'subdirs': []}
                structure['by_directory'][dir_key]['files'].append(file_name)
        
        self.index = structure
        return structure
    
    def save_json(self, output_file: str = "directory_index.json") -> str:
        """
        Save index to JSON file.
        
        Args:
            output_file: Output file path
            
        Returns:
            Path to saved file
        """
        if not self.index:
            self.build_index()
        
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)
        
        return str(output_path)
    
    def load_json(self, input_file: str = "directory_index.json") -> Dict:
        """
        Load index from JSON file.
        
        Args:
            input_file: Input file path
            
        Returns:
            Loaded index dictionary
        """
        with open(input_file, 'r', encoding='utf-8') as f:
            self.index = json.load(f)
        return self.index
    
    def find_files(self, 
                   name_pattern: Optional[str] = None,
                   extension: Optional[str] = None,
                   path_contains: Optional[str] = None,
                   directory: Optional[str] = None) -> List[Dict]:
        """
        Query files by various criteria.
        
        Args:
            name_pattern: Search for files containing this pattern in name
            extension: Filter by file extension (e.g., '.py', '.md')
            path_contains: Filter by path containing this string
            directory: Filter by directory path
            
        Returns:
            List of matching file dictionaries
        """
        if not self.index:
            self.build_index()
        
        results = self.index['files'].copy()
        
        # Filter by name pattern
        if name_pattern:
            results = [f for f in results if name_pattern.lower() in f['name'].lower()]
        
        # Filter by extension
        if extension:
            if not extension.startswith('.'):
                extension = '.' + extension
            results = [f for f in results if f['extension'] == extension]
        
        # Filter by path contains
        if path_contains:
            results = [f for f in results if path_contains.lower() in f['path'].lower()]
        
        # Filter by directory
        if directory:
            results = [f for f in results if directory.replace('\\', '/') in f['directory']]
        
        return results
    
    def find_by_extension(self, extension: str) -> List[str]:
        """
        Find all files with given extension.
        
        Args:
            extension: File extension (e.g., 'py', '.py', 'md')
            
        Returns:
            List of file paths
        """
        if not self.index:
            self.build_index()
        
        if not extension.startswith('.'):
            extension = '.' + extension
        
        return self.index['by_extension'].get(extension, [])
    
    def list_directory(self, directory: str = '.') -> Dict:
        """
        List contents of a specific directory.
        
        Args:
            directory: Directory path (relative to root)
            
        Returns:
            Dictionary with 'files' and 'subdirs' lists
        """
        if not self.index:
            self.build_index()
        
        dir_key = directory.replace('\\', '/')
        return self.index['by_directory'].get(dir_key, {'files': [], 'subdirs': []})
    
    def get_file_path(self, filename: str) -> Optional[str]:
        """
        Get full path for a file by name.
        
        Args:
            filename: Name of the file to find
            
        Returns:
            Full path if found, None otherwise
        """
        if not self.index:
            self.build_index()
        
        matches = [f for f in self.index['files'] if f['name'] == filename]
        if matches:
            return matches[0]['path']
        return None
    
    def search(self, query: str) -> Dict:
        """
        General search across all file names and paths.
        
        Args:
            query: Search query string
            
        Returns:
            Dictionary with 'files' and 'directories' matching the query
        """
        if not self.index:
            self.build_index()
        
        query_lower = query.lower()
        
        matching_files = [
            f for f in self.index['files']
            if query_lower in f['name'].lower() or query_lower in f['path'].lower()
        ]
        
        matching_dirs = [
            d for d in self.index['directories']
            if query_lower in d.lower()
        ]
        
        return {
            'query': query,
            'files': matching_files,
            'directories': matching_dirs,
            'count': len(matching_files) + len(matching_dirs)
        }


def generate_index(root_path: str = ".", 
                   output_file: str = "directory_index.json",
                   exclude_patterns: Optional[List[str]] = None) -> str:
    """
    Convenience function to generate and save directory index.
    
    Args:
        root_path: Root directory to index
        output_file: Output JSON file path
        exclude_patterns: Patterns to exclude from index
        
    Returns:
        Path to generated index file
    """
    indexer = DirectoryIndex(root_path)
    indexer.build_index(exclude_patterns)
    return indexer.save_json(output_file)


if __name__ == "__main__":
    # Generate index for current directory
    print("Building directory index...")
    indexer = DirectoryIndex(".")
    indexer.build_index()
    
    output_file = indexer.save_json("directory_index.json")
    print(f"Index saved to: {output_file}")
    print(f"Total files indexed: {len(indexer.index['files'])}")
    print(f"Total directories indexed: {len(indexer.index['directories'])}")
    
    # Example queries
    print("\n--- Example Queries ---")
    print("\n1. Find all Python files:")
    py_files = indexer.find_by_extension('py')
    print(f"   Found {len(py_files)} Python files")
    if py_files:
        print(f"   Example: {py_files[0]}")
    
    print("\n2. Search for 'brain':")
    brain_results = indexer.search('brain')
    print(f"   Found {brain_results['count']} matches")
    if brain_results['files']:
        print(f"   Example file: {brain_results['files'][0]['path']}")
    
    print("\n3. Find files in 'utils' directory:")
    utils_files = indexer.find_files(directory='utils')
    print(f"   Found {len(utils_files)} files")
    for f in utils_files[:5]:
        print(f"   - {f['path']}")

