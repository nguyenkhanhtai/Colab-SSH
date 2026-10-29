import json
from pathlib import Path

drive_candidates = list(Path('/content').glob('**/MyDrive'))
if not drive_candidates:
    raise RuntimeError("Google Drive is not mounted in this session.")

my_drive = drive_candidates[0]
candidate_dirs = [
    my_drive / 'Colab-Backups',
    my_drive / 'colab-backups',
    my_drive / 'colab_backups',
]
items = []
seen_keys = set()
for backups_dir in candidate_dirs:
    if backups_dir.is_dir():
        for meta_file in sorted(backups_dir.glob('*.json'), reverse=True):
            try:
                data = json.loads(meta_file.read_text())
                k = data.get('key')
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    items.append(data)
            except Exception:
                pass

print(json.dumps({"status": "ok", "backups": items}))

