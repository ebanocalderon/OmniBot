import sys

file_path = "/home/chatwoot/chatwoot/.env"

with open(file_path, "r") as f:
    lines = f.readlines()

new_lines = []
ssrf_found = False
safe_fetch_found = False

for line in lines:
    clean = line.strip()
    if clean.startswith("ENABLE_SSRF_PREVENTION=") or clean.startswith("# ENABLE_SSRF_PREVENTION="):
        new_lines.append("ENABLE_SSRF_PREVENTION=false\n")
        ssrf_found = True
    elif clean.startswith("SAFE_FETCH_ALLOW_PRIVATE_NETWORK=") or clean.startswith("# SAFE_FETCH_ALLOW_PRIVATE_NETWORK="):
        new_lines.append("SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true\n")
        safe_fetch_found = True
    else:
        new_lines.append(line)

if not ssrf_found:
    new_lines.append("ENABLE_SSRF_PREVENTION=false\n")
if not safe_fetch_found:
    new_lines.append("SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true\n")

with open(file_path, "w") as f:
    f.writelines(new_lines)

print("SSRF prevention disabled and private network webhooks allowed successfully!")
