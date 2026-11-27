# F117. Fleet deployment (Ansible, GPO)

- **Component:** installers
- **Area:** 19. Packaging and deployment tools
- **Source:** [docs/FEATURES.md](../../FEATURES.md) (status legend, roles, `S/` = `server/app/`, `A/` = `agent/`)

- **Code:** `installers/ansible/site.yml` + roles, `installers/gpo/README.md`, `new_setup_scripts/windows/deploy-agents.ps1`.
  `deploy-agents.ps1` reads the page and fetches the installer from `https://<ccc>[:-HttpsPort]/downloads`; the
  teacher PC and every student PC accept the CCC certificate only if it chains to the lab CA in
  `server/storage/app/private/ca/ca.crt` and its IP SAN matches (`Enable-XephyLabCaTls` in
  `start_server/windows/_common.ps1`, compiled on the remote PC from the same source); a `-SetupUrl` that is not
  HTTPS gets a warning (server S-74 follow-up).
- **Status:** unclear.
- **Test:** 1. `ansible-playbook -i inventory.ini installers/ansible/site.yml --check`.
