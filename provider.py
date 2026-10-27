"""IPMI integration for Hisho (see addon.yaml). Runs inside Core; needs ipmitool there.

What it reads and does follows the Home Assistant IPMI integration by Adrian Teodorescu
(github.com/ateodorescu/home-assistant-ipmi, MIT): power state, the BMC's sensors (temperature,
fan, voltage, power, current) with their status, and power on / soft shutdown / off / cycle / reset.
No code is copied from it; this calls ipmitool directly.
"""
from __future__ import annotations

from typing import Any

VERBS = {"on": "power on", "soft": "power soft", "off": "power off", "cycle": "power cycle",
         "reset": "power reset", "status": "power status", "sensors": "sdr elist full", "info": "mc info"}
#: ipmitool sdr status codes -> how bad. ok = fine; nc = non-critical; cr = critical; nr = non-recoverable;
#: the l/u prefixed forms (lnr, ucr...) say which threshold (lower/upper) was crossed.
BAD = {"cr": "critical", "nr": "non-recoverable", "nc": "warning",
       "lcr": "critical (low)", "ucr": "critical (high)", "lnr": "non-recoverable (low)",
       "unr": "non-recoverable (high)", "lnc": "warning (low)", "unc": "warning (high)",
       "stopped": "not spinning (no fan fitted?)"}
CRITICAL = {"cr", "nr", "lcr", "ucr", "lnr", "unr"}
WARNING = {"nc", "lnc", "unc", "stopped"}
UNITS = [("degrees c", "Temperatures"), ("rpm", "Fans"), ("volts", "Voltages"), ("watts", "Power"),
         ("amps", "Current")]


class _Resolver:
    def __init__(self, ctx: Any) -> None:
        self.resolve = ctx.secret


def _ipmi(entry: dict[str, Any], ctx: Any, verb: str, timeout: int = 12) -> dict[str, Any]:
    from hisho.power import PowerExecutor
    return PowerExecutor(resolver=_Resolver(ctx), timeout=timeout).run_ipmi(
        {"bmc_ip": entry["address"], "username": entry.get("user"),
         # a typed user name wins; user_ref is only for a user name kept as a secret
         "user_ref": None if entry.get("user") else entry.get("user_ref"),
         "password_ref": entry["password"], "interface": entry.get("interface") or "lanplus",
         "cipher": entry.get("cipher")}, VERBS[verb])


def _plain(exc: Exception) -> str:
    missing = str(exc).rsplit("missing environment secret:", 1)
    if len(missing) == 2:
        return (f"Hisho can't find the secret {missing[1].strip()} on the Core machine. Type the password in "
                "this machine's form again, or put it in Bitwarden Secrets Manager.")
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def _why(stderr: str) -> str:
    low = stderr.lower()
    if "password" in low or "authentication" in low or "rakp" in low or "unauthorized" in low or "invalid user" in low:
        return "the BMC refused the user name or password"
    if "timeout" in low or "no route" in low:
        return "the BMC does not answer on the network (address, cable, or BMC switched off?)"
    if "unable to establish" in low:
        return ("the BMC would not open a session: usually a wrong user name or password, "
                "otherwise it is not reachable")
    if "cipher" in low:
        return "the BMC refused the connection settings (try interface lan, or another cipher)"
    return stderr[:160] or "no answer"


def _state(entry: dict[str, Any], ctx: Any) -> tuple[str, str]:
    try:
        res = _ipmi(entry, ctx, "status")
    except Exception as exc:  # noqa: BLE001
        return "unknown", _plain(exc)
    if not res.get("ok"):
        return "unknown", _why(str(res.get("stderr") or ""))
    return ("on" if "is on" in str(res.get("stdout")).lower() else "off"), str(res.get("stdout"))


def parse_sdr(text: str) -> list[dict[str, Any]]:
    """``ipmitool sdr elist full`` lines -> readings. ``CPU1 Temp | 01h | ok | 3.1 | 45 degrees C``."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[0]:
            continue
        name, status, reading = parts[0], parts[2].lower(), parts[4]
        if status == "ns" or reading.lower() in ("no reading", "disabled", ""):
            continue
        group = next((g for unit, g in UNITS if unit in reading.lower()), "Other")
        if group == "Fans" and status in CRITICAL and reading.split()[0] in ("0", "0.0"):
            # 0 RPM below the lower threshold is how these boards report an empty fan header
            # as often as a dead fan: show it, don't page about it.
            status = "stopped"
        out.append({"name": name, "status": status, "reading": reading, "group": group})
    return out


def _sensors(entry: dict[str, Any], ctx: Any) -> tuple[list[dict[str, Any]], str | None]:
    if entry.get("power_only"):
        return [], None
    try:
        res = _ipmi(entry, ctx, "sensors", timeout=40)
    except Exception as exc:  # noqa: BLE001
        return [], _plain(exc)
    if not res.get("ok"):
        return [], _why(str(res.get("stderr") or ""))
    ignore = {n.strip().lower() for n in str(entry.get("ignore") or "").split(",") if n.strip()}
    return [r for r in parse_sdr(str(res.get("stdout") or "")) if r["name"].lower() not in ignore], None


def summary(entries: dict[str, dict[str, Any]], ctx: Any) -> dict[str, Any]:
    on, problems = 0, []
    for name, entry in entries.items():
        state, detail = _state(entry, ctx)
        if state == "unknown":
            problems.append({"entry": name, "severity": "warn", "title": f"Can't reach {name}'s BMC",
                             "detail": f"{entry['address']}: {detail}."})
            continue
        on += state == "on"
        if state == "on":
            readings, _ = _sensors(entry, ctx)
            for r in readings:
                if r["status"] in CRITICAL:
                    problems.append({"entry": name, "severity": "critical",
                                     "title": f"{name}: {r['name']} is {BAD[r['status']]}",
                                     "detail": f"It reads {r['reading']}. Check the machine."})
    reachable = len(entries) - sum(1 for p in problems if p["title"].startswith("Can't reach"))
    return {"state": "down" if any(p["severity"] == "critical" for p in problems) else "warn" if problems else "ok",
            "headline": f"{len(entries)} machine{'s' * (len(entries) != 1)} · {on} on"
                        + (f" · {len(entries) - reachable} not answering" if reachable < len(entries) else ""),
            "problems": problems}


def _power_actions(name: str, state: str) -> list[dict[str, Any]]:
    if state == "off":
        return [{"id": "on", "label": "power on", "confirm": f"Power on {name}?"}]
    if state != "on":
        return []
    return [{"id": "soft", "label": "shut down", "danger": True, "confirm": f"Shut {name} down gracefully?"},
            {"id": "cycle", "label": "power cycle", "danger": True,
             "confirm": f"Power-cycle {name}? It is switched off and on again; unsaved work is lost."},
            {"id": "reset", "label": "reset", "danger": True,
             "confirm": f"Hard-reset {name}? Like pressing its reset button; unsaved work is lost."},
            {"id": "off", "label": "force off", "danger": True,
             "confirm": f"Cut power to {name} right now? Unsaved work on it is lost."}]


def details(entries: dict[str, dict[str, Any]], ctx: Any) -> list[dict[str, Any]]:
    sections = []
    for name, entry in entries.items():
        state, detail = _state(entry, ctx)
        facts = [f"BMC {entry['address']} ({entry.get('interface') or 'lanplus'})"]
        items = [{"id": "power", "name": f"Power: {state}", "facts": [detail],
                  "state": {"on": "up", "off": "off"}.get(state, "down"), "actions": _power_actions(name, state)}]
        if state == "on" or state == "off":
            readings, err = _sensors(entry, ctx)
            if err:
                facts.append(f"sensors: {err}")
            groups: dict[str, list[dict[str, Any]]] = {}
            for r in readings:
                groups.setdefault(r["group"], []).append(r)
            for group, rows in groups.items():
                worst = next((r for r in rows if r["status"] in CRITICAL), None) or \
                    next((r for r in rows if r["status"] in WARNING), None)
                items.append({"id": group.lower(), "name": f"{group} ({len(rows)})",
                              "state": "down" if worst and worst["status"] in CRITICAL else "warn" if worst else "up",
                              "facts": [f"{worst['name']} {worst['reading']} ({BAD[worst['status']]})" if worst
                                        else "all ok"]
                                       + [f"{r['name']}: {r['reading']}"
                                          + ("" if r["status"] == "ok" else f" ({BAD.get(r['status'], r['status'])})")
                                          for r in rows],
                              "actions": []})
        if entry.get("note"):
            facts.append(entry["note"])
        sections.append({"title": name, "entry": name, "state": "ok" if state != "unknown" else "down",
                         "facts": facts, "items": items})
    return sections


def test(entry: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Connection test for the page's Test button: power state, then the BMC's own info."""
    state, detail = _state(entry, ctx)
    if state == "unknown":
        return {"ok": False, "error": f"{entry.get('address')}: {detail}"}
    info = ""
    try:
        res = _ipmi(entry, ctx, "info")
        if res.get("ok"):
            lines = dict(l.split(":", 1) for l in str(res["stdout"]).splitlines() if ":" in l)
            info = " · ".join(f"{k.strip()} {lines[k].strip()}" for k in lines
                              if k.strip() in ("Product Name", "Firmware Revision"))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "message": f"Connected: power is {state}" + (f" · {info}" if info else "")}


def act(entries: dict[str, dict[str, Any]], ctx: Any, entry: str, item: str, action: str) -> dict[str, Any]:
    if action not in ("on", "soft", "off", "cycle", "reset"):
        return {"ok": False, "error": f"unknown action {action}"}
    if entry == ctx.fleet.core_host and action != "on":
        return {"ok": False, "error": f"{entry} runs Hisho's Core; it is never powered off from here"}
    res = _ipmi(entries[entry], ctx, action)
    return {"ok": bool(res.get("ok")), "message": res.get("stdout") or f"{action} sent to {entry}",
            "error": None if res.get("ok") else _why(str(res.get("stderr") or ""))}
