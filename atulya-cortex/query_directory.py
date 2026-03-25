"""
Quick Directory Query Script

Simple command-line interface for querying the directory index.
Usage examples:
    python query_directory.py search brain
    python query_directory.py extension py
    python query_directory.py path utils
    python query_directory.py name blackbox
"""

import sys
import json
from utils.directory_index import DirectoryIndex


def main():
    if len(sys.argv) < 3:
        print("Usage: python query_directory.py <command> <query>")
        print("\nCommands:")
        print("  search <term>     - Search for term in file names and paths")
        print("  extension <ext>   - Find all files with extension (e.g., py, md)")
        print("  path <path>       - Find files containing path in their path")
        print("  name <name>       - Find files with name containing term")
        print("  dir <directory>   - List files in specific directory")
        print("  file <filename>   - Get full path for a specific file")
        print("\nExample: python query_directory.py search brain")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    query = sys.argv[2]
    
    # Load or build index
    indexer = DirectoryIndex(".")
    try:
        indexer.load_json("directory_index.json")
        print(f"Loaded index from directory_index.json")
    except FileNotFoundError:
        print("Index not found, building new index...")
        indexer.build_index()
        indexer.save_json("directory_index.json")
    
    # Execute command
    if command == "search":
        results = indexer.search(query)
        print(f"\nFound {results['count']} matches for '{query}':")
        if results['files']:
            print(f"\nFiles ({len(results['files'])}):")
            for f in results['files'][:20]:  # Show first 20
                print(f"  - {f['path']}")
            if len(results['files']) > 20:
                print(f"  ... and {len(results['files']) - 20} more")
        if results['directories']:
            print(f"\nDirectories ({len(results['directories'])}):")
            for d in results['directories'][:10]:
                print(f"  - {d}")
    
    elif command == "extension":
        files = indexer.find_by_extension(query)
        print(f"\nFound {len(files)} files with extension '{query}':")
        for f in files[:30]:
            print(f"  - {f}")
        if len(files) > 30:
            print(f"  ... and {len(files) - 30} more")
    
    elif command == "path":
        results = indexer.find_files(path_contains=query)
        print(f"\nFound {len(results)} files with path containing '{query}':")
        for f in results[:30]:
            print(f"  - {f['path']}")
        if len(results) > 30:
            print(f"  ... and {len(results) - 30} more")
    
    elif command == "name":
        results = indexer.find_files(name_pattern=query)
        print(f"\nFound {len(results)} files with name containing '{query}':")
        for f in results[:30]:
            print(f"  - {f['path']}")
        if len(results) > 30:
            print(f"  ... and {len(results) - 30} more")
    
    elif command == "dir":
        contents = indexer.list_directory(query)
        print(f"\nContents of '{query}':")
        if contents['files']:
            print(f"\nFiles ({len(contents['files'])}):")
            for f in contents['files']:
                print(f"  - {f}")
        if contents['subdirs']:
            print(f"\nSubdirectories ({len(contents['subdirs'])}):")
            for d in contents['subdirs']:
                print(f"  - {d}")
    
    elif command == "file":
        path = indexer.get_file_path(query)
        if path:
            print(f"\nFound: {path}")
        else:
            print(f"\nFile '{query}' not found")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

