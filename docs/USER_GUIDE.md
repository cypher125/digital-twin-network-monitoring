# User guide

The Digital Twin is a live copy of the campus network. It shows how busy every link is, warns before a link becomes congested, and lets you try changes safely before making them on the real network.

Open **https://localhost** and sign in with your account.

## Your role

| Role | Can |
|---|---|
| **Junior Administrator** | See everything |
| **Senior Administrator** | Everything a junior can, plus: create and run simulations, edit devices and links, import a topology, manage accounts |

**After 30 minutes away,** the dashboard asks a senior for the password again before any change. Looking around never needs it.

**Five wrong passwords** lock sign-in for that account for 15 minutes.

## Colours and symbols

Every status is shown three ways: a colour, an icon and a word.

| You see | Means |
|---|---|
| green, ✓ **Normal** | below 70 % of capacity |
| yellow, ⚠ **Warning** | 70 % to 90 % |
| red, ⓘ **Critical** | 90 % or more: congested |
| orange glow, ◷ **Congestion predicted** | the forecast says the link is likely to reach 90 % within 30 minutes |
| grey dashes, ⊘ **Down** | out of service |
| grey dots, ? **No data** | no reading from the device |

The header shows **Live** while the twin is up to date. **Data delayed** means it is behind, and **Engine stopped** means it is not running.

Times are West Africa Time (WAT). Times marked **(server clock)** come from the laptop's own clock rather than the network's.

## Pages

### Overview

- **Tiles at the top:** devices up, average and busiest link, and how many links are at warning level, congested now, or predicted to congest.
- **Live network map:** each line is a link and each shape a device (the legend under the map explains the shapes).
  - Point at a line or shape for its figures; click it to open its page.
  - **Fit** shows the whole network again.
  - **Table** lists the same links as rows.
- **Predictive alerts and Busiest links now:** what needs attention first.
- **Network utilisation, last 6 hours:** the average of all links and the busiest link, with the 70 % and 90 % lines.

### Link and device pages

- **Utilisation and forecast** shows the link's history. The **dashed** part is the forecast for the next 30 minutes.
- **Period** (1 h, 6 h, 24 h, 7 days) changes both charts on the page.
- **Forecast by horizon** gives the predicted value at 5, 10, 15 and 30 minutes, and whether the link is likely to reach 90 %, with how confident the model is.
- **Configuration (Topology Store)**, seniors only: correct capacity, routing cost, location or status.
  - The Digital Twin Engine applies changes when it next starts. The System page says when that is needed.
  - Devices and links are retired, not deleted, so their history is kept. A device cannot be retired while links in service still use it: retire the links first.

### Alerts

- **An alert opens** when a link is likely to reach 90 % within the next 30 minutes. It closes after the link has been quiet for five minutes.
- **What each alert shows:**
  - when the problem is expected and how confident the model is;
  - the forecast at each horizon;
  - **Recommended actions**, fixes the twin has already tested on a copy of the network.
- **See simulation** shows the tested fix. **Try in simulator** (seniors) copies it into the Simulation console, so you can adjust it and run it again.
- **Alert history** lists alerts from the last 24 or 48 hours.

### Simulation

Try a change on a copy of the network. Nothing here touches the real network.

1. Choose the kind of change, for example **Link failure** or **Capacity change**.
2. Fill in the details and give the scenario a name.
3. Choose the traffic to test with:
   - **Current traffic**, the network now;
   - **Forecast traffic**, as predicted in 5 to 30 minutes.
4. Press **Save and run**. The result is usually ready within a second or two.

A scenario that has been run cannot be edited: use **Copy** to change it, so every result always matches the scenario that produced it.

**On the result page:**
- **What would happen:** a summary in words.
- **Tiles:** busiest link before and after, bottlenecks created and relieved, devices cut off, traffic that could not be delivered.
- **Links that change most:** before and after. **Compare with: The network now** compares against the live network instead of the model.
- **The network after the change:** the map, coloured as it would be.
- **Every link:** all links as a table.

### Trends

For planning. The **Period** and **Link** filters at the top apply to the first chart and the busiest links.

- **Weekly pattern:** average use by weekday and hour over the last 14 days. Cells near the 0 % end of the key are the quiet times for maintenance.
- **Capacity planning:** each link's growth per week and, if growth continues in a straight line, when it would reach 90 %. Weekends are allowed to be quieter than weekdays, so a quiet weekend does not look like falling traffic. Treat it as an early hint for budgeting, not a promise.
- **Export CSV:** hourly figures for every link, for a spreadsheet or a report.

### System

- **Digital Twin Engine:**
  - whether it is running;
  - how long each monitoring cycle takes (well under the 5-second target);
  - **Cycles missed**, which should stay at 0: if it rises, the laptop is too slow for the chosen speed;
  - data quality.
- **Forecasting models:** how accurate each model was on days it never saw, against simply assuming nothing changes.
- **Database and Settings:** for information.
- **Administrator accounts, Import topology** (seniors), and **Change your password**.

## Good to know

- Charts and tables have a **Chart / Table** switch: the table has the exact figures.
- The theme follows Windows (light or dark). Change it in the account menu at the top right.
- Everything a senior changes, and every sign-in, is recorded in the audit log (`var\log\audit.log`).
