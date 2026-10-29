# IPMI (Hisho add-on)

## What it does

Power control and health for machines with a BMC (iDRAC, iLO, Supermicro IPMI...): power state,
the BMC's sensors (temperatures, fans, voltages, power), critical sensors as alerts, and buttons
to power on, power off gracefully or hard, cycle and reset. It never offers to power off the Core
machine. Modeled on the Home Assistant IPMI integration by Adrian Teodorescu (MIT).

## What it needs

- You need:
  - A server with a BMC (iDRAC, iLO, Supermicro IPMI...) on your network
  - A BMC user name and password
- Runs on: the Core machine, inside Hisho Core
- Commands on that machine: `ipmitool`
- One entry per IPMI machine, each with:
  - `address` (str, required)
  - `user` (str, optional)
  - `user_ref` (secret name, optional)
  - `password` (password, kept as a local secret, required)
  - `interface` (list(lanplus|lan), optional)
  - `cipher` (int, optional)
  - `power_only` (bool, optional)
  - `ignore` (str, optional)
  - `note` (str, optional)

## How to install

On the dashboard: **Add-ons > Store > IPMI > Install**. Or from a terminal:

```bash
hisho addon install ipmi
```

Hisho takes the newest version from this repository and turns it on inside Hisho Core. Updates show as **Update
available** on its Store card; **Roll back** returns to the version before.

Needs `ipmitool` on the Core machine.

## How to use

Its card shows each machine's power and any critical sensor. Its page (**Add-ons > IPMI**) has the sensors and **power on**, **power off** (graceful or hard), **cycle** and **reset**; each asks first, and the Core machine never gets a power-off button.

## Settings

Add a machine on its page (**Add-ons > IPMI**). **Found on your network** lists the BMCs that answer
IPMI's presence ping (UDP 623); **Use this** opens the form with the address filled in. Then type the
BMC's user name and password,
the interface (`lanplus` for most, `lan` for old BMCs), and sensors to hide (e.g. empty fan headers
`FAN2,FAN5`). Test checks the BMC before saving; a typed password is kept only on the Core machine
(`~/.hisho-secrets.env`), or give a secret's name. From a terminal:
`hisho addon entry ipmi big-box address=192.0.2.50 user=ADMIN password=HISHO_BIGBOX_IPMI_PASSWORD`.
Entries are kept in `~/Hisho/System/Config/Addons/ipmi.yaml`. To change a password: the machine's
BMC web page > User Management.

## How to remove

**Add-ons > Store > IPMI > Remove**, or `hisho addon remove ipmi`. Its card and page go away; your settings stay in `~/Hisho/System/Config/Addons/ipmi.yaml`, so installing it again picks up where you left off.

## License

Source-available under the [PolyForm Shield License 1.0.0](LICENSE.md): free to use, change and share,
for any purpose except offering a product that competes with Hisho (reselling it, for example).
