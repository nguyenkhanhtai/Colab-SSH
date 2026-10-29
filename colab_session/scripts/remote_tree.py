import json, os, sys

def human_size(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}" if unit != 'B' else f"{int(bytes_val)} B"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"

def scan_dir(path, current_depth, max_depth, max_per_branch, show_hidden):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"error": f"Path not found: {path}", "path": path, "name": os.path.basename(path) or path, "is_dir": False}

    if os.path.isfile(path):
        try:
            stat = os.stat(path)
            return {
                "name": os.path.basename(path) or path,
                "path": path,
                "is_dir": False,
                "size": stat.st_size,
                "size_human": human_size(stat.st_size),
            }
        except Exception as e:
            return {"name": os.path.basename(path) or path, "path": path, "is_dir": False, "error": str(e)}

    node = {
        "name": os.path.basename(path) or path,
        "path": path,
        "is_dir": True,
        "size": 0,
        "children": [],
        "total_items": 0,
        "shown_items": 0,
        "has_more": False,
        "remaining_count": 0,
    }

    if current_depth >= max_depth:
        return node

    try:
        entries = os.listdir(path)
    except Exception as e:
        node["error"] = str(e)
        return node

    if not show_hidden:
        entries = [e for e in entries if not e.startswith('.')]

    def sort_key(name):
        full = os.path.join(path, name)
        is_directory = os.path.isdir(full)
        return (0 if is_directory else 1, name.lower())

    entries.sort(key=sort_key)
    node["total_items"] = len(entries)

    shown_entries = entries[:max_per_branch]
    node["shown_items"] = len(shown_entries)
    if len(entries) > max_per_branch:
        node["has_more"] = True
        node["remaining_count"] = len(entries) - max_per_branch

    for name in shown_entries:
        child_path = os.path.join(path, name)
        try:
            if os.path.isdir(child_path):
                child_node = scan_dir(child_path, current_depth + 1, max_depth, max_per_branch, show_hidden)
                node["children"].append(child_node)
            else:
                stat = os.stat(child_path)
                node["children"].append({
                    "name": name,
                    "path": child_path,
                    "is_dir": False,
                    "size": stat.st_size,
                    "size_human": human_size(stat.st_size),
                })
        except Exception as e:
            node["children"].append({
                "name": name,
                "path": child_path,
                "error": str(e),
            })

    return node

if __name__ == "__main__":
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/content"
    max_d = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    max_branch = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    hidden = sys.argv[4].lower() in ("1", "true", "yes") if len(sys.argv) > 4 else False

    result = scan_dir(target_path, current_depth=0, max_depth=max_d, max_per_branch=max_branch, show_hidden=hidden)
    print(json.dumps(result))
