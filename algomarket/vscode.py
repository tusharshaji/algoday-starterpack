"""Installs the kit's replay viewer for VS Code (viewer/algoday-replay.vsix).

    python run_local.py --vscode

finds VS Code (and VS Code Insiders, Cursor, VSCodium, Windsurf) and runs its
`--install-extension` for the .vsix. After that, a match's .algoday file in
out/ plays in a tab when it is clicked in the editor.

    from algomarket import vscode
    vscode.main("path/to/the/kit")        # prints what it did; 0 = installed somewhere

Standard library only.
"""
import os
import shutil
import subprocess
import sys
import tempfile

VSIX_NAME = "algoday-replay.vsix"
# (name, command, where its bin folder may be when the command isn't on PATH:
#  on Windows as (environment variable, folder under it), then on a Mac)
EDITORS = (
    ("VS Code", "code",
     (("LOCALAPPDATA", r"Programs\Microsoft VS Code\bin"), ("ProgramFiles", r"Microsoft VS Code\bin")),
     ("/Applications/Visual Studio Code.app/Contents/Resources/app/bin",
      "~/Applications/Visual Studio Code.app/Contents/Resources/app/bin")),
    ("VS Code Insiders", "code-insiders",
     (("LOCALAPPDATA", r"Programs\Microsoft VS Code Insiders\bin"),
      ("ProgramFiles", r"Microsoft VS Code Insiders\bin")),
     ("/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin",)),
    ("Cursor", "cursor",
     (("LOCALAPPDATA", r"Programs\cursor\resources\app\bin"),),
     ("/Applications/Cursor.app/Contents/Resources/app/bin",)),
    ("VSCodium", "codium",
     (("LOCALAPPDATA", r"Programs\VSCodium\bin"), ("ProgramFiles", r"VSCodium\bin")),
     ("/Applications/VSCodium.app/Contents/Resources/app/bin",)),
    ("Windsurf", "windsurf",
     (("LOCALAPPDATA", r"Programs\Windsurf\bin"),),
     ("/Applications/Windsurf.app/Contents/Resources/app/bin",)),
)
TIME_LIMIT = 300   # seconds an editor gets to install it
BY_HAND = ("in VS Code, open the Extensions view (the four squares on the left), click the ... at its top, "
           "choose \"Install from VSIX...\" and pick {vsix} in this folder.")


def find_editors(which=shutil.which, isfile=os.path.isfile, platform=sys.platform, env=os.environ):
    """[(name, command path)] for every editor found: on PATH, else where it
    is usually installed."""
    found = []
    for label, command, windows, mac in EDITORS:
        # On Windows the command is a .cmd file; the plain name next to it is
        # a shell script for Git Bash, which Windows itself can't run.
        names = [command + ".cmd"] if platform == "win32" else [command]
        folders = []
        if platform == "win32":
            for variable, tail in windows:
                if env.get(variable):
                    folders.append(os.path.join(env[variable], tail))
        elif platform == "darwin":
            for folder in mac:
                folders.append(os.path.join(env.get("HOME", ""), folder[2:]) if folder.startswith("~/") else folder)
        path = None
        for name in names:
            if path is None:
                path = which(name)
        for folder in folders:
            for name in names:
                if path is None and isfile(os.path.join(folder, name)):
                    path = os.path.join(folder, name)
        if path is not None:
            found.append((label, path))
    return found


def reason(output):
    """Why an editor refused the .vsix, from what its command printed. It
    prints the error, then a stack trace, then "Failed Installing
    Extensions: <the file>", then Node's own warnings: the error is the
    first line that is none of the others."""
    lines = [line.strip() for line in output.splitlines()]
    lines = [line for line in lines if line and not line.startswith(("(node:", "(Use "))]
    said = [line for line in lines
            if not line.startswith(("at ", "Installing extensions", "Failed Installing Extensions"))]
    if said:
        return said[0]
    return lines[-1] if lines else ""


def install(vsix, editors, run=subprocess.run):
    """Install the .vsix into each of `editors` (find_editors()).
    Returns [(name, True or False, why not)]."""
    folder, name = os.path.split(os.path.abspath(vsix))
    results = []
    for label, command in editors:
        try:
            # The output goes to a file, not a pipe: the editor's own process
            # would hold a pipe open, and the time limit would wait for it.
            with tempfile.TemporaryFile() as output:
                # From the .vsix's folder, by its name alone: on Windows the command
                # is a batch file, which can trip over a path with & or % in it.
                done = run([command, "--install-extension", name, "--force"], cwd=folder,
                           stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=TIME_LIMIT)
                output.seek(0)
                text = output.read().decode("utf-8", errors="replace")
            ok = done.returncode == 0
            results.append((label, ok, "" if ok else reason(text)))
        except subprocess.TimeoutExpired:
            results.append((label, False, f"it didn't finish in {TIME_LIMIT // 60} minutes"))
        except (OSError, subprocess.SubprocessError) as exc:
            results.append((label, False, str(exc)))
    return results


# Said when the viewer couldn't be added: a replay can still be watched.
IN_A_BROWSER = ("Or watch in your browser: drop a match's .algoday file on the Replays tab of the "
                "competition site.")


def main(kit, find=find_editors, run=subprocess.run, say=print):
    """Install the viewer from the kit in folder `kit` and say what happened.
    Returns the exit code: 0 when at least one editor has it."""
    vsix = os.path.join(kit, "viewer", VSIX_NAME)
    shown = os.path.join("viewer", VSIX_NAME)
    if not os.path.isfile(vsix):
        say(f"Can't find {shown} in {kit}. It comes with the starter kit: unzip the kit again "
            "(the organisers' checkout builds it with python scripts/make_starter.py).")
        return 1
    editors = find()
    if not editors:
        say("Couldn't find VS Code on this computer (its `code` command), so nothing was installed.")
        say("Add it by hand: " + BY_HAND.format(vsix=shown))
        say(IN_A_BROWSER)
        return 1
    say(f"Installing the replay viewer ({shown})...")
    installed = 0
    for label, ok, why in install(vsix, editors, run):
        if ok:
            installed += 1
            say(f"  {label}: installed.")
        else:
            say(f"  {label}: couldn't install it ({why or 'no reason given'}).")
    if installed == 0:
        say("Add it by hand: " + BY_HAND.format(vsix=shown))
        say(IN_A_BROWSER)
        return 1
    say("Now click a match's .algoday file in out/ (python run_local.py makes them) and it plays in a tab.")
    say("If it opens as text or not at all, close VS Code and open it again.")
    # The command installs into VS Code's default profile only.
    say("Still not playing (you may use a VS Code profile)? Add it by hand: " + BY_HAND.format(vsix=shown))
    return 0
