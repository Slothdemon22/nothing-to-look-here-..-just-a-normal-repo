# Cookie-only Flex sniper (VPS / SSH, no browser)

No Chrome. No captcha. No password. You SSH in, drop a live cookie, start the script.

```bash
cd ~/flex/server
python3 flex_server.py 23L-0700 --cookie cookie.txt --new dl -p 3
```

Keep it running with tmux:

```bash
tmux new -s flex
python3 flex_server.py 23L-0700 --cookie cookie.txt --new dl -p 3
# Ctrl+B then D to detach
tmux attach -t flex
```

## Cookie file

One line, session value only. From Chrome on a machine that *can* log in:

```
theLongSessionIdHere
```

Save as `server/cookie.txt` (or `cookie_23L0700.txt`). If Flex dumps you to `/Login`, you get mail **SESSION expired** and the script **exits**. SSH in, paste a fresh cookie, start again.

## Arguments

| Arg | Default | Meaning |
|---|---|---|
| `ROLL` | required | `23L-0700` |
| shorts | with `--new`: only what you type | `dl` `ds` `se` `bi` `wp` |
| `--cookie` | `cookie_<roll>.txt` | file path or raw session id |
| `--new` | off | unknown first-section electives first, then your shorts |
| `-p` | `4` | poll seconds |
| `--section` | `BCS-7A` | preferred section if open |
| `-m` | from `config.py` | alert inbox |

Examples:

```bash
python3 flex_server.py 23L-0700 --cookie cookie.txt --new dl -p 3
python3 flex_server.py 23L-0700 --cookie 'rawSessionId' --new
python3 flex_server.py 23L-0704 --cookie cookie_23L0704.txt dl ds
```

## Mail (Resend → l230625@lhr.nu.edu.pk)

- STARTED
- STARTED health / HEALTH running (hourly)
- NEW elective
- REGISTERED
- DROPPED
- DROP to enroll (hourly if holding a course)
- **SESSION expired** (cookie dead — script stops)
- ERROR crash / register fail

## Always-on SSH (VPS)

This folder is meant for a cheap cloud VM with a **public IP**. Then from any terminal:

```bash
ssh ubuntu@YOUR_VPS_IP
```

No Tailscale app. AWS Lightsail / Hetzner / DigitalOcean all work; they usually need a card. A tiny Ubuntu box is enough (no GPU, no Chrome).

On the VPS:

```bash
sudo apt update
sudo apt install -y python3 tmux
# copy this server/ folder
cd flex/server
# paste cookie.txt
tmux new -s flex
python3 flex_server.py 23L-0700 --cookie cookie.txt --new dl -p 3
```

Do **not** run `sniper/flex_reg_loop.py` on the VPS — that one needs Chrome + captcha.
