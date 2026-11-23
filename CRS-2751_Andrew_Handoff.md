# CRS-2751 Gwinnett Preventive Screening Reconciliation: handoff for Andrew

| | |
|---|---|
| Run ID | `20261123_1319` |
| Member history as of | 11/20/2026 19:57 |
| Last reward files | 101151 on 11/03/2026, 101152 on 10/05/2026 |
| Previous run compared | none (first run) |
| Delivered runs already netted out | none |
| Workbook | `output/CRS-2751_Gwinnett_PS_Reconciliation_20261123_1319.xlsx` in the CRS-2751 ticket folder (identifiers only, no PII) |

**601 members, 56,000 points to add to the final reward file.**
956 members on the impact list are owed nothing. Load from the **Add_To_Payment_File** tab.

| Program ID | PS Event ID | Engage Cap | Members | True 2nd | Overmax | Total |
|---|---|---|---|---|---|---|
| 692dfbe47425f9676936b8f2 | 692dfbe47425f9676936b8cf | 500 | 162 | 12,150 | 2,975 | 15,125 |
| 692e07214050a36039ca2358 | 692e07214050a36039ca2307 | 600 | 439 | 36,975 | 3,900 | 40,875 |

## 1. What happened

Gwinnett pays up to 2 Preventive Screenings (100 points each) in the Engage pillar. On 9/21/2026 an unintended plan
shift on eligibility made the platform fire the screening a second time for med-enrolled employees and spouses who had
only one screening, using the same date of service. That second award (the "refire") is not a real screening, so all
1,557 refire rows were held on the error file as `Duplicate` and kept off the Q3 payout. The points could not be
reversed, so they are still in each member's Sharecare account.

The refire caused two kinds of underpayment, and this reconciliation finds both.

## 2. How the member list was built

All logic is in `crs2751_ps_reconciliation.sql`, run by `CRS-2751_PS_Reconciliation.ipynb`. The only source is the
incentive platform history (`ENT_WH.SC_INCENT_MEMBER_HISTORY`) plus the program setup tables, and what was sent or held is
read from `bi_reporting.incentives_earned_events` and `bi_reporting.incentives_errors`.

**Step 1: population.** The 1,557 members on the impact list (11/20 secure email), in both 2026 Embrace
Wellness programs. Engage caps: 692dfb... = 500, 692e07... = 600. Every member must have exactly one 9/21 refire row, held as `Duplicate` (or released by a delivered run).

**Step 2: find the refire.** The second earned row for the same reward event, screening code and date of service, earned on
9/21. Everything else in the member's Engage history is treated as real.

**Step 3: true 2nd screening.** A Preventive Screening event that:
- has a date of service from 1/1/2026 to 10/31/2026 (10/31 is firm, per Ginger),
- is a different screening than the one already paid (a different screening code, or a different date of service), and
- got 0 points, because the refire had already used the member's second screening slot.

At most one per member (the program allows 2 and every member has 1 paid). A different screening on the same day counts,
for example Well Woman and mammogram (Ginger, 11/23). 11 of these were received 8/03, before the refire, and never
fired. They count and are flagged for review.

**Step 4: overmax recovery (Engage only).** The refire's points count toward the Engage cap on the platform. If that pushed a
member to the cap, later Engage activities were paid 0 or less than their full value. Each such row is due the shortfall.
Rows limited by their own rules are not included (a non-repeatable activity already earned, an activity's own point
limit, or data received after the activity's end date). Balance, Connect and Premium Reduction are never included.

**Step 5: points due.** For each member:

    room under the cap = Engage cap - Engage points awarded (excluding the refire) - points already paid by this reconciliation
    points due         = the true 2nd and overmax shortfalls, in the order they were received, until the room is used up

So a member is never paid above the Engage cap or the program max, and never more than their Sharecare account shows.

Points due by activity on this run:

| Reason | Event Description | Rows | Points Due |
|---|---|---|---|
| TRUE 2ND SCREENING | Complete a Preventive Screening | 513 | 49,125 |
| OVERMAX RECOVERY | Complete Annual Physical | 55 | 4,400 |
| OVERMAX RECOVERY | Get a Flu Shot at one of the Gwinnett Flu Clinics or at the Wellness Center | 17 | 750 |
| OVERMAX RECOVERY | Gwinnett Employee Wellness Center Appointment | 15 | 650 |
| OVERMAX RECOVERY | Meet with Wellness Center Registered Dietitian In-Person | 13 | 550 |
| OVERMAX RECOVERY | Sharecare Lifestyle Telephonic Wellness Coaching | 20 | 500 |
| OVERMAX RECOVERY | Participate in an approved ENGAGE Event | 1 | 25 |

The Summary tab of the workbook walks through a full overmax example.

## 3. How to load it onto the final reward file

1. Open **Add_To_Payment_File**. There is one row per payment, and `POINTS_DUE` is the amount to pay. Filter on `LOAD_ACTION`.
2. Handle each `LOAD_ACTION` as below. `ERROR_FILE_HISTORY_ID` is the exact row to take off the error file.

| Load Action | Rows | Members | Points Due | What To Do |
|---|---|---|---|---|
| RELEASE REFIRE ROW FROM ERROR FILE | 513 | 513 | 49,125 | Take ERROR_FILE_HISTORY_ID (the held 9/21 refire, error reason Duplicate) off the error file and put it on the reward file at POINTS_DUE. The member already has these points in their Sharecare account from the refire. |
| ADD DIFFERENCE ROW | 48 | 48 | 3,400 | The source row was already sent at POINTS_AWARDED. Add a row for POINTS_DUE only (the difference). A dedupe on history_id will block it, so it needs a manual exception. |
| RELEASE ROW FROM ERROR FILE | 49 | 42 | 1,925 | Take ERROR_FILE_HISTORY_ID (error reason Zero Dollar Event, platform shows 0) off the error file and put it on the reward file at POINTS_DUE. |
| ADD ON TOP OF NORMAL FLOW | 24 | 23 | 1,550 | POINTS_AWARDED goes out on the next normal file. Add POINTS_DUE on top. Do not replace it. |
| TOTAL | 634 | 601 | 56,000 |  |

3. Run your dupe and over-max checks, keeping in mind:
   - **Leave the refire out of any over-max check, except the rows you are releasing.** The platform counts every refire
     toward the cap, so these members look capped. `ENGAGE_AWARDED_EXCL_REFIRE + POINTS_DUE` is never above the cap.
   - **A released refire row carries the original screening's date of service.** If the file needs the 2nd screening's
     date, use `ACTIVITY_DATE` from the tab.
   - **`ADD DIFFERENCE ROW` reuses a history_id that is already in `incentives_earned_events`**, so a history_id dedupe
     will block it.
   - `incentives_earned_events` holds the same history_id once per extract (101151 and 101152). Use MAX, not SUM.
   - 74 of these members also have 83 other Engage rows (14,875 pts) awarded but not yet sent. They go out on
     the normal file as usual. The points due already account for them under the cap.
4. **After the file is loaded, send Brandon the run ID `20261123_1319`.** It gets added to `DELIVERED_RUNS` in the notebook, and that is
   what stops a rerun from paying the same rows again.

## 4. Reruns: tracking who was added back and taken off the error file

Every run saves its payment rows to `output/runs/payment_rows_<RUN_ID>.csv` (identifiers only). On a rerun:

- **Delivered runs are netted out.** For each run ID in `DELIVERED_RUNS`, the points paid come off that row and off the
  member's room under the cap. A member who was fully paid shows as `ALREADY PAID BY RECONCILIATION` and drops off the payment tab.
- **New data is picked up.** A screening or Engage activity that arrived after the last run is added if it qualifies and
  there is room under the cap.
- **The Changes_Since_Last_Run tab** lists every difference from the previous run:
  - `ADDED`: a new row is due. `WHY` says what changed.
  - `REMOVED`: a row from the last run is no longer due. `WHY` says whether it was paid on a delivered run, whether the
    member's room under the cap changed, or whether the source data changed.
  - `POINTS CHANGED`: the same row, with a different amount.
  - `DELIVERED IN RUN ...`: one line per row already loaded, showing whether its `ERROR_FILE_HISTORY_ID` is now on a sent
    file, still on the error file (it needs removing there), or off the error file but not yet sent.
- The checks fail the run if a refire row was released without being on a delivered run, or if any member would go over
  the cap, the program max or their Sharecare account balance.

This run compared to: **none (first run)**

| Change | Rows | Members |
|---|---|---|
| NONE | 0 | 0 |

## 5. Flagged for review (Ginger and Andrew), tab `Review_Flags`

| Review Flag | Members | On Payment List | Review Note |
|---|---|---|---|
| PAID - RECEIVED BEFORE 9/21, NEVER FIRED | 11 | 11 | Counted per Ginger 11/23 (Well Woman and mammogram are 2 screenings). Platform never fired it when received - confirm why with the incentives team. |
| PLAN SHIFT - IN BOTH PROGRAMS | 1 | 1 | Has Engage history in both 692e07 and 692dfb. Points are calculated in the refire program. Confirm which program the payment goes under and that the replayed rows in the other program are not paid. |

## 6. Decisions

| Date | From | Decision |
|---|---|---|
| 11/23 | Ginger | Well Woman and mammogram are 2 different screenings, so the same-day Well Woman events received 8/03 count. |
| 11/23 | Ginger | The 10/31 date-of-service cutoff is firm. Screenings dated 11/1 or later stay excluded. |

## 7. Checks that passed on this run

- members = impact list
- one row per member
- every member has a 9/21 refire
- refires held as Duplicate unless released by a delivered run
- max one true 2nd screening per member
- no true 2nd dated after 10/31
- no duplicate source rows on report
- due never above headroom
- awarded (excl refire) + earlier loads + due <= Engage cap
- paid after this load <= Engage points on the platform
- all pillars + earlier loads + due <= program max
- reported points = awarded points (rows not yet loaded)
