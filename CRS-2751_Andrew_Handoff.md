# CRS-2751 Gwinnett Preventive Screening Reconciliation: handoff for Andrew

Run 11/23/2026. Member history as of 11/20/2026 19:57. Last files: 101151 on 11/03/2026, 101152 on 10/05/2026.

Workbook: `output/CRS-2751_Gwinnett_PS_Reconciliation_20261123.xlsx` in the CRS-2751 ticket folder (identifiers only, no PII).
Everything you need to load is on the **Add_To_Payment_File** tab.

## What this is

On 9/21/2026 a plan shift re-fired the Preventive Screening reward (100 pts, Engage) for 1,557 med-enrolled
members who had one screening. Every refire is held on the error file as `Duplicate` and none was sent. These members
are owed points when either of these is true:

- **True 2nd screening**: a second, different screening (DOS 1/1 to 10/31/2026) came in and got 0 points because
  the refire had used the second slot.
- **Overmax recovery (Engage only)**: the refire's 100 points pushed the member to the Engage cap, so later Engage
  activities earned 0 or partial points.

Points due per member never exceed `Engage cap - Engage points awarded excluding the refire`.

## Totals

| PROGRAM_ID | PS_EVENT_ID | ENGAGE_CAP | MEMBERS | TRUE_2ND | OVERMAX | TOTAL |
|---|---|---|---|---|---|---|
| 692dfbe47425f9676936b8f2 | 692dfbe47425f9676936b8cf | 500 | 162 | 12,150 | 2,975 | 15,125 |
| 692e07214050a36039ca2358 | 692e07214050a36039ca2307 | 600 | 439 | 36,975 | 3,900 | 40,875 |

**601 members, 56,000 points.** 956 members on the impact list are owed nothing.

## How to load each row (`SOURCE_FILE_STATUS` and `HANDLING` columns)

| REASON | SOURCE_FILE_STATUS | ROWS | MEMBERS | POINTS_DUE | HANDLING |
|---|---|---|---|---|---|
| OVERMAX RECOVERY | NOT YET SENT - WILL FLOW NORMALLY | 24 | 23 | 1,550 | POINTS_AWARDED flows on the next normal file. Add POINTS_DUE on top. |
| OVERMAX RECOVERY | ON ERROR FILE - Zero Dollar Event | 49 | 42 | 1,925 | Pull back from the error file at POINTS_DUE (platform shows 0). |
| OVERMAX RECOVERY | SOURCE ROW ALREADY SENT | 48 | 48 | 3,400 | Add POINTS_DUE only (the difference). Row is already in incentives_earned_events. |
| TRUE 2ND SCREENING | EVENT ONLY - NO EARNED ROW | 513 | 513 | 49,125 | Add POINTS_DUE. No earned row exists, so the normal extract will never send it. |

## Gotchas for your dupe and overmax checks

1. **Leave the refire out of any over-max check.** The platform still counts the held refire's 100 points, so these
   members look like they're at the cap on the platform. The workbook's `ENGAGE_AWARDED_EXCL_REFIRE` + `POINTS_DUE`
   is never above the cap (checked for every member, along with the program max).
2. **True 2nd rows have no earned row.** `SOURCE_HISTORY_ID` is the raw `event` history row, so it won't be in
   `incentives_stage`, `incentives_earned_events` or `incentives_errors`. Use the program's Preventive Screening
   event ID above. The normal extract will never send these, so there is no double-pay risk from the regular flow.
3. **Overmax rows already sent**: the `history_id` is already in `incentives_earned_events` at the awarded points.
   A dedupe on `history_id` will block it. Send only `POINTS_DUE` (the difference).
4. **Overmax rows on the error file (`Zero Dollar Event`)**: the platform shows 0. Pull them back at `POINTS_DUE`.
5. **Overmax rows not yet sent**: the awarded part goes out on the next normal file. `POINTS_DUE` is extra on top. Don't replace it.
6. **Other Engage points still in the normal flow**: 74 of these members have 83 other Engage rows (14,875 pts)
   awarded but not yet sent or errored (tab `Pending_Normal_Flow`). The points due already account for them under the cap,
   so both the normal rows and `POINTS_DUE` should be paid.
7. **`incentives_earned_events` has the same `history_id` once per extract** (101151 and 101152), so use MAX, not SUM.
8. **If new data lands before you load**, rerun `CRS-2751_PS_Reconciliation.ipynb`. The amounts can change.

## Flagged for review (Ginger and Andrew), tab `Review_Flags`

| REVIEW_FLAG | MEMBERS | ON_PAYMENT_LIST | REVIEW_NOTE |
|---|---|---|---|
| PAID - RECEIVED BEFORE 9/21, NEVER FIRED | 11 | 11 | Counted per Ginger 11/23 (Well Woman and mammogram are 2 screenings). Platform never fired it when received - confirm why with the incentives team. |
| PLAN SHIFT - IN BOTH PROGRAMS | 1 | 1 | Has Engage history in both 692e07 and 692dfb. Points are calculated in the refire program. Confirm which program the payment goes under and that the replayed rows in the other program are not paid. |

## Decisions (Ginger, 11/23)

- Well Woman and mammogram are 2 different screenings, so same-day Well Woman events now count even though they were
  received 8/03 (before 9/21) and never fired.
- The 10/31 DOS cutoff is firm. Screenings with DOS 11/1 or later stay excluded.

## Checks that passed on this run

- members = impact list
- one row per member
- every member has a 9/21 refire
- every refire held as Duplicate, none sent
- max one true 2nd screening per member
- no true 2nd dated after 10/31
- no duplicate source rows on report
- due never above headroom
- Engage awarded (excl refire) + due <= cap
- all pillars + due <= program max
- reported points = awarded points
