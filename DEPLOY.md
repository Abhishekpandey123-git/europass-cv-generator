# Putting the service on an AWS server

The scripts in `deploy/` do the work. You run three commands on the server;
everything else is automatic.

What you end up with:

```
client website ──https──▶ nginx (port 443) ──▶ the service (port 8000, local only)
staff browser  ──https──▶                                    │
                                                        data/cvs.db
```

---

## 1. Create the server

In the AWS console, **EC2 → Launch instance**:

| Setting | Choose |
|---|---|
| Name | `europass-cv` |
| Image (AMI) | **Ubuntu Server 24.04 LTS** |
| Instance type | **t3.small** (2 GB RAM). `t3.micro` works but PDF rendering is tight. |
| Key pair | Create one and download the `.pem` file. You need it to log in. |
| Network: allow SSH | Yes, and set **My IP**, not anywhere |
| Network: allow HTTP | Yes |
| Network: allow HTTPS | Yes |
| Storage | 20 GB gp3 |

Launch it, then copy the **Public IPv4 address**.

**Do not open port 8000** in the security group. The service listens only on
the machine itself; nginx is what the internet talks to.

### Elastic IP (recommended)

A stopped instance gets a new IP when it starts again, which would break the
client's integration. **EC2 → Elastic IPs → Allocate**, then **Associate** it
with the instance. Use that IP from here on.

---

## 2. Point a domain at it (recommended)

HTTPS needs a domain name. In the client's DNS settings, add an **A record**,
for example `cv.theirdomain.com` → the Elastic IP. Wait a few minutes, then
check from your PC:

```powershell
nslookup cv.theirdomain.com
```

Without a domain the service still runs, but only over plain HTTP, which means
student data and the API key travel unencrypted. That's fine for a demo, not
for real data.

---

## 3. Copy the project to the server

From PowerShell on your machine, in the folder holding `europass-cv-service`:

```powershell
# keep the key private, or ssh will refuse to use it
icacls "$HOME\Downloads\europass-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"

scp -i "$HOME\Downloads\europass-key.pem" -r europass-cv-service ubuntu@SERVER_IP:~/
```

Replace `SERVER_IP` and the key path with yours. If you have a `venv` folder
inside the project, delete it first: it's large and rebuilt on the server.

---

## 4. Run the setup script

```powershell
ssh -i "$HOME\Downloads\europass-key.pem" ubuntu@SERVER_IP
```

Then on the server:

```bash
cd ~/europass-cv-service
sudo bash deploy/setup.sh cv.theirdomain.com     # leave the domain off if you have none
```

It takes two to three minutes and does all of this:

- installs Python, nginx, and the Pango libraries WeasyPrint needs
- copies the app to `/opt/europass-cv` and builds its virtual environment
- creates `.env` with a **generated admin password and API key**
- registers a systemd service that starts on boot and restarts on crash
- configures nginx as the front door and turns on the firewall
- requests a free HTTPS certificate from Let's Encrypt (with a domain)

**At the end it prints the admin password and API key. Save them.** They're
also in `/opt/europass-cv/.env`, readable with
`sudo cat /opt/europass-cv/.env`.

---

## 5. Check it works

Open `https://cv.theirdomain.com` in a browser. You should get the staff login.
Sign in with the printed password.

Test the website API from your own machine:

```powershell
curl.exe -X POST https://cv.theirdomain.com/api/v1/cvs `
  -H "X-API-Key: THE_KEY" -H "Content-Type: application/json" `
  -d '{\"cv\":{\"personal\":{\"name\":\"Test Student\"}}}'
```

A JSON reply with an `id` means the client's developer can start integrating.
Send them `INTEGRATION.md`, the service address, and the API key (not by
public chat: use a password manager or an encrypted note).

---

## Day-to-day commands

Run these on the server over SSH.

| Task | Command |
|---|---|
| Is it running? | `systemctl status europass-cv` |
| Watch the log live | `journalctl -u europass-cv -f` |
| Restart | `sudo systemctl restart europass-cv` |
| Change a setting | `sudo nano /opt/europass-cv/.env` then restart |
| Deploy new code | copy the folder up again, then `sudo bash deploy/update.sh` |
| Back up now | `sudo bash deploy/backup.sh` |

**Turn on daily backups** (keeps 30 days in `/opt/europass-cv/backups`):

```bash
sudo cp deploy/backup.sh /etc/cron.daily/europass-cv-backup
sudo chmod +x /etc/cron.daily/europass-cv-backup
```

Copy a backup to your own machine from time to time; a backup on the same
server doesn't help if the server is lost:

```powershell
scp -i "$HOME\Downloads\europass-key.pem" ubuntu@SERVER_IP:/opt/europass-cv/backups/*.db .
```

---

## Security notes

- **The CVs hold students' personal data.** Use HTTPS, keep the admin password
  strong, and give each system its own API key so one can be revoked alone.
- **Keys live only in `.env`** on the server (permissions `600`). They are
  never in the code or in git.
- **SSH stays limited to your IP.** If your home IP changes, update the
  security group rule.
- **Apply updates monthly:** `sudo apt update && sudo apt upgrade`. Certbot
  renews the certificate by itself.
- Set a retention rule with the client (for example, delete CVs a year after
  the application) and delete old rows from the dashboard.

## If something goes wrong

**The site doesn't load at all:** check nginx is up (`systemctl status nginx`)
and that HTTP/HTTPS are allowed in the security group.

**502 Bad Gateway:** nginx is fine but the app isn't. Look at
`journalctl -u europass-cv -n 50`. A missing Python package or a bad `.env`
line is the usual cause.

**PDF fails with a `gobject`/`pango` error:** the Pango libraries are missing.
`sudo apt install libpango-1.0-0 libpangoft2-1.0-0`, then restart the service.

**certbot fails:** the domain isn't pointing at the server yet. Wait for DNS,
then run `sudo certbot --nginx -d cv.theirdomain.com`.

**Uploads of large PDFs fail:** raise `client_max_body_size` in
`/etc/nginx/sites-available/europass-cv`, then `sudo systemctl reload nginx`.

---

## Upgrading an existing install

This release changes the stored CV shape: the optional sections are typed now
instead of free-text `additional_sections`. Old records still load — the
importer fills the new keys and leaves anything it does not recognise in
`additional_sections` — but take a backup first.

```bash
systemctl cat europass-cv | grep -E 'WorkingDirectory|User'
APP=/path/from/WorkingDirectory

tar czf /root/europass-backup-$(date +%F-%H%M).tar.gz -C "$(dirname $APP)" "$(basename $APP)"

mkdir -p /tmp/new && unzip -q /root/europass-cv-production.zip -d /tmp/new
rsync -a --delete \
  --exclude '.env' --exclude 'data/' --exclude 'venv/' --exclude 'samples/reference/' \
  /tmp/new/europass-cv/ "$APP"/

"$APP/venv/bin/pip" install -r "$APP/requirements.txt"
```

Run the tests on the server before restarting — they take about a minute and
will catch a bad upgrade before any student sees it:

```bash
cd "$APP" && ./run_tests.sh
systemctl restart europass-cv
systemctl status europass-cv --no-pager
```

Rollback:

```bash
systemctl stop europass-cv
tar xzf /root/europass-backup-<stamp>.tar.gz -C "$(dirname $APP)"
systemctl start europass-cv
```

`samples/reference/` holds real student CVs used as test fixtures. It is
excluded from the sync above and from git; copy it across once, by hand, if you
want to run the tests on the server.
