# GitHub Setup — Pi Sales Leaderboard

This project is designed to use a **public GitHub repository** as its automatic
software-update source.

## One-time GitHub setup

1. Sign in to GitHub.
2. Create a new **Public** repository.
3. Recommended repository name: `pi-sales-leaderboard`.
4. Do not initialize it with extra starter files if GitHub gives you that option.
5. Extract the `pi-tableau-github-repo-v31.zip` package into a folder on your computer/Pi.
6. Open the extracted folder.
7. On the empty GitHub repository page, choose the option to upload existing files.
8. Upload **the contents of the extracted folder** so that `app`, `VERSION`,
   `install.sh`, and `README.md` are at the ROOT of the GitHub repository.
9. Commit the upload to the default branch.

Your GitHub repository should look roughly like:

```text
app/
VERSION
README.md
GITHUB_SETUP.md
requirements.txt
install.sh
kiosk.sh
...
```

Do NOT create an extra folder above `app/` inside the GitHub repository.

## One-time Raspberry Pi setup

Install v31 on the Pi once using the existing phone updater:

Settings -> Software Update -> choose
`pi-tableau-sales-leaderboard-v31-github-auto-update.zip`

After the Pi restarts:

1. Open Settings from your phone.
2. Scroll to Software Update -> Automatic GitHub Updates.
3. Enter the repo as `YOUR_GITHUB_USERNAME/pi-sales-leaderboard`.
4. Turn on `Automatically install newer versions`.
5. Press `Save Display Settings`.
6. Press `Check GitHub Now`.

The Pi checks the public repo every 15 minutes.

## Publishing future updates

Each update package should contain a higher number in the root `VERSION` file.

To publish:
1. Replace/upload the new project files to the GitHub repository.
2. Commit them to the default branch.
3. The Pi sees the higher VERSION and installs the repository automatically.

The SQLite database, team assignments, logos, and settings live outside the app
folder and are preserved across normal software updates.
