"""IPMI add-on tests. Run with Hisho's venv at the repository's top:
~/code/hisho/.venv/bin/python -m pytest -q"""
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from hisho import addon_store, addons
from hisho.addon_testing import AUTH, TOKEN, Recorder

HERE = Path(__file__).resolve().parents[1]


def ctx_for(addon):
    return addons.Context(addon, resolve=lambda name: f"value-of-{name}")


def test_manifest_is_valid_and_readme_matches(addon):
    assert addons.validate_manifest(addon.manifest) == []
    assert addon_store.readme_problems(HERE) == []


def test_the_ipmi_integration_reads_power_and_guards_core(fleet, monkeypatch):
    ip = addons.get("ipmi")
    addons.set_entry(ip, "big-box", {"address": "10.0.0.5", "user": "ADMIN", "password": "HISHO_BB_PASS"})
    addons.set_entry(ip, "kihon", {"address": "10.0.0.6", "user": "ADMIN", "password": "HISHO_K_PASS"})
    calls = []

    def run_ipmi(self, ipmi, verb):
        calls.append((ipmi["bmc_ip"], verb))
        return {"ok": True, "stdout": "Chassis Power is off" if ipmi["bmc_ip"] == "10.0.0.5" else "Chassis Power is on"}
    monkeypatch.setattr("hisho.power.PowerExecutor.run_ipmi", run_ipmi)
    ctx = ctx_for(ip)
    assert addons.summarize(ip, ctx)["headline"] == "2 machines · 1 on"
    secs = {s["entry"]: s for s in addons.details(ip, ctx)}
    assert [a["id"] for a in secs["big-box"]["items"][0]["actions"]] == ["on"]
    assert addons.act(ip, "kihon", "power", "off", ctx)["ok"] is False
    assert addons.act(ip, "big-box", "power", "on", ctx)["ok"] and calls[-1] == ("10.0.0.5", "power on")


SDR = """CPU1 Temp        | 01h | ok  |  3.1 | 45 degrees C
FAN1             | 41h | ok  | 29.1 | 3800 RPM
FAN3             | 43h | cr  | 29.3 | 400 RPM
FAN2             | 42h | lnr | 29.2 | 0 RPM
12V              | 30h | ok  |  7.17 | 12.19 Volts
PS1 Status       | c8h | ok  | 10.1 | Presence detected
FAN4             | 44h | ns  | 29.4 | No Reading
"""


def test_parse_sdr_groups_readings_and_skips_no_reading():
    from importlib import util
    spec = util.spec_from_file_location("ipmi_provider", HERE / "provider.py")
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.parse_sdr(SDR)
    assert [(r["name"], r["group"], r["status"]) for r in rows] == [
        ("CPU1 Temp", "Temperatures", "ok"), ("FAN1", "Fans", "ok"), ("FAN3", "Fans", "cr"), ("FAN2", "Fans", "stopped"),
        ("12V", "Voltages", "ok"), ("PS1 Status", "Other", "ok")]


def test_a_typed_password_is_kept_only_in_the_local_secrets_file(fleet, tmp_path, monkeypatch):
    secrets = tmp_path / "secrets.env"
    secrets.write_text("OTHER=1\nHISHO_ADDON_IPMI_BIG_BOX_PASSWORD=old\n")
    monkeypatch.setattr(addons, "LOCAL_SECRETS", str(secrets))
    ip = addons.get("ipmi")
    addons.set_entry(ip, "big-box", {"address": "10.0.0.5", "user": "ADMIN", "password": "hunter2!x"}, merge=True)
    saved = addons.entries(ip)["big-box"]
    assert saved["password"] == "HISHO_ADDON_IPMI_BIG_BOX_PASSWORD"
    assert "hunter2" not in addons.config_path("ipmi").read_text()
    assert secrets.read_text().splitlines() == ["OTHER=1", "HISHO_ADDON_IPMI_BIG_BOX_PASSWORD=hunter2!x"]
    assert oct(secrets.stat().st_mode & 0o777) == "0o600"
    # a later save with the password left blank keeps it
    addons.set_entry(ip, "big-box", {"address": "10.0.0.6"}, merge=True)
    assert addons.entries(ip)["big-box"]["password"] == "HISHO_ADDON_IPMI_BIG_BOX_PASSWORD"
    # a secret's name is kept as a name
    addons.set_entry(ip, "pve", {"address": "10.0.0.7", "password": "IPMI_PASSWORD_BMC_134"}, merge=True)
    assert addons.entries(ip)["pve"]["password"] == "IPMI_PASSWORD_BMC_134"


def test_critical_sensors_need_you_and_power_cycle_reset_exist(fleet, monkeypatch):
    ip = addons.get("ipmi")
    addons.set_entry(ip, "big-box", {"address": "10.0.0.5", "user": "ADMIN", "password": "HISHO_BB_PASS"})
    calls = []

    def run_ipmi(self, ipmi, verb):
        calls.append(verb)
        if verb == "sdr elist full":
            return {"ok": True, "stdout": SDR}
        return {"ok": True, "stdout": "Chassis Power is on"}
    monkeypatch.setattr("hisho.power.PowerExecutor.run_ipmi", run_ipmi)
    ctx = ctx_for(ip)
    summ = addons.summarize(ip, ctx)
    assert summ["state"] == "down"
    assert [p["title"] for p in summ["problems"]] == ["big-box: FAN3 is critical"]
    [sec] = addons.details(ip, ctx)
    power, *groups = sec["items"]
    assert [a["id"] for a in power["actions"]] == ["soft", "cycle", "reset", "off"]
    fans = next(g for g in groups if g["name"].startswith("Fans"))
    assert fans["state"] == "down" and fans["facts"][0] == "FAN3 400 RPM (critical)"
    assert addons.act(ip, "big-box", "power", "cycle", ctx)["ok"] and calls[-1] == "power cycle"


def test_the_test_button_uses_a_typed_password_without_saving_it(fleet, tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "LOCAL_SECRETS", str(tmp_path / "secrets.env"))
    ip = addons.get("ipmi")
    seen = []

    def run_ipmi(self, ipmi, verb):
        seen.append(self.resolver.resolve(ipmi["password_ref"]))
        if verb == "power status":
            return {"ok": True, "stdout": "Chassis Power is off"}
        return {"ok": True, "stdout": "Product Name : X10DRU-i+\nFirmware Revision : 3.88"}
    monkeypatch.setattr("hisho.power.PowerExecutor.run_ipmi", run_ipmi)
    res = addons.test_entry(ip, "new", {"address": "10.0.0.5", "user": "ADMIN", "password": "typed-pw"})
    assert res["ok"] and res["message"] == "Connected: power is off · Product Name X10DRU-i+ · Firmware Revision 3.88"
    assert seen == ["typed-pw", "typed-pw"]
    assert not (tmp_path / "secrets.env").exists() and addons.entries(ip) == {}


def test_bmc_errors_are_said_in_plain_words(fleet, monkeypatch):
    ip = addons.get("ipmi")
    addons.set_entry(ip, "big-box", {"address": "10.0.0.5", "user": "ADMIN", "password": "HISHO_BB_PASS"})
    monkeypatch.setattr("hisho.power.PowerExecutor.run_ipmi",
                        lambda self, ipmi, verb: {"ok": False, "stderr": "cipher 17: Error: Unable to establish IPMI v2 / RMCP+ session"})
    [p] = addons.summarize(ip, ctx_for(ip))["problems"]
    assert p["title"] == "Can't reach big-box's BMC" and "wrong user name or password" in p["detail"]
