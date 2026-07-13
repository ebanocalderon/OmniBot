import sys

file_path = "/home/chatwoot/chatwoot/.env"
new_url = sys.argv[1]

with open(file_path, "r") as f:
    lines = f.readlines()

new_lines = []
found = False
for line in lines:
    if line.startswith("FRONTEND_URL="):
        new_lines.append(f"FRONTEND_URL={new_url}\n")
        found = True
    else:
        new_lines.append(line)

if not found:
    new_lines.append(f"FRONTEND_URL={new_url}\n")

with open(file_path, "w") as f:
    f.writelines(new_lines)

print("FRONTEND_URL updated successfully!")
