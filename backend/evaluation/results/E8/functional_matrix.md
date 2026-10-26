| Requirement | Source | What is verified | Evidence | Result |
|---|---|---|---|---|
| FR1 | §3.4.1, O1 | Represent the topology as a dynamic graph with node and edge attributes and configuration | tests 5/5; experiments 1/1 (E1) | **pass** |
| FR2 | §3.4.1, O2 | Synchronise the model with monitoring data periodically and on events | tests 9/9; experiments 1/1 (E1) | **pass** |
| FR3 | §3.4.1, O3 | Analyse trends, forecast utilisation and warn before congestion, with lead time | tests 6/6; experiments 2/2 (E2, E3) | **pass** |
| FR4 | §3.4.1, O4 | Test changes on a detached copy and show bottlenecks created or relieved | tests 8/8; experiments 1/1 (E4) | **pass** |
| FR5 | §3.4.1, O5 | Web dashboard with a live topology view | walkthrough steps 2/2; tests 2/2; experiments 0/1 (E5) | **fail** |
| UC1 | Figure 3.5 | Monitor network topology in real time | walkthrough steps 3/3 | **pass** |
| UC1-ext | Figure 3.5 | View device / link detail | walkthrough steps 2/2 | **pass** |
| UC2 | Figure 3.5 | Receive predictive congestion alerts (link, time, confidence, recommendation) | walkthrough steps 1/1; tests 2/2; experiments 1/1 (E3) | **pass** |
| UC2-ext | Figure 3.5 | View trend and forecast chart | walkthrough steps 1/1; tests 1/1 | **pass** |
| UC3 | Figure 3.5 | Run a what-if simulation | walkthrough steps 1/1; tests 2/2; experiments 1/1 (E4) | **pass** |
| UC3-ext | Figure 3.5 | Compare scenario result with current state | walkthrough steps 1/1; tests 1/1 | **pass** |
| UC4 | Weakness 3 (§3.7) | Analyse long-term trends and plan capacity | walkthrough steps 1/1; tests 5/5; experiments 1/1 (E9) | **pass** |
| Auth | Figure 3.5 «include» | Authenticate (log in) with two roles | walkthrough steps 4/4; tests 3/3 | **pass** |
| NFR1 | §3.4.2 | Responsiveness: new data on screen within 5 s | walkthrough steps 1/1; tests 3/3; experiments 0/1 (E5) | **fail** |
| NFR2 | §3.4.2 | Reliability: runs unattended and recovers from faults | tests 4/4; documents 1/1 (docs/evidence/P6_recovery.json); experiments 2/2 (E6, E6_database) | **pass** |
| NFR3 | §3.4.2 | Usability for administrators without data-science training | documents 1/1 (docs/evaluation/E8_USABILITY_KIT.md); experiments 0/1 (E8-SUS) | **pending** |
| NFR4 | §3.4.2, §3.8 | Security: authentication, roles, HTTPS, CSRF, throttling, audit | tests 11/11; documents 1/1 (docs/evidence/P6_security_headers.txt) | **pass** |
| NFR5 | §3.4.2 | Modularity: layered packages, pluggable adapters and scenario types | import-linter 1/1; tests 3/3; documents 1/1 (docs/EXTENDING.md) | **pass** |
| G1 | §3.2 | A live replica of the network | experiments 1/1 (E1) | **pass** |
| G2 | §3.2 | Forecasts bound to links, with alerts | experiments 1/1 (E3) | **pass** |
| G3 | §3.2, §3.8 | Changes tested on a detached copy with no write path to the network | tests 4/4; import-linter 1/1; experiments 1/1 (E4) | **pass** |
| G4 | §3.2 | Affordable, open source, administrator-first | documents 2/2 (docs/INSTALL.md, docs/USER_GUIDE.md); experiments 1/2 (E7, E8-SUS) | **pending** |
| Optimisation | §3.2 (title) | Recommend tested fixes for predicted congestion | tests 4/4; experiments 2/2 (E4, E4_recommendations) | **pass** |
| Tables 3.2/3.3 | §3.6 | The six tables, their principal fields and relationships | tests 7/7 | **pass** |
| Figure 3.4 | §3.5 | Data flow: processes 1.0-6.0 and stores D1-D4 | tests 2/2; documents 1/1 (docs/diagrams/dfd.svg) | **pass** |
