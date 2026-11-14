"""Host-side installation. Secrets are fetched with the instance role."""

import glob
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

os.environ["AWS_PAGER"] = ""


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args, text=True)


def aws(*args):
    return json.loads(output(["aws", "--region", "us-east-2", "--no-cli-pager", *args]))


m = json.loads(Path("/opt/encuentrau/manifest.json").read_text())
volume = m["DataVolume"].replace("-", "")
paths = glob.glob("/dev/disk/by-id/*" + volume)
if len(paths) != 1:
    raise RuntimeError("Expected one attached data volume")
device = str(Path(paths[0]).resolve())
filesystem = output(["lsblk", "-no", "FSTYPE", device]).strip()
if not filesystem:
    run(["mkfs", "-t", "xfs", device], stdout=subprocess.DEVNULL)
elif filesystem != "xfs":
    raise RuntimeError("Unexpected data filesystem")
Path("/mnt/encuentrau").mkdir(exist_ok=True)
if subprocess.run(["mountpoint", "-q", "/mnt/encuentrau"]).returncode:
    run(["mount", device, "/mnt/encuentrau"])
uuid = output(["blkid", "-s", "UUID", "-o", "value", device]).strip()
fstab = Path("/etc/fstab")
if uuid not in fstab.read_text():
    with fstab.open("a") as f:
        f.write("\nUUID=" + uuid + " /mnt/encuentrau xfs defaults 0 2\n")
Path("/mnt/encuentrau/uploads").mkdir(exist_ok=True)
run(["chown", "10001:10001", "/mnt/encuentrau/uploads"])
Path("/etc/encuentrau").mkdir(mode=0o700, exist_ok=True)
run(
    [
        "curl",
        "-fsSL",
        "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
        "-o",
        "/etc/encuentrau/rds-ca.pem",
    ]
)
secret = json.loads(
    aws("secretsmanager", "get-secret-value", "--secret-id", "encuentrau/runtime")[
        "SecretString"
    ]
)
db = json.loads(
    aws("secretsmanager", "get-secret-value", "--secret-id", m["DbSecret"])[
        "SecretString"
    ]
)
base = {
    "AI_QUOTA_ENABLED": "false",
    "AI_QUOTA_USER_HOUR": "6",
    "AI_QUOTA_USER_DAY": "20",
    "AI_QUOTA_GLOBAL_DAY": "120",
    "AI_QUOTA_GLOBAL_MONTH": "1200",
    "AI_PRIMARY_PROVIDER": "openai",
    "AI_FALLBACK_PROVIDER": "gemini",
    "OPENAI_MODEL": "gpt-5.4",
    "GEMINI_MODEL": "gemini-3.5-flash-lite",
    "AI_TIMEOUT_SECONDS": "60",
    "CORS_ORIGINS": "https://" + m["Domain"],
    "EMAIL_VERIFICATION_REQUIRED": secret.get("EMAIL_VERIFICATION_REQUIRED", "false"),
    "EMAIL_SENDER": secret.get("EMAIL_SENDER", ""),
    "ADMIN_EMAIL": secret.get("ADMIN_EMAIL", "camila@example.com"),
    "EMAIL_AWS_REGION": "us-east-2",
    "EMAIL_DAILY_LIMIT": "40",
}
for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "JWT_SECRET_KEY"):
    base[key] = secret[key]


def dburl(user, password):
    return (
        "postgresql+psycopg://"
        + user
        + ":"
        + quote(password, safe="")
        + "@"
        + m["DbEndpoint"]
        + ":5432/encuentrau?sslmode=verify-full&sslrootcert=/certs/rds-ca.pem"
    )


def writeenv(values):
    p = Path("/etc/encuentrau/runtime.env")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for k, v in values.items():
            if "\n" in v or "\r" in v:
                raise RuntimeError("Invalid environment value")
            f.write(k + "=" + v + "\n")


base["DATABASE_URL"] = dburl(db["username"], db["password"])
writeenv(
    {
        **base,
        "DB_APP_PASSWORD": secret["DB_APP_PASSWORD"],
        "INITIAL_ADMIN_PASSWORD": secret["INITIAL_ADMIN_PASSWORD"],
    }
)
Path("deployment.env").write_text(
    "BACKEND_IMAGE=encuentrau-api:email-20261115-final\n"
    "WEB_IMAGE=encuentrau-web:email-20261115-final\nSITE_DOMAIN="
    + m["Domain"]
    + "\nRUNTIME_ENV_FILE=/etc/encuentrau/runtime.env\n"
    "UPLOADS_PATH=/mnt/encuentrau/uploads\n"
    "RDS_CA_FILE=/etc/encuentrau/rds-ca.pem\n"
)
compose = ["docker", "compose", "--env-file", "deployment.env"]
run(compose + ["run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"])
run(
    compose
    + [
        "run",
        "--rm",
        "--no-deps",
        "-e",
        "PYTHONPATH=/app",
        "-v",
        "/opt/encuentrau/init_database.py:/tmp/init_database.py:ro",
        "api",
        "python",
        "/tmp/init_database.py",
    ]
)
base["DATABASE_URL"] = dburl("euapp", secret["DB_APP_PASSWORD"])
writeenv(base)
run(compose + ["up", "-d", "--wait", "--wait-timeout", "180"])
run(["cp", "encuentrau.service", "/etc/systemd/system/encuentrau.service"])
run(["systemctl", "daemon-reload"])
run(["systemctl", "enable", "encuentrau"])
backup = Path("/usr/local/sbin/encuentrau-backup")
backup.write_text(
    "#!/bin/bash\nset -eu\nexport AWS_PAGER=\nmkdir -p "
    "/var/backups/encuentrau\ntar -czf "
    "/var/backups/encuentrau/photos.tar.gz -C /mnt/encuentrau "
    "uploads\naws s3 cp /var/backups/encuentrau/photos.tar.gz "
    "s3://"
    + m["Bucket"]
    + "/backups/photos-latest.tar.gz --region us-east-2 --only-show-errors\n"
)
backup.chmod(0o700)
Path("/etc/systemd/system/encuentrau-backup.service").write_text(
    "[Unit]\nDescription=EncuentraU private photo backup\n"
    "RequiresMountsFor=/mnt/encuentrau\n[Service]\nType=oneshot\n"
    "ExecStart=/usr/local/sbin/encuentrau-backup\n"
)
Path("/etc/systemd/system/encuentrau-backup.timer").write_text(
    "[Unit]\nDescription=Daily EncuentraU backup\n[Timer]\n"
    "OnCalendar=*-*-* 06:00:00\nPersistent=true\n[Install]\n"
    "WantedBy=timers.target\n"
)
run(["systemctl", "daemon-reload"])
run(["systemctl", "enable", "--now", "encuentrau-backup.timer"])
run(["/usr/local/sbin/encuentrau-backup"])
print("Application services started")
