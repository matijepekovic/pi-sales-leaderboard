# Pi Tableau Sales Leaderboard v5

## Architecture

```text
Tableau sales data
      ↓
Pi source connector
      ↓
Persistent local SQLite database
      ↓
Pi organization layer
      ↓
Leaderboard calculations
      ↓
Pi-hosted website
      ↓
Chromium kiosk → HDMI → TV
```

## Persistence

All important user configuration is stored in:

```text
~/.local/share/pi-tableau-leaderboard/leaderboard.db
```

That database is outside the installed application directory.

It persists through:
- reboot
- power loss
- browser restart
- Tableau refresh
- normal software updates

`install.sh` also creates:

```text
leaderboard.db.backup-before-update
```

before replacing application files.

## Pi-owned teams

Tableau is not authoritative for leaderboard team membership.

The Pi stores:
- teams
- team names
- one team leader per team
- lead role (Sales Manager, SMIT, General Manager, Other)
- rep-to-team assignments

Tableau's team remains stored as `tableau_team` for reference and fallback.

A rep with no local Pi assignment uses the Tableau team.

A rep with a local Pi assignment uses the Pi team regardless of Tableau.

## Tableau refresh behavior

When Tableau is connected, refreshing sales data replaces the rep metrics but does NOT touch:

- created Pi teams
- team leads
- rep team assignments
- display mode
- visible columns
- ranking stat
- ranking direction

The Tableau connector should pull the office/branch population needed for the leaderboard, then the Pi groups it locally. This prevents Tableau team filters from excluding a rep who was reassigned on the Pi.

## Recalculated team performance

When a rep moves from Team A to Team B, the Pi immediately rebuilds both team totals from the rep-level data.

Team calculations use the raw components:

- Issued Leads = sum of reps
- Pitched Leads = sum of reps
- Sold Leads = sum of reps
- Gross Split = sum of reps
- Pending Split = sum of reps
- Net Split = sum of reps
- Pitched Rate = team pitched / team issued
- Close Rate = team sold / team issued
- DPL = team net split / team issued
- Sales Retention = team net split / team gross split
- Avg Gross Sale = team gross split / team sold
- Avg Net Sale = team net split / team sold

Percentages and averages are not incorrectly averaged across reps.

## Ranking

Each mode independently selects:
- Rank By stat
- Highest is #1 OR Lowest is #1

Modes:
1. Whole Office
2. Team vs Team
3. All Teams
4. Per Team

## Team management

Settings page:

```text
http://PI-IP:8765/settings
```

You can:
- create a team
- assign one team leader
- identify each leader as Sales Manager, SMIT, General Manager, or Other
- assign any rep to any Pi team
- remove a local assignment and return to the Tableau team
- archive teams
- select Team vs Team teams
- select the Per Team view
- choose visible stats per mode
- choose ranking stat per mode

## Upgrade from v3/v4

The database migration is automatic.

Existing text-based team overrides are converted into persistent Pi teams and rep assignments where possible.


## Update directly from an iPhone

Open the Pi settings page on the same Wi-Fi:

```text
http://PI-IP:8765/settings
```

Go to **Software Update**.

1. Download the new leaderboard ZIP to the iPhone Files app.
2. Tap **Choose File**.
3. Select the ZIP.
4. Tap **Install Update**.
5. The Pi backs up the current application, preserves the persistent database,
   installs the new code/dependencies, and restarts the leaderboard service.
6. The settings page waits for the Pi to come back and reloads automatically.

Normal app updates no longer require Terminal.

Persistent data remains at:

```text
~/.local/share/pi-tableau-leaderboard/leaderboard.db
```

A failed application install restores the previous application files from the update backup.


## One-click install / update

For Raspberry Pi OS Desktop, normal Terminal commands are no longer required.

1. Download the ZIP on the Raspberry Pi.
2. Open the Downloads folder.
3. Right-click the ZIP and choose **Extract Here**.
4. Open the extracted `pi_tableau_leaderboard` folder.
5. Double-click **INSTALL LEADERBOARD**.
6. If Raspberry Pi OS asks whether to execute the file, choose **Execute** / **Launch**.
7. Enter the Raspberry Pi password if prompted.
8. Wait for `INSTALLATION COMPLETE`.
9. Press `R` if you want the Pi to reboot immediately.

The installer automatically:
- installs required packages
- installs/updates the leaderboard service
- preserves the persistent SQLite settings/database
- backs up the current database before software updates
- configures fullscreen kiosk startup

After v8/v9 is installed, future normal app updates can also be uploaded from the phone through the **Software Update** section in Settings.


## v10 double-click installer

The update package now contains one installer:

```text
INSTALL-LEADERBOARD
```

After extracting the ZIP, double-click that file and choose **Execute** or
**Execute in Terminal** if Raspberry Pi OS asks.

The installer uses its own real filesystem location, so it works regardless of
where the extracted folder is placed.

Do not run files directly from inside the ZIP/archive viewer; extract the ZIP first.


## Team leader dropdown

Each team has one leader.

The leader is selected from a dropdown rather than typed manually. The dropdown
is built from:

- Tableau `Team Lead Name` values found in the source data
- Tableau people whose title identifies them as a manager / SMIT
- already saved Pi leaders, so a temporary Tableau omission does not erase the selection

The leader role remains separately selectable as Sales Manager, SMIT, General
Manager, or Other.


## Interactive Team Builder

Team management is now one workflow instead of separate settings.

Create or edit a team:

1. Choose team name
2. Add/replace/remove team logo
3. Choose one team lead from the Tableau-derived dropdown
4. Choose team lead role
5. Search and select members
6. Review
7. Save Team

Saving a team performs the organization change as one operation. A rep selected
for a new Pi team is moved from their prior local Pi team automatically. Team
performance is then recalculated from the rep-level sales data.

Team logos are persisted outside the application code in:

```text
~/.local/share/pi-tableau-leaderboard/team-logos/
```

so they survive reboot and normal software updates.


## Whole Office total row

Whole Office mode now includes a `TOTAL` row at the bottom.

Additive metrics are summed:
- Issued Leads
- Pitched Leads
- Sold Leads
- Gross Split
- Pending Split
- Net Split

Derived metrics are recalculated from the whole-office components:
- Pitched Rate = total pitched / total issued
- Close Rate = total sold / total issued
- DPL = total net split / total issued
- Sales Retention = total net split / total gross split
- Avg Gross Sale = total gross split / total sold
- Avg Net Sale = total net split / total sold

The total row respects the columns selected for Whole Office view.


## TV controls

The Settings page includes two remote TV controls:

### Refresh TV View

Reloads the leaderboard webpage on the office TV without restarting Chromium or
the Raspberry Pi.

### Restart TV View

Closes and reopens the fullscreen Chromium kiosk. The TV may go black briefly,
then the leaderboard returns automatically.

`kiosk.sh` now keeps Chromium in a restart loop, so the kiosk recovers if the
browser crashes or is deliberately restarted from Settings.


## v15 reliable app restart

`Restart Leaderboard App` no longer depends on killing Chromium.

It now:
1. saves a persistent restart counter
2. returns a response to the phone
3. exits the leaderboard backend
4. systemd automatically launches a fresh backend process
5. the TV detects the restart counter and performs a hard reload
6. the phone waits for the server to come back and confirms success

This restarts the leaderboard application without rebooting the Raspberry Pi.


## v16 automatic fullscreen kiosk

The TV display is now self-enforcing.

At desktop login the Pi starts `kiosk.sh`. The kiosk watchdog:
- waits for the leaderboard server
- launches Chromium with a dedicated kiosk-only browser profile
- uses both `--kiosk` and `--start-fullscreen`
- disables first-run/session-crash interruptions
- keeps the TV awake
- automatically relaunches Chromium if it is closed or crashes
- waits for the backend if the leaderboard application is restarting
- accepts a `Force Fullscreen TV` request from the phone Settings page

A dedicated Chromium profile is stored at:

```text
~/.local/share/pi-tableau-leaderboard/chromium-kiosk-profile/
```

This avoids interference from normal Chromium windows/profiles.

After installing v16, reboot the Raspberry Pi once so the graphical-session
autostart watchdog starts with the new kiosk behavior. After that, no manual
F11/fullscreen action is required.


## v17 Raspberry Pi labwc fullscreen fix

Raspberry Pi OS Bookworm and newer use Wayland with labwc by default.

v17 now follows the Raspberry Pi kiosk method directly:

- creates/maintains `~/.config/labwc/autostart`
- launches the leaderboard watchdog from labwc startup
- Chromium uses `--kiosk --start-maximized`
- removes the old leaderboard-specific XDG autostart file to prevent duplicate
  Chromium windows
- uses a dedicated Chromium kiosk profile
- `Force Fullscreen TV` requests a complete kiosk relaunch
- if `wtype` is installed, F11 is also sent as a fallback

The server self-repairs the labwc autostart file after a phone software update.

After installing v17, reboot the Raspberry Pi once. That reboot is required for
labwc to load the newly managed autostart configuration.

## v18 Team vs Team head-to-head layout

Team vs Team is now a dedicated two-team comparison view.

- hard limit of two selected teams in both Settings and backend
- two dropdowns replace the old unlimited team checkboxes
- team aggregate panel always shows all 12 core KPIs:
  issued, pitched, pitched rate, sold, close rate, gross, pending, net, DPL,
  retention, average gross sale, and average net sale
- individual rep performance is always displayed below each team
- rep stat visibility still uses the independent Team vs Team metric toggles
- existing installs get the full individual metric set enabled once on v18
- layout uses two side-by-side team columns and compact KPI grids, then the
  existing auto-fit engine scales only when necessary to keep everything on TV

Derived team totals are recalculated from raw components rather than averaging
rep percentages or averages.


## v19 Team vs Team overflow fix

Team vs Team has been rebuilt as a dedicated two-panel scoreboard.

- Maximum two teams
- Both teams always fit inside the TV width
- No generic team-card renderer is used in Team vs Team
- All 12 team totals are always visible
- Every rep always shows all 12 numeric stats
- Team and rep KPIs use short TV-friendly labels
- Team totals use a compact 6 x 2 grid
- Each rep uses a compact 6 x 2 stat grid
- Team vs Team ignores stale older visibility settings
- The auto-fit routine no longer widens the Team vs Team canvas beyond the TV,
  which was the source of the right-side overflow


## v20 Active TV Mode controls the stat selector

There is no separate display-mode editing menu anymore.

The `Active TV Mode` dropdown is now the only mode selector. When it changes:
- Rank By changes to that mode's saved setting
- Ranking Direction changes to that mode's saved setting
- Data shown on TV changes to that mode's saved toggles

For team-based views (`Team vs Team`, `All Teams`, `Per Team`), these fields are
removed from the stat selector because the team context is already established:
- Team
- Home Branch
- Title
- Hire Date

For Team vs Team, the selected numeric toggles control BOTH:
- team aggregate totals
- individual rep stats

The head-to-head renderer keeps its two-column TV-optimized layout and dynamically
reflows the selected metrics to avoid horizontal overflow.

## v21 aligned team totals and unified ranking

Team vs Team now uses one row structure for both team aggregates and reps.

- `TEAM TOTAL` sits directly above that team's reps
- team totals and rep values use the exact same metric grid
- every selected metric occupies the same position in the aggregate and rep rows
- the active `Rank By` metric is visually highlighted in both team and rep rows
- the backend ranks the two teams by the same `Rank By` metric and the same
  Highest/Lowest direction used to rank reps
- team ranking and rep ranking therefore always use one consistent rule


## v22 simple ranking

Ranking Direction has been removed completely.

There is one rule everywhere:
- select `Rank By`
- highest value is always #1
- teams and reps both sort high-to-low using that same metric

Team vs Team:
- first team is labeled `WINNER`
- second team has no placement label
- `Ranked by ...`, `Highest is #1`, and `Lowest is #1` are no longer shown
- TEAM TOTAL does not repeat a team rank number
- individual reps can still display #1, #2, #3, etc. when Rank is enabled


## v23 All Teams redesign

All Teams now shows team cards only.

Each card includes:
- team logo and name
- team lead (when available)
- selected team KPI list
- MVP section

MVP is the highest-ranked rep on that team based on the current `Rank By` metric.
Example:
- if `Rank By` = Net Split, MVP is the rep with the highest Net Split on that team
- if `Rank By` = DPL, MVP is the rep with the highest DPL on that team

The All Teams stat selector now exposes only numeric team KPIs, because the TV
card no longer shows full individual rep tables in that mode.


## v24 Per Team total row

Per Team now includes a real `TOTAL` row at the bottom of the rep table,
using the same visible columns and the same aggregation logic as Whole Office.

So Per Team now has:
- the existing top summary area
- the rep table
- a bottom TOTAL row for the selected team


## v25 permanent team deletion

`Archive` has been removed from Team Builder.

Teams now have `Delete Team`.

Deletion rules:
- a team with zero reps can be deleted immediately
- a team with reps cannot be deleted until every rep is reassigned
- the delete screen shows every rep with a destination-team dropdown
- different reps can be moved to different teams
- the leader and stored team logo are removed with the deleted team
- team performance recalculates after reassignment

Deleted team names are remembered by the Pi. If Tableau still reports that old
team name later, the Pi will not silently recreate it. A new rep arriving from
that deleted Tableau team appears as `Unassigned` until assigned in Team Builder.

Creating a team again with the same name intentionally restores it.


## v26 deleted-team recreation correction

Deleting a team only deletes the current Pi team structure.

Rules:
- existing reps on that team still must be reassigned before deletion
- those rep overrides remain on their new teams
- the deleted team name is NOT blacklisted
- if Tableau later reports that team again, normal source sync may recreate it
- new reps arriving from Tableau under that team can appear on that recreated team

In other words: deleting a team does not delete, block, or alter people.


## v27 per-team selector moved into Active TV Mode

There is no separate `Per Team View` team selector anymore.

Instead, the `Active TV Mode` dropdown now lists:
- Whole Office
- Team vs Team
- All Teams
- one `Per Team — <team name>` option for every team

Choosing a team directly there activates that specific team view. This removes the
extra per-team settings card and keeps all mode selection in one place.

Per-team display settings still use the shared `per_team` configuration bucket, so
switching from one team to another does not reset which columns are shown.


## v28 Team vs Team chooser moved into Active TV Mode

The permanent `Team vs Team` settings card has been removed.

New flow:
1. Open `Active TV Mode`
2. Choose `Team vs Team`
3. A two-team chooser opens immediately
4. Select Team 1 and Team 2
5. Press `Use These Teams`

After selection, the Active TV Mode option shows the matchup, for example:
`Team vs Team — Undisputed vs Team Charlie`.

The head-to-head team selectors no longer occupy permanent space on the Settings
page.


## v29 cleaner Active TV Mode menu

Team entries in `Active TV Mode` now display only the team name.

The menu is structured as:
- Whole Office
- Team vs Team
- All Teams
- Team Alpha
- Team Bravo
- Team Charlie
- Undisputed
- etc.

The internal per-team mode still works the same way; only the unnecessary
`Per Team —` wording has been removed from the user interface.


## v30 simpler Team vs Team menu label

`Active TV Mode` now always displays exactly `Team vs Team`.

The selected matchup is not repeated in the dropdown. Choosing `Team vs Team`
still opens the two-team chooser when needed.


## v31 public GitHub automatic updates

The Pi can now use a public GitHub repository as its software-update source.

Settings -> Software Update now includes:
- Public GitHub repository (`owner/repo`)
- Automatically install newer versions
- Check GitHub Now

The Pi checks GitHub every 15 minutes. It reads the repository's root `VERSION`
file and compares it with the installed version. If GitHub has a higher version,
the Pi downloads the default-branch ZIP archive, uses the existing safe updater,
preserves persistent data, and restarts the leaderboard automatically.

No GitHub token is required for a public repository.

See `GITHUB_SETUP.md` for the one-time setup.
