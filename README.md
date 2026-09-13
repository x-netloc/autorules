# autorules

Canonical, client-independent routing policies.

This repository does not publish client-ready rule files. It defines the one
source of truth consumed by format-specific adapters:

- `shadowrocket-autorules`
- `mihomo-autorules`
- `happ-autorules`

## Repository layout

```text
catalog.toml       upstream, category catalog and ordered profile IDs
profiles/*.toml    ordered, vendor-neutral routing policies
scripts/validate.py
```

The source dataset is
[`runetfreedom/russia-v2ray-rules-dat`](https://github.com/runetfreedom/russia-v2ray-rules-dat).
Downstream repositories download its `geosite.dat` and `geoip.dat` directly,
then generate every category listed in `catalog.toml`.

## Profiles

| Profile | Default | Purpose |
| --- | --- | --- |
| `bypass-blacklist` | direct | Proxy blocked resources and selected global services |
| `freedom-no-ru` | proxy | Route private, Apple and Russian resources directly |
| `freedom-no-ru-no-ads` | proxy | Same as above, with advertising domains rejected |

Profiles contain semantic actions (`direct`, `proxy`, `reject`) rather than
client-specific policy names. Each adapter maps those actions to its own
format, preserving rule order.

## Validate

Python 3.11 or newer is required; there are no third-party dependencies.

```bash
python3 scripts/validate.py
```
