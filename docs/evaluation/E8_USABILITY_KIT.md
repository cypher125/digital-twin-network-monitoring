# E8 Usability test kit (NFR3)

This kit is for the usability test in Chapter 4. Campus IT or network staff try the dashboard unaided, then fill in the System Usability Scale (SUS). It takes about 25 minutes per participant.

## Who takes part

- **At least five participants** who look after networks or IT systems, for example staff of the college ICT unit, and who have **no data-science or machine-learning training**. That matches the administrators NFR3 is written for.
- Note each person's role and years of experience.
- Students may take part as well, but their results are reported **separately**, not mixed in with the staff results.

## Before each session

1. Start the system the day before, as in `docs/DEMO_SCRIPT.md`, so it has live history.
2. Sign in as a **Senior Administrator** on the test laptop and open the **Overview**.
3. Have the surge command ready in a second PowerShell window (task 3):
   ```powershell
   backend\.venv\Scripts\python.exe -m netemu lab surge --zone HOSTEL --cls video --multiplier 10 --ramp 15 --hold 30
   ```
   Use `--multiplier 3` in the network's evening and `--multiplier 25` at night (the header shows the network time).
4. Print one **observation sheet** and one **SUS form** per participant (both below).

## What to say to the participant

> "This is a prototype system that monitors a campus network and predicts congestion. We are testing the system, not you. Please think aloud as you work. I will not help unless you are stuck for more than two minutes. You can stop at any time. Your name will not appear in the report."

Get verbal consent, and write down role and years of experience.

## The tasks

Read each task aloud. Start timing when you finish reading, and stop when the participant gives the answer or gives up.

| Task | Use case | Read aloud | Success when the participant… |
|---|---|---|---|
| T1 | UC1 | "Which link in the network is the busiest right now, and how full is it?" | names the busiest link and its utilisation (within a few %) |
| T2 | UC1, detail | "Open the details of the link between DIST-HOSTEL and AP-HOSTEL-01. Is it expected to become congested in the next 30 minutes?" | opens the link page and reads the forecast or warning correctly |
| T3 | UC2 | *(Inject the surge now.)* "Students in the hostels have just started streaming. Watch the system. When it warns you, tell me which link is affected, roughly when it will congest, and one action the system recommends." | names the alerted link, the expected time or minutes, and one recommendation |
| T4 | UC3 | "Using the simulation console, find out what would happen if the ISP-B internet link went down. Would any link be overloaded?" | creates and runs a link-failure scenario and reads the result correctly |
| T5 | UC3, compare | "Compare that result with the network as it is now." | switches the comparison to "The network now" |
| T6 | Trends | "Which link is expected to reach 90 % first if growth continues, and when is a quiet hour for maintenance on Wednesday?" | names the top link in capacity planning and a pale (quiet) hour |

Score each task:
- **1** = done unaided;
- **0.5** = done with one hint;
- **0** = not done, or more than one hint.

## Observation sheet (one per participant)

```
Participant ID: P__     Role: ______________________   Years in IT/networking: ___
Data-science or ML training?  yes / no        Student?  yes / no        Date: __________

Task | Score (1 / 0.5 / 0) | Time (s) | Hints | Notes (what they tried, where they hesitated)
T1   |                     |          |       |
T2   |                     |          |       |
T3   |                     |          |       |
T4   |                     |          |       |
T5   |                     |          |       |
T6   |                     |          |       |

Comments after the session:
```

## System Usability Scale (give after the tasks)

Ask the participant to tick one box for each statement, without thinking about it for long:
1 = strongly disagree … 5 = strongly agree.

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | I think that I would like to use this system frequently. | | | | | |
| 2 | I found the system unnecessarily complex. | | | | | |
| 3 | I thought the system was easy to use. | | | | | |
| 4 | I think that I would need the support of a technical person to be able to use this system. | | | | | |
| 5 | I found the various functions in this system were well integrated. | | | | | |
| 6 | I thought there was too much inconsistency in this system. | | | | | |
| 7 | I would imagine that most people would learn to use this system very quickly. | | | | | |
| 8 | I found the system very cumbersome to use. | | | | | |
| 9 | I felt very confident using the system. | | | | | |
| 10 | I needed to learn a lot of things before I could get going with this system. | | | | | |

The wording is Brooke's standard SUS (1996), with "system" kept as is. Do not change it: changing the wording makes the scores incomparable with published benchmarks.

## Entering and scoring the results

1. Copy `backend/evaluation/results/E8_usability/sus_responses_TEMPLATE.csv` to `backend/evaluation/results/E8_usability/sus_responses.csv`.
2. Type in one row per participant: the observation sheet and the ten SUS answers.
3. Run:
   ```powershell
   cd backend
   .venv\Scripts\python.exe -m evaluation.e8_sus
   ```
   This writes, to `backend/evaluation/results/E8_usability/`:
   - each participant's SUS score (0–100);
   - the mean with a 95 % confidence interval;
   - the rating band;
   - task success rates and times;
   - the charts for Chapter 4.

**How SUS is scored:**
- For each odd-numbered item, subtract 1 from the answer.
- For each even-numbered item, subtract the answer from 5.
- Add the ten results and multiply by 2.5.

The published average across many systems is about **68**. Scores above about 71 are usually described as "good", and above about 85 as "excellent" (Bangor, Kortum and Miller, 2009).

## Reporting in Chapter 4

- Report the number of participants, their roles and experience.
- Report the mean SUS score with its interval, and the task success rate and median time per task.
- Quote the most common problems from the notes.
- Report students separately.
- With five participants, the confidence interval is wide: say so, and present the result as an early indication, not a precise measurement.
