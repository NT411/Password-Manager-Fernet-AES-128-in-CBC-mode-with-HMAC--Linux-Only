#!/usr/bin/env python3
import curses
import json
from pathlib import Path
import os
import secrets
import string
from dataclasses import dataclass
from cryptography.fernet import Fernet

USER = os.environ.get("SUDO_USER") or os.environ.get("USER", "")
VAULT_DIR = Path(f"/home/{USER}/mnt/usb_secure")
VAULT_FILE = VAULT_DIR / "vault.json"
KEY_FILE = VAULT_DIR / "vault.key"

# check USB + key file
if not VAULT_DIR.exists() or not KEY_FILE.exists():
    print("❌ Secure USB not mounted or missing key. Please run 'usbon'.")
    raise SystemExit(1)

# load encryption key
vault_key = KEY_FILE.read_bytes()
fernet = Fernet(vault_key)

# vault data
vault = {}
if VAULT_FILE.exists():
    vault = json.loads(fernet.decrypt(VAULT_FILE.read_bytes()).decode())

def save():
    data = json.dumps(vault, indent=2).encode()
    VAULT_FILE.write_bytes(fernet.encrypt(data))
    os.chmod(VAULT_FILE, 0o600)

# ---------------- Password generation ----------------

DEFAULT_SPECIAL = "!@#$%^&*()-_=+[]{}<>?/:;,."
_rng = secrets.SystemRandom()

@dataclass
class GenOptions:
    length: int = 16
    inc_upper: bool = True
    inc_lower: bool = True
    inc_num: bool = True
    inc_special: bool = True
    special_set: str = DEFAULT_SPECIAL
    enforce: bool = True

GEN_OPTS = GenOptions()

def _build_classes(o: GenOptions):
    classes = []
    if o.inc_upper:
        classes.append(string.ascii_uppercase)
    if o.inc_lower:
        classes.append(string.ascii_lowercase)
    if o.inc_num:
        classes.append(string.digits)
    if o.inc_special and o.special_set:
        classes.append(o.special_set)

    # If user turns everything off, default to all
    if not classes:
        classes = [string.ascii_uppercase, string.ascii_lowercase, string.digits, o.special_set]
    return classes

def generate_password(o: GenOptions) -> str:
    if o.length <= 0:
        raise ValueError("Length must be positive.")
    classes = _build_classes(o)
    charset = "".join(classes)

    if o.enforce and o.length < len(classes):
        raise ValueError(f"Length too small to enforce ({len(classes)} classes).")

    chars = []
    if o.enforce:
        for cls in classes:
            chars.append(_rng.choice(cls))
    for _ in range(o.length - len(chars)):
        chars.append(_rng.choice(charset))
    _rng.shuffle(chars)
    return "".join(chars)

def _masked_input(stdscr, y, x, prompt, allow_empty=False):
    """
    Reads input while masking with * (like a password field).
    """
    stdscr.addstr(y, x, prompt)
    stdscr.refresh()
    buf = []
    cx = x + len(prompt)

    while True:
        ch = stdscr.getch()
        if ch in (10, 13):  # Enter
            if allow_empty or buf:
                return "".join(buf)
        elif ch in (27,):  # ESC cancels -> return empty
            return ""
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
                cx -= 1
                stdscr.move(y, cx)
                stdscr.addch(" ")
                stdscr.move(y, cx)
                stdscr.refresh()
        elif 32 <= ch <= 126:  # printable ascii
            buf.append(chr(ch))
            stdscr.addch(y, cx, "*")
            cx += 1
            stdscr.refresh()

def _simple_input(stdscr, y, x, prompt, default=""):
    curses.echo()
    stdscr.addstr(y, x, prompt)
    if default:
        stdscr.addstr(y, x + len(prompt), default)
        stdscr.move(y, x + len(prompt) + len(default))
    s = stdscr.getstr().decode(errors="ignore").strip()
    curses.noecho()
    if not s and default:
        return default
    return s

def generator_tui(stdscr, initial: GenOptions) -> GenOptions:
    """
    Configure generator settings using terminal default colors.
    Enter toggles. Left/Right changes length when on Length.
    """
    o = GenOptions(**vars(initial))
    selected = 0
    msg = ""
    typed_len = ""

    def rows():
        return [
            ("Length", str(o.length), "←/→ adjust, type digits"),
            ("Uppercase (A-Z)", "ON" if o.inc_upper else "OFF", "Enter toggle"),
            ("Lowercase (a-z)", "ON" if o.inc_lower else "OFF", "Enter toggle"),
            ("Digits (0-9)", "ON" if o.inc_num else "OFF", "Enter toggle"),
            ("Special", "ON" if o.inc_special else "OFF", "Enter toggle"),
            ("Special set", o.special_set if o.inc_special else "(disabled)", "Enter edit"),
            ("Enforce 1/class", "ON" if o.enforce else "OFF", "Enter toggle"),
            ("Done", "", "Enter to continue"),
            ("Back", "", "Enter to cancel"),
        ]

    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        stdscr.addnstr(1, 2, "Password Generator Settings", w - 4)
        stdscr.addnstr(2, 2, "↑↓ move  ←→ length  Enter select  q back", w - 4)

        for i, (label, val, hint) in enumerate(rows()):
            y = 4 + i
            line = f"{label:<18} {val:<24} {hint}"
            if i == selected:
                stdscr.addnstr(y, 2, line, w - 4, curses.A_REVERSE)
            else:
                stdscr.addnstr(y, 2, line, w - 4)

        if msg:
            stdscr.addnstr(h - 2, 2, msg, w - 4)
        stdscr.refresh()

    def bump_length(delta):
        nonlocal msg, typed_len
        o.length = max(1, o.length + delta)
        typed_len = ""
        msg = f"Length set to {o.length}"

    while True:
        draw()
        ch = stdscr.getch()

        if ch in (ord("q"), ord("Q")):
            return initial

        if ch == curses.KEY_UP:
            selected = (selected - 1) % len(rows())
            typed_len = ""
        elif ch == curses.KEY_DOWN:
            selected = (selected + 1) % len(rows())
            typed_len = ""

        elif ch in (curses.KEY_LEFT, ord("-")) and selected == 0:
            bump_length(-1)
        elif ch in (curses.KEY_RIGHT, ord("+"), ord("=")) and selected == 0:
            bump_length(+1)

        elif selected == 0 and 48 <= ch <= 57:
            typed_len += chr(ch)
            try:
                v = int(typed_len)
                if v > 0:
                    o.length = v
                    msg = f"Length set to {o.length}"
            except ValueError:
                pass
        elif selected == 0 and ch in (curses.KEY_BACKSPACE, 127, 8):
            typed_len = typed_len[:-1]
            if typed_len:
                try:
                    o.length = max(1, int(typed_len))
                except ValueError:
                    pass
            msg = f"Length set to {o.length}"

        elif ch in (10, 13):  # Enter
            if selected == 1:
                o.inc_upper = not o.inc_upper
                msg = f"Uppercase: {'ON' if o.inc_upper else 'OFF'}"
            elif selected == 2:
                o.inc_lower = not o.inc_lower
                msg = f"Lowercase: {'ON' if o.inc_lower else 'OFF'}"
            elif selected == 3:
                o.inc_num = not o.inc_num
                msg = f"Digits: {'ON' if o.inc_num else 'OFF'}"
            elif selected == 4:
                o.inc_special = not o.inc_special
                msg = f"Special: {'ON' if o.inc_special else 'OFF'}"
            elif selected == 5 and o.inc_special:
                stdscr.clear()
                stdscr.addstr(0, 0, "Type allowed special chars (exactly). Empty = keep current.")
                stdscr.addstr(2, 0, f"Current: {o.special_set}")
                s = _simple_input(stdscr, 4, 0, "New: ")
                if s:
                    o.special_set = s
                    msg = f"Special set updated ({len(o.special_set)} chars)."
                else:
                    msg = "Special set unchanged."
            elif selected == 6:
                o.enforce = not o.enforce
                msg = f"Enforce: {'ON' if o.enforce else 'OFF'}"
            elif selected == 7:  # Done
                # validate
                try:
                    _ = generate_password(o)
                    return o
                except Exception as e:
                    msg = str(e)
            elif selected == 8:  # Back
                return initial

def generate_password_flow(stdscr) -> str:
    """
    1) Configure generator (optional)
    2) Show generated password + confirm (Use/Regenerate/Cancel)
    Returns password or "" if cancelled.
    """
    global GEN_OPTS
    GEN_OPTS = generator_tui(stdscr, GEN_OPTS)

    while True:
        try:
            pw = generate_password(GEN_OPTS)
        except Exception as e:
            stdscr.clear()
            stdscr.addstr(0, 0, f"❌ Generator error: {e}")
            stdscr.addstr(2, 0, "Press any key to go back...")
            stdscr.getch()
            return ""

        idx = 0
        options = ["Use this password", "Regenerate", "Cancel"]

        while True:
            stdscr.clear()
            stdscr.addstr(0, 0, "Generated password:")
            stdscr.addstr(2, 0, pw)
            stdscr.addstr(4, 0, "Choose:")
            for i, opt in enumerate(options):
                if i == idx:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(6 + i, 0, opt)
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(6 + i, 0, opt)

            key = stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(options)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(options)
            elif key in (10, 13):
                choice = options[idx]
                if choice == "Use this password":
                    return pw
                if choice == "Regenerate":
                    break
                return ""

# ---------------- Vault UI ----------------

def add_password(stdscr):
    stdscr.clear()
    name = _simple_input(stdscr, 0, 0, "Service name: ")
    if not name:
        return
    user = _simple_input(stdscr, 1, 0, "Username: ")

    # Password step: choose manual vs generated
    idx = 0
    options = ["Type password", "Generate secure password", "Back"]
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Service: {name}")
        stdscr.addstr(1, 0, f"Username: {user}")
        stdscr.addstr(3, 0, "Password:")
        for i, opt in enumerate(options):
            if i == idx:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(5 + i, 0, opt)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(5 + i, 0, opt)

        key = stdscr.getch()
        if key == curses.KEY_UP:
            idx = (idx - 1) % len(options)
        elif key == curses.KEY_DOWN:
            idx = (idx + 1) % len(options)
        elif key in (10, 13):
            choice = options[idx]
            if choice == "Back":
                return
            if choice == "Type password":
                stdscr.clear()
                stdscr.addstr(0, 0, f"Service: {name}")
                stdscr.addstr(1, 0, f"Username: {user}")
                pwd = _masked_input(stdscr, 3, 0, "Password (ESC cancels): ")
                if not pwd:
                    continue
            else:
                pwd = generate_password_flow(stdscr)
                if not pwd:
                    continue

            vault[name] = {"username": user, "password": pwd}
            save()
            stdscr.clear()
            stdscr.addstr(0, 0, "✅ Saved!")
            stdscr.addstr(2, 0, "Press any key...")
            stdscr.getch()
            return

def view_details(stdscr, service):
    stdscr.clear()
    u, p = vault[service]["username"], vault[service]["password"]
    stdscr.addstr(0,0,f"Service:  {service}")
    stdscr.addstr(1,0,f"Username: {u}")
    stdscr.addstr(2,0,f"Password: {p}")
    stdscr.addstr(4,0,"(Press any key to go back)")
    stdscr.getch()

def edit_details(stdscr, service):
    stdscr.clear()
    old = vault[service]
    newname = _simple_input(stdscr, 0, 0, f"Edit Service (old: {service})", default="")
    if not newname:
        newname = service
    newuser = _simple_input(stdscr, 1, 0, "New username: ", default=old["username"])

    # Password choice (manual vs generate)
    idx = 0
    options = ["Keep current password", "Type new password", "Generate new password", "Cancel"]
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Service:  {service} -> {newname}")
        stdscr.addstr(1, 0, f"Username: {newuser}")
        stdscr.addstr(3, 0, "Password action:")
        for i, opt in enumerate(options):
            if i == idx:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(5 + i, 0, opt)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(5 + i, 0, opt)

        key = stdscr.getch()
        if key == curses.KEY_UP:
            idx = (idx - 1) % len(options)
        elif key == curses.KEY_DOWN:
            idx = (idx + 1) % len(options)
        elif key in (10, 13):
            choice = options[idx]
            if choice == "Cancel":
                return
            if choice == "Keep current password":
                newpwd = old["password"]
            elif choice == "Type new password":
                stdscr.clear()
                newpwd = _masked_input(stdscr, 0, 0, "New password (ESC cancels): ")
                if not newpwd:
                    continue
            else:
                newpwd = generate_password_flow(stdscr)
                if not newpwd:
                    continue

            # update vault
            if newname != service:
                del vault[service]
            vault[newname] = {"username": newuser, "password": newpwd}
            save()

            stdscr.clear()
            stdscr.addstr(0, 0, "✅ Updated! Press any key...")
            stdscr.getch()
            return

def password_menu(stdscr, service):
    idx = 0
    options = ["View details","Edit details","Delete","Back"]
    while True:
        stdscr.clear()
        stdscr.addstr(0,0,f"Service: {service}")
        for i,opt in enumerate(options):
            if i==idx:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(i+2,0,opt)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(i+2,0,opt)
        key = stdscr.getch()
        if key == curses.KEY_UP: idx = (idx-1) % len(options)
        elif key == curses.KEY_DOWN: idx = (idx+1) % len(options)
        elif key in (curses.KEY_ENTER,10,13):
            if options[idx]=="View details":
                view_details(stdscr, service)
            elif options[idx]=="Edit details":
                edit_details(stdscr, service)
                return
            elif options[idx]=="Delete":
                del vault[service]
                save()
                return
            elif options[idx]=="Back":
                return

def menu(stdscr):
    curses.curs_set(0)
    idx = 0
    while True:
        stdscr.clear()
        options = ["Add password"] + list(vault.keys()) + ["Quit"]
        stdscr.addstr(0,0,"Password Manager")
        for i,opt in enumerate(options):
            if i==idx:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(i+2,0,opt)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(i+2,0,opt)
        key = stdscr.getch()
        if key == curses.KEY_UP: idx = (idx-1) % len(options)
        elif key == curses.KEY_DOWN: idx = (idx+1) % len(options)
        elif key in (curses.KEY_ENTER,10,13):
            choice = options[idx]
            if choice=="Add password":
                add_password(stdscr)
            elif choice=="Quit":
                break
            else:
                password_menu(stdscr, choice)

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    menu(stdscr)

if __name__=="__main__":
    curses.wrapper(main)
