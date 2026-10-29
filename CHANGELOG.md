# Changelog

## 0.3.0

- Found on your network: the page lists the BMCs that answer IPMI's presence ping (RMCP, UDP 623); Use this fills
  the address. No Sign in once: IPMI signs in with the BMC user each time, so that user and password are what Hisho keeps.
- Setup help says so.

## 0.2.2

- Every field on its setup form says in plain words what it is, and links to where to get it (addon.yaml `help:`, shown by Hisho's dashboard).

## 0.2.1

- README says what you need (addon.yaml you_need) and how to use it; the README check requires both.

## 0.2.0

- Moved out of Hisho into its own repository (hisho-addon-ipmi); installed from the add-on store.
- Typed passwords, sensors, a Test button and plain-words BMC errors.
