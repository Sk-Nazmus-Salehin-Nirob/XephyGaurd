# F68. Path rules and selective inspection

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** for chosen hosts (`inspect_hosts`, seeded from `data/network/proxy.yaml`, editable on `/settings`)
  the proxy decrypts and blocks specific paths. Logged paths of inspected requests never include the query string ([F70](F070-observe-allowed-ai-ide-traffic.md)).
  Each entry is one exact host; `*.example.com` opts in to its subdomains (not example.com itself). Sign-in, mail and document hosts (`NEVER_INSPECT` in `domains.py`: accounts/mail/docs/drive.google.com, login.live.com, outlook.office.com, ...) are never decrypted, a wildcard included (`inspect_hosts_match_exactly_with_opt_in_wildcard`, `seed_inspect_hosts_cover_search_but_not_google_accounts`).
- **Code:** addon `request`, `proxy_logic.py`.
- **Status:** working (`path_rule_blocked`, `plain_http_blocked_domain`).
- **Test:** 1. Add a host/path rule. 2. That path is blocked, the rest of the site works.
