# Defence demonstration script

A 10–15 minute live demonstration of the Digital Twin for the project defence. It shows each use case from Chapter 3: UC1 monitor, UC2 predictive alert, UC3 simulation, plus UC4 trends (added by the build) and the two administrator roles.

## The day before

1. Start the system and leave it running for at least an hour, so live forecasts and alerts have history:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10
   ```
2. On the **System** page check:
   - Digital Twin Engine is **Running**;
   - **Cycles missed** is 0;
   - both forecasting models are listed.
3. Make sure you know both passwords: the Senior Administrator account and a **Junior Administrator** account (create one if needed; see INSTALL.md §6).
4. Rehearse the surge command in step 4 once.
5. If the venue may have no internet, set up and test the offline fallback (INSTALL.md).

## On the day

Before the panel arrives:
- start the system;
- sign in as the Senior Administrator;
- close every other program;
- open a second PowerShell window in the project folder for the surge command.

| Step | Do | Say (in your own words) |
|---|---|---|
| 1 | **Overview.** Point at the tiles, then the live map. Hover over a link, then a device. | "The twin mirrors the campus network. Every minute it collects counters from the network, cleans them and updates its model. The colour is current utilisation: green below 70 %, yellow to 90 %, red above. The thickness shows capacity. Status is never colour alone: each one has an icon and a word." |
| 2 | Click a busy link to open its detail page. Show the chart and the dashed forecast. | "Here is the history and, dashed, the Random Forest forecast for the next 30 minutes, with how confident the model is." |
| 3 | Open **System**. Show the engine steps, the cycle time and the model accuracy table. | "Each cycle takes well under a second, inside the 5-second requirement. The forest is measured against simple baselines on days it never saw." |
| 4 | Inject a surge in the second PowerShell window:<br>`backend\.venv\Scripts\python.exe -m netemu lab surge --zone HOSTEL --cls video --multiplier 3 --ramp 20 --hold 30`<br>The surge multiplies the video traffic that is already there, so size it to the network's time of day (shown in the header): `--multiplier 3` in the evening, when the hostels are busy; `--multiplier 10` during the day; `--multiplier 25` at night.<br>Go back to the **Overview**. | "This makes something happen in the 'real' network, the emulator: students start streaming video in the hostels. The twin does not know this is coming; it only sees the counters." |
| 5 | Wait for the **Congestion predicted** alert (usually within a minute at speed 10). Open **Alerts**. | "The alert came before the link reached 90 %. This is the early warning that Chapter 1 said current tools lack (gap G2)." |
| 6 | In the alert, show **Recommended actions**, then **See simulation**. | "When the alert opened, the twin tried possible fixes on a copy of the network and kept the ones that help." |
| 7 | Open **Simulation**. Create a **Link failure** of the ISP-B link and run it. Then use **Compare with: The network now**. | "This is the safe test environment: nothing here touches the real network. If ISP-B fails, all internet traffic moves to ISP-A, and we can see whether it copes before it happens." |
| 8 | Open **Trends**. Show the weekly pattern and the capacity planning table. | "For planning: the quiet hours for maintenance, and which links will reach 90 % first if growth continues." |
| 9 | Sign out. Sign in as the **Junior Administrator**, open **Simulation**, then a link page. | "A junior administrator can see everything but change nothing. The server enforces this, not only the screen." |

If the panel asks about security:
- passwords are stored with Argon2;
- five wrong passwords lock sign-in for 15 minutes;
- changes need the password again after 30 minutes away;
- every sign-in and change is written to `var\log\audit.log`;
- the twin can only read from the network, never write to it.

## If something goes wrong

- **No alert appears within 3 minutes:**
  - the surge may be too small for the current time of day; run it again with `--multiplier 4`;
  - or go to **Alerts → Alert history**, which shows earlier alerts from the generated history.
- **Header says "Data delayed":** close other programs, or restart with a lower speed (`deploy\stop.ps1`, then `start.ps1 -Speed 5`).
- **No internet at the venue:** use the offline fallback you tested the day before.
