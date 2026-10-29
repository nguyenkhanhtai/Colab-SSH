import glob
import os
import sys
import tarfile

base = sys.argv[1]
patterns = sys.argv[2:]

if os.path.exists(base):
    os.chdir(base)
else:
    sys.stderr.write("BASE_DIR_NOT_FOUND\n")
    sys.exit(1)

found = []
for p in patterns:
    p = p.strip()
    if not p:
        continue
    matches = glob.glob(p, recursive=True)
    if matches:
        found.extend(matches)
    elif os.path.exists(p):
        found.append(p)

seen = set()
unique = []
for f in found:
    if f not in seen:
        seen.add(f)
        unique.append(f)

if not unique:
    sys.stderr.write("NO_MATCH\n")
    sys.exit(0)

with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as tar:
    for item in unique:
        tar.add(item)

sys.stderr.write("FOUND:" + ",".join(unique) + "\n")

