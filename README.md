# platform-health

The **platform health dashboard** of palermo-sites: https://palermo-sites.github.io/platform-health/

Modelled on the agentic platform kit's platform dashboard (website-platform-kit decision 0008, superseding the Azure
Static Web App dashboard): the platform's structure as a landscape (operators → the platform kit → the website systems
in the GitHub organization → the services they share) and every system as a project group with a tile per environment,
UAT then prod: last deploy, whether the node answers, uptime, whether `main` is green, domain status, the scorecard
summary with a link to the site's scorecard report, and a link to the system's own health dashboard.

- `registry/`: a copy of the kit's `platform/platform.json` and `platform/systems/`, pushed by the kit's workflow
  `registry` on every change (deploy key on this repository; `registry/COMMIT` names the kit commit). Do not edit here.
- `scripts/platform.py`: reads the registry, each system's published `health.json`, the system repositories through the
  GitHub API and each site's `scorecard-data/latest.json`; writes `index.html` and `platform.json`.
- Workflow `platform`: every 30 minutes, on every push (a registry change) and by hand; deploys to GitHub Pages.

Public by design: names of systems, repositories, addresses and delivery numbers. No secret is stored or needed.
