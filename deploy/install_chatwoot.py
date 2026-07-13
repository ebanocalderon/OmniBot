import subprocess
import sys
import time

def main():
    cmd = ["sudo", "-S", "./install.sh", "--install"]
    print("Starting Chatwoot installation wrapper script (with timing-based inputs)...")
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # 1. Send sudo password
    print("Sending sudo password...")
    proc.stdin.write("Mangudeplatano1!\n")
    proc.stdin.flush()

    # 2. Wait 6 seconds for the script to load and reach the domain prompt
    print("Waiting 6 seconds for domain prompt...")
    time.sleep(6)

    # 3. Send "no" to the domain prompt
    print("Sending 'no' to domain prompt...")
    proc.stdin.write("no\n")
    proc.stdin.flush()

    # 4. Wait 3 seconds for the Postgres/Redis prompt to appear
    print("Waiting 3 seconds for Postgres/Redis prompt...")
    time.sleep(3)

    # 5. Send "yes" to the Postgres/Redis prompt
    print("Sending 'yes' to Postgres/Redis prompt...")
    proc.stdin.write("yes\n")
    proc.stdin.flush()

    print("Prompts answered. Streaming output from installer...")

    # 6. Stream the rest of the output
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()

    proc.wait()
    print(f"\nInstallation wrapper finished with exit code {proc.returncode}")
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()
