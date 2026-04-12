"""Edwin Plombery App -- scheduler with web UI."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from plombery import get_app, register_pipeline, task, Trigger, Pipeline
from plombery.pipeline.context import pipeline_context

# Auto-detect EDWIN_HOME: env var > ~/Edwin
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", Path.home() / "Edwin"))
PYTHON = os.environ.get("PYTHON", sys.executable)
PYTHON_312 = os.environ.get("PYTHON_312", PYTHON)
EVENTS_URL = os.environ.get("EVENTS_URL", "http://127.0.0.1:8790/job-complete")
SKILL_EVENTS_URL = os.environ.get("SKILL_EVENTS_URL", "http://127.0.0.1:8790/run-skill")
PLOMBERY_PORT = int(os.environ.get("PLOMBERY_PORT", "8899"))


def run_cmd(cmd: str, timeout: int = 7200) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=str(EDWIN_HOME),
            capture_output=True, text=True, timeout=timeout
        )
        status = "OK" if result.returncode == 0 else f"ERROR (exit {result.returncode})"
        output = (result.stdout + result.stderr)[-1000:]
        return f"{status}\n{output}"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"


@task
def notify_complete(sync_result):
    """Post pipeline completion to the events channel."""
    pipeline = pipeline_context.get()
    status = "ok" if sync_result.startswith("OK") else "error"
    payload = json.dumps({
        "event_type": "job_complete",
        "source": "plombery",
        "job": pipeline.id,
        "pipeline": pipeline.name,
        "status": status,
        "message": sync_result[:500],
    })
    try:
        req = urllib.request.Request(
            EVENTS_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # don't fail the pipeline over a notification
    return sync_result


def fire_skill_event(skill_name: str) -> str:
    """Post a run_skill event to the events channel. The orchestrator
    receives this, spawns a subagent, and executes the skill."""
    payload = json.dumps({
        "event_type": "run_skill",
        "source": "plombery",
        "skill": skill_name,
        "message": f"SKILL: {skill_name}\nACTION: Spawn background subagent to execute {EDWIN_HOME}/skills/{skill_name}/SKILL.md\nReturn the Completion Report when done.",
    })
    try:
        req = urllib.request.Request(
            SKILL_EVENTS_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        return f"OK\nSkill event fired: {skill_name}"
    except Exception as e:
        return f"ERROR\nFailed to fire skill event: {e}"


@task
def trigger_morning_brief():
    return fire_skill_event("morning-brief")

@task
def trigger_daily_agenda():
    return fire_skill_event("daily-agenda")

@task
def trigger_morning_brief_daily_archive():
    return fire_skill_event("morning-brief-daily-archive")

@task
def trigger_weekly_archive():
    return fire_skill_event("weekly-archive")

@task
def trigger_weekly_dispatch():
    return fire_skill_event("weekly-dispatch")

@task
def trigger_pm_capture():
    return fire_skill_event("pm-capture")

@task
def trigger_limitless_analysis():
    return fire_skill_event("limitless-analysis")

@task
def trigger_nightwatch():
    """Write state file and fire nightwatch skill event."""
    import pytz
    from datetime import datetime, timedelta
    tz = pytz.timezone(os.environ.get("TZ", "America/New_York"))
    now = datetime.now(tz)
    stop_at = now.replace(hour=3, minute=30, second=0, microsecond=0)
    if stop_at <= now:
        stop_at += timedelta(days=1)
    state_file = EDWIN_HOME / "data" / "nightwatch" / ".nightwatch-state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "active": True,
        "stop_at": stop_at.isoformat(),
        "started_at": now.isoformat(),
        "trigger": "scheduled"
    }, indent=2))
    return fire_skill_event("nightwatch")

@task
def trigger_ops_dashboard():
    return fire_skill_event("ops-dashboard")

@task
def trigger_intent_check():
    return fire_skill_event("intent-check")

@task
def trigger_pre_1on1_brief():
    return fire_skill_event("pre-1on1-brief")

@task
def trigger_monday_prep():
    return fire_skill_event("monday-prep")


# -- Connector sync tasks --

@task
def o365_sync():
    return run_cmd(f"{PYTHON} connectors/o365/o365 sync all")

@task
def google_sync():
    return run_cmd(f"{PYTHON} connectors/google/google sync all")

@task
def imessage_sync():
    return run_cmd(f"{PYTHON} connectors/imessage/imessage sync all")

@task
def limitless_sync():
    return run_cmd(f"{PYTHON} connectors/limitless/limitless sync all")

@task
def browser_sync():
    return run_cmd(f"{PYTHON} connectors/browser/browser sync all")

@task
def notes_sync():
    return run_cmd(f"{PYTHON} connectors/notes/notes sync all")

@task
def sessions_sync():
    return run_cmd(f"{PYTHON} connectors/sessions/sessions sync")

@task
def atlassian_sync():
    return run_cmd(f"{PYTHON} connectors/atlassian/atlassian sync all")

@task
def fireflies_sync():
    return run_cmd(f"{PYTHON} connectors/fireflies/fireflies sync all")

@task
def calls_sync():
    return run_cmd(f"{PYTHON} connectors/calls/calls sync all")

@task
def screentime_sync():
    return run_cmd(f"{PYTHON} connectors/screentime/screentime sync all")

@task
def photos_sync():
    return run_cmd(f"{PYTHON} connectors/photos/photos sync all")

@task
def documents_sync():
    return run_cmd(f"{PYTHON} connectors/documents/documents sync all")

@task
def contacts_sync():
    return run_cmd(f"{PYTHON} connectors/contacts/contacts sync")

@task
def plaud_sync():
    return run_cmd(f"{PYTHON} connectors/plaud/plaud")


# -- Tool tasks --

@task
def indexer_run():
    return run_cmd(f"{PYTHON_312} tools/indexer/indexer sync")

@task
def session_watcher():
    return run_cmd(f"{PYTHON} tools/session-watcher/capture")

@task
def systems_report():
    return run_cmd(f"{PYTHON} tools/systems-report/report")

@task
def pm_export():
    return run_cmd(f"{PYTHON} briefing-book/scripts/pm-export")

@task
def librarian_check():
    return run_cmd(f"{PYTHON} tools/librarian/librarian full")

@task
def workspace_publish():
    return run_cmd(f"{PYTHON} briefing-book/scripts/obsidian-publish --all")

@task
def obsidian_watcher():
    return run_cmd(f"{PYTHON} briefing-book/scripts/obsidian-watcher --sync")

@task
def pm_loop():
    return run_cmd(f"{PYTHON} briefing-book/scripts/pm-loop")

@task
def overnight_cleanup():
    return run_cmd(f"{PYTHON} briefing-book/scripts/overnight-cleanup")

@task
def pm_dedup():
    return run_cmd(f"{PYTHON} tools/pm-dedup/pm-dedup clean")

@task
def shared_layer_backup():
    return run_cmd("bash scripts/backup-shared-layer all", timeout=600)

@task
def pm_recurring():
    return run_cmd(f"{PYTHON} tools/pm-recurring/pm-recurring instantiate")

@task
def pr_monitor():
    return run_cmd(f"{PYTHON} tools/pr-monitor/pr-monitor scan")

@task
def teams_unanswered():
    return run_cmd(f"{PYTHON} tools/teams-unanswered/teams-unanswered scan")

@task
def pm_wake():
    return run_cmd(f"{PYTHON} tools/pm-wake/pm-wake run")

@task
def ambient_poll():
    return run_cmd(f"{PYTHON} tools/ambient-poll/ambient-poll snap")

@task
def email_unanswered():
    return run_cmd(f"{PYTHON} tools/email-unanswered/email-unanswered scan")

@task
def session_slicer():
    return run_cmd(f"{PYTHON} tools/session-slicer/session-slicer sync")

@task
def email_priority_scan():
    return run_cmd(f"{PYTHON} tools/email-priority/email-priority --hours 12")

@task
def nightwatch_heartbeat():
    """Check if nightwatch is active and should continue."""
    import pytz
    state_file = EDWIN_HOME / "data" / "nightwatch" / ".nightwatch-state.json"
    if not state_file.exists():
        return "OK\nNo nightwatch state file. Skipping."
    try:
        state = json.loads(state_file.read_text())
    except Exception:
        return "OK\nCould not read nightwatch state. Skipping."
    if not state.get("active", False):
        return "OK\nNightwatch not active. Skipping."
    from datetime import datetime
    tz = pytz.timezone(os.environ.get("TZ", "America/New_York"))
    now = datetime.now(tz)
    stop_at = datetime.fromisoformat(state["stop_at"])
    if hasattr(stop_at, 'tzinfo') and stop_at.tzinfo is None:
        stop_at = tz.localize(stop_at)
    if now >= stop_at:
        # Deactivate
        state["active"] = False
        state_file.write_text(json.dumps(state, indent=2))
        return "OK\nNightwatch stop time reached. Deactivated."
    payload = json.dumps({
        "event_type": "nightwatch_heartbeat",
        "source": "plombery",
        "message": "NIGHTWATCH HEARTBEAT: Check if a task subagent is active. If the plan file exists and has uncompleted tasks, and no subagent is running, spawn the next task. Stop time: " + state["stop_at"],
    })
    try:
        req = urllib.request.Request(
            EVENTS_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        return "OK\nHeartbeat sent. Stop at: " + state["stop_at"]
    except Exception as e:
        return f"ERROR\nFailed to send heartbeat: {e}"


# -- Sync: High Frequency --
register_pipeline(id="sync-o365", name="Sync: O365", description="Mail, calendar, teams, sharepoint", tasks=[o365_sync, notify_complete], triggers=[Trigger(id="t1", name="Every 15 min", schedule=IntervalTrigger(minutes=15))])
register_pipeline(id="sync-google", name="Sync: Google", description="Gmail + Google Calendar", tasks=[google_sync, notify_complete], triggers=[Trigger(id="t2", name="Every 30 min", schedule=IntervalTrigger(minutes=30))])
register_pipeline(id="sync-imessage", name="Sync: iMessage", description="iMessage conversations", tasks=[imessage_sync, notify_complete], triggers=[Trigger(id="t3", name="Every hour", schedule=IntervalTrigger(hours=1))])
register_pipeline(id="sync-limitless", name="Sync: Limitless", description="Limitless lifelogs", tasks=[limitless_sync, notify_complete], triggers=[Trigger(id="t4", name="Every hour", schedule=IntervalTrigger(hours=1))])
register_pipeline(id="sync-browser", name="Sync: Browser", description="Safari + Chrome history", tasks=[browser_sync, notify_complete], triggers=[Trigger(id="t5", name="Every 2 hours", schedule=IntervalTrigger(hours=2))])
register_pipeline(id="sync-notes", name="Sync: Notes", description="Apple Notes", tasks=[notes_sync, notify_complete], triggers=[Trigger(id="t6", name="Every 2 hours", schedule=IntervalTrigger(hours=2))])
register_pipeline(id="sync-atlassian", name="Sync: Atlassian", description="Jira, Confluence, Bitbucket", tasks=[atlassian_sync, notify_complete], triggers=[Trigger(id="t8", name="Every 2 hours", schedule=IntervalTrigger(hours=2))])

# -- Sync: Daily --
register_pipeline(id="sync-fireflies", name="Sync: Fireflies", description="Meeting transcripts", tasks=[fireflies_sync, notify_complete], triggers=[Trigger(id="t9", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-calls", name="Sync: Calls", description="Phone call logs", tasks=[calls_sync, notify_complete], triggers=[Trigger(id="t10", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-screentime", name="Sync: Screentime", description="App usage", tasks=[screentime_sync, notify_complete], triggers=[Trigger(id="t17", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-photos", name="Sync: Photos", description="Photo metadata", tasks=[photos_sync, notify_complete], triggers=[Trigger(id="t18", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-documents", name="Sync: Documents", description="Desktop, Documents, iCloud", tasks=[documents_sync, notify_complete], triggers=[Trigger(id="t19", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-plaud", name="Sync: Plaud", description="Plaud Note Pro meeting recordings and transcripts", tasks=[plaud_sync, notify_complete], triggers=[Trigger(id="t37b", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sync-contacts", name="Sync: Apple Contacts", description="Import Apple Contacts into identity registry. Weekly Sunday 6 AM.", tasks=[contacts_sync, notify_complete], triggers=[Trigger(id="t41", name="Sunday 6 AM", schedule=CronTrigger(day_of_week="sun", hour=6))])

# -- Memory --
register_pipeline(id="mem-indexer", name="Memory: Indexer", description="Chunk markdown into Qdrant vectors. Incremental -- only processes new/changed files.", tasks=[indexer_run, notify_complete], triggers=[Trigger(id="t11", name="Every hour", schedule=IntervalTrigger(hours=1))])
register_pipeline(id="mem-librarian", name="Memory: Librarian", description="Health and quality audit across Qdrant, Neo4j, and Ollama. Checks freshness, runs known-answer queries, flags drift.", tasks=[librarian_check, notify_complete], triggers=[Trigger(id="t12", name="Daily 6 AM", schedule=CronTrigger(hour=6))])

# -- System --
register_pipeline(id="sys-session-watcher", name="System: Session Watcher", description="Monitors the active Claude Code session. Captures conversation-state.md when idle > 60min or token usage > 70%.", tasks=[session_watcher, notify_complete], triggers=[Trigger(id="t13", name="Every 15 min", schedule=IntervalTrigger(minutes=15))])
register_pipeline(id="sys-systems-report", name="System: Health Report", description="Nightly infrastructure check -- Docker containers, Ollama, disk space, Qdrant stats, Neo4j entity counts, connector sync recency.", tasks=[systems_report, notify_complete], triggers=[Trigger(id="t14", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="sys-pm-export", name="System: PM Export", description="Export prospective memory items to Obsidian-formatted markdown in the briefing book.", tasks=[pm_export, notify_complete], triggers=[Trigger(id="t15", name="Daily 10 PM", schedule=CronTrigger(hour=22))])
register_pipeline(id="sys-workspace-publish", name="System: Workspace Publish", description="Publish all briefing book docs to the Obsidian vault. Compares checksums, only copies changed files.", tasks=[workspace_publish, notify_complete], triggers=[Trigger(id="t16", name="Every 5 min", schedule=IntervalTrigger(minutes=5))])
register_pipeline(id="sys-obsidian-watcher", name="System: Obsidian Watcher", description="Sync edits made in the Obsidian vault back to the briefing book. Detects changes by comparing file hashes and mtimes.", tasks=[obsidian_watcher, notify_complete], triggers=[Trigger(id="t25", name="Every 10 min", schedule=IntervalTrigger(minutes=10))])
register_pipeline(id="sys-pm-loop", name="System: PM Sync Loop", description="Bidirectional PM sync -- pulls checkbox/date/note changes from Obsidian Action Tracker, applies them to the PM database, then re-exports.", tasks=[pm_loop, notify_complete], triggers=[Trigger(id="t26", name="Every 15 min", schedule=IntervalTrigger(minutes=15))])
register_pipeline(id="sys-overnight-cleanup", name="System: Overnight Cleanup", description="Archives stale overnight logs and drafts older than 7 days.", tasks=[overnight_cleanup, notify_complete], triggers=[Trigger(id="t27", name="Daily 2 AM", schedule=CronTrigger(hour=2))])
register_pipeline(id="sys-nightwatch-heartbeat", name="System: Nightwatch Heartbeat", description="Every 30 min from 9 PM to 4 AM, checks if the nightwatch loop is active. Posts heartbeat event to orchestrator.", tasks=[nightwatch_heartbeat, notify_complete], triggers=[Trigger(id="t29", name="Every 30 min", schedule=IntervalTrigger(minutes=30))])
register_pipeline(id="sys-pm-dedup", name="System: PM Dedup", description="Detect and cancel near-duplicate PM items using fuzzy string matching.", tasks=[pm_dedup, notify_complete], triggers=[Trigger(id="t30", name="Friday 7:30 PM", schedule=CronTrigger(day_of_week="fri", hour=19, minute=30))])
register_pipeline(id="sys-shared-layer-backup", name="System: Shared Layer Backup", description="Back up PM SQLite, Qdrant snapshot, and Neo4j graph export.", tasks=[shared_layer_backup, notify_complete], triggers=[Trigger(id="t32", name="Daily 11 PM", schedule=CronTrigger(hour=23))])
register_pipeline(id="sys-email-unanswered", name="System: Email Unanswered", description="Detect emails awaiting the user's reply. Scans mail data, filters newsletters/automated.", tasks=[email_unanswered, notify_complete], triggers=[Trigger(id="t44", name="Weekdays 7:30 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=7, minute=30))])
register_pipeline(id="sys-teams-unanswered", name="System: Teams Unanswered", description="Detect Teams messages awaiting the user's reply. Scans 1:1 and group chats from the last 3 days.", tasks=[teams_unanswered, notify_complete], triggers=[Trigger(id="t38", name="Weekdays 7 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=7))])
register_pipeline(id="sys-pr-monitor", name="System: PR Monitor", description="Scan PRs, generate aging report. Flags PRs >7 days (aging) and >30 days (critical).", tasks=[pr_monitor, notify_complete], triggers=[Trigger(id="t37", name="Daily 8 AM", schedule=CronTrigger(hour=8))])
register_pipeline(id="sys-pm-recurring", name="System: PM Recurring", description="Create next-period PM items from recurring templates. Prevents duplicates.", tasks=[pm_recurring, notify_complete], triggers=[Trigger(id="t33", name="Sunday 4 AM", schedule=CronTrigger(day_of_week="sun", hour=4))])
register_pipeline(id="sys-ambient-poll", name="System: Ambient Poll", description="Take a snapshot of the user's current context -- calendar, Teams, Limitless. Writes JSON to data/ambient/.", tasks=[ambient_poll, notify_complete], triggers=[Trigger(id="t40", name="Every 30 min", schedule=IntervalTrigger(minutes=30))])
register_pipeline(id="sys-pm-wake", name="System: PM Wake Check", description="Check deferred PM items for wake conditions. Reactivates items whose due date has arrived.", tasks=[pm_wake, notify_complete], triggers=[Trigger(id="t39", name="Daily 6 AM", schedule=CronTrigger(hour=6))])
register_pipeline(id="sys-session-slicer", name="System: Session Slicer", description="Split Claude Code session JSONLs into sliding windows for better embedding and retrieval.", tasks=[session_slicer, notify_complete], triggers=[Trigger(id="t45", name="Every 10 min", schedule=IntervalTrigger(minutes=10))])
register_pipeline(id="sys-email-priority", name="System: Email Priority", description="Classify incoming emails by urgency tier for triage", tasks=[email_priority_scan, notify_complete], triggers=[Trigger(id="t38b", name="Weekdays 7 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=7))])

# -- Skills (fire run_skill event to events channel, orchestrator spawns subagent) --
register_pipeline(id="skill-morning-brief-archive", name="Skill: Brief Archive", description="Move yesterday's morning/EOD briefs into Daily Archive. Publishes new locations to Obsidian.", tasks=[trigger_morning_brief_daily_archive, notify_complete], triggers=[Trigger(id="t20", name="Daily 5:55 AM", schedule=CronTrigger(hour=5, minute=55))])
register_pipeline(id="skill-weekly-archive", name="Skill: Weekly Archive", description="Move last week's Weekly Dispatch into Weekly Archive.", tasks=[trigger_weekly_archive, notify_complete], triggers=[Trigger(id="t21", name="Monday 5:50 AM", schedule=CronTrigger(day_of_week="mon", hour=5, minute=50))])
register_pipeline(id="skill-morning-brief", name="Skill: Morning Brief", description="Generate the morning briefing. Pulls email, calendar, Teams, iMessage, PM, and web intel.", tasks=[trigger_morning_brief, notify_complete], triggers=[Trigger(id="t22", name="Weekdays 6 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=6))])
register_pipeline(id="skill-daily-agenda", name="Skill: Daily Agenda", description="Build today's chronological agenda with pre-meeting research for every meeting.", tasks=[trigger_daily_agenda, notify_complete], triggers=[Trigger(id="t23", name="Weekdays 6:05 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=6, minute=5))])
register_pipeline(id="skill-limitless-analysis", name="Skill: Limitless Analysis", description="Deep review of the day's Limitless lifelog recordings. Catches off-calendar conversations and extracts commitments.", tasks=[trigger_limitless_analysis, notify_complete], triggers=[Trigger(id="t36", name="Daily 10:30 PM", schedule=CronTrigger(hour=22, minute=30))])
register_pipeline(id="skill-pm-capture", name="Skill: PM Capture", description="Nightly sweep of meetings, email, Teams, and iMessage to extract commitments and tasks. Deduplicates against existing PM items.", tasks=[trigger_pm_capture, notify_complete], triggers=[Trigger(id="t35", name="Daily 10 PM", schedule=CronTrigger(hour=22))])
register_pipeline(id="skill-weekly-dispatch", name="Skill: Weekly Dispatch", description="Generate the Weekly Dispatch -- full week retrospective covering wins, commitments, open items, and next week preview.", tasks=[trigger_weekly_dispatch, notify_complete], triggers=[Trigger(id="t34", name="Friday 8 PM", schedule=CronTrigger(day_of_week="fri", hour=20))])
register_pipeline(id="skill-nightwatch", name="Skill: Nightwatch", description="Overnight autonomous work session. Loops picking the highest-leverage task each cycle -- operator work and architect work.", tasks=[trigger_nightwatch, notify_complete], triggers=[Trigger(id="t24", name="Daily 9 PM", schedule=CronTrigger(hour=21))])
register_pipeline(id="skill-ops-dashboard", name="Skill: Ops Dashboard", description="Generate operational status pages -- pipeline health, indexing coverage, memory system health, and capability inventory.", tasks=[trigger_ops_dashboard, notify_complete], triggers=[Trigger(id="t28", name="Every hour", schedule=IntervalTrigger(hours=1))])
register_pipeline(id="skill-intent-check", name="Skill: Intent Check", description="Scan recent data for violations of decisions, expectations, and org rules. Checks against the intent/decision graph.", tasks=[trigger_intent_check, notify_complete], triggers=[Trigger(id="t39b", name="Weekdays 7:30 AM", schedule=CronTrigger(day_of_week="mon-fri", hour=7, minute=30))])
register_pipeline(id="skill-pre-1on1-brief", name="Skill: Pre-1on1 Brief", description="On-demand pre-meeting brief for upcoming 1-on-1s. No automatic schedule -- trigger manually or via events channel.", tasks=[trigger_pre_1on1_brief, notify_complete], triggers=[])
register_pipeline(id="skill-monday-prep", name="Skill: Monday Prep", description="Friday Monday-prep automation -- compile status report, talking points, and risk areas for Monday leadership meeting.", tasks=[trigger_monday_prep, notify_complete], triggers=[Trigger(id="t42", name="Friday 5 PM", schedule=CronTrigger(day_of_week="fri", hour=17))])

app = get_app()
