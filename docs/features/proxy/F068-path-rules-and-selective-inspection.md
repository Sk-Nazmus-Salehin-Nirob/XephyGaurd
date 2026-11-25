# F68. Path rules and selective inspection

- **Component:** proxy
- **Area:** 12. Network enforcement (gateway, DNS, proxy)
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **What:** for chosen hosts (`inspect_hosts`, seeded from `data/network/proxy.yaml`, editable on `/settings`)
  the proxy decrypts and blocks specific paths. Logged paths of inspected requests never include the query string ([F70](F070-observe-allowed-ai-ide-traffic.md)).
  Each entry is one exact host; `*.example.com` opts in to its subdomains (not example.com itself). Sign-in, mail and document hosts (`NEVER_INSPECT` in `domains.py`: accounts/mail/docs/drive.google.com, login.live.com, outlook.office.com, ...) are never decrypted, a wildcard included (`inspect_hosts_match_exactly_with_opt_in_wildcard`, `seed_inspect_hosts_cover_search_but_not_google_accounts`).
  A host named by a path rule of the client's group is inspected too, even when `inspect_hosts` doesn't list it (I-PROXY-17; `TlsDecision` reason `path rule host`): only for test/block_ai, only the rule's exact host (`hf.co` for `hf.co/chat`, not `cdn.hf.co`), never a `NEVER_INSPECT` host, and only rules of that group's categories (block_ai gets `ai` rules, so `aws.amazon.com/q` is inspected in Test only) (`path_rule_hosts_are_inspected_for_their_group`). Before, such a rule never applied over HTTPS.
  HTTP decisions use the same policy: before one valid `proxy.json` has loaded, every plain-HTTP and inspected request gets the block page (`no_policy`); a broken update keeps the last good path rules.
  The request path is normalised before it is compared with a rule (`domains.normalize_path`, I-PROXY-16): query and fragment dropped, percent-decoded (until stable, at most 3 rounds, so `%2563` too), a backslash read as `/`, `;params` dropped from every segment, `//` collapsed, `.`/`..` resolved, lower-case; rule paths are normalised the same way. So `/%63hat`, `//chat`, `/chat;x` and `/x/../chat` all match `huggingface.co/chat`, while `/chatterbox` and `/models;chat` still do not (`path_rules_match_normalised_paths`, `path_rules_normalising_does_not_widen_rules`, `path_rule_blocks_disguised_paths`). Only matching uses it; events still carry `loggable_path`.
  A path-rule block carries the category whose rule list matched (`State.path_rule_match`, I-PROXY-24), so an IDE rule (`aws.amazon.com/q`) is `ide` in net_events and alerts, not `ai` (`path_rule_block_has_category_of_matched_rule`).
  Path rules are compiled once per policy load (`State.build_index`, I-PROXY-20): per category and per group, each indexed by rule host, so a request looks up its host and parent hosts instead of scanning every rule. The first matching rule in list order still wins. With 5,000 rules `path_rule_match` takes about 14 µs (2,000 calls within the test's 0.25 s budget, `lookups_on_5000_domains_fit_timing_budget`).
- **Code:** addon `request` (`proxy/addons/hooks_http.py`), `proxy_logic.py`.
- **Status:** working (`path_rule_blocked`, `path_rule_blocks_disguised_paths`, `plain_http_blocked_domain`).
- **Test:** 1. Add a host/path rule. 2. That path is blocked, the rest of the site works.
