# Welcome to Edwin

You just finished setup. I have your preferences, your connectors are starting to sync, and I'm already building context about your world. Here's how everything works.

## The Briefing Book

This folder structure you're looking at -- that's the briefing book. It's my working memory, organized the way a good chief of staff would organize a principal's desk. You don't need to maintain it. I populate it automatically as I work.

Over the next few hours, as connectors sync your email, calendar, messages, and meeting transcripts, you'll see files appear. Within a day or two, the briefing book will be a rich, searchable view of your work life.

### What goes where

**Briefs** -- Summaries I write for you. Morning briefs, weekly rollups, situation reports when something important happens. These are your "what do I need to know right now" section.

**Calendar** -- Your upcoming schedule, meeting prep notes, post-meeting summaries with action items extracted. I pull from your connected calendars and enrich entries with context.

**Action Tracker** -- Commitments, tasks, and follow-ups. When someone says "I'll send that by Friday" in a meeting, it lands here. When you tell me to do something, it lands here. I track what you owe others, what others owe you, and what I owe you.

**Drafts** -- Email replies, messages, reports, and documents I've prepared for your review. I draft, you decide whether to send.

**Overnight** -- Work I did while you were sleeping. Research, data processing, maintenance logs. Check this in the morning if you're curious what happened.

**Research** -- Deep dives on topics you've asked about or that I've flagged as relevant. Competitor analysis, vendor evaluations, technical research.

**Projects** -- Active project tracking. Status, blockers, decisions, timelines.

**Products** -- Product-specific information if you work in product development.

**People** -- Profiles of key people in your world. Communication patterns, recent interactions, relationship context.

**Daytime Log** -- Running log of what I'm doing during the day. Tasks completed, decisions made, things I noticed.

**Operations** -- System health. Connector status, pipeline metrics, error logs. The "is everything working" section.

## How to Talk to Me

If you're in the terminal, you're already here -- just type. If you set up Telegram during onboarding, you can message me there from your phone anytime.

There's no special syntax. Talk to me like you'd talk to a sharp colleague who knows your context. Some examples:

- "What's on my calendar today?"
- "Any urgent emails?"
- "What did I miss in the last 3 hours?"
- "Draft a reply to Jason's email -- tell him we'll have the numbers by Thursday"
- "What do we know about [company/person/topic]?"
- "Remind me to follow up with Sarah next Tuesday"
- "Research X and put a summary in my briefing book"
- "What's the status of [project]?"

I'll figure out what you need and either do it immediately or draft something for your approval, depending on the autonomy levels we set up.

## The Daily Rhythm

Here's what a typical day looks like once everything is running:

**Morning** -- Your morning brief arrives (if you enabled it). It covers what's on your calendar, what happened overnight, any urgent items, and commitments due today. Check the briefing book for the full version, or just ask me for a summary.

**During the day** -- Connectors sync in the background on cadence. Email every 15-60 minutes, calendar updates, messages, meeting transcripts after calls end. I'm processing all of it -- extracting action items, updating the knowledge graph, flagging things that need your attention.

**When you need something** -- Just ask. I have context from your email, calendar, messages, meetings, and everything we've discussed. The more connectors you have running, the more I can see.

**Overnight** -- If you enabled overnight autonomy, I work while you sleep. Research tasks, data cleanup, briefing book updates, anything in my queue that doesn't need your input.

## The Plombery Dashboard

Open `localhost:8899` in your browser. That's Plombery -- my scheduler. It shows:

- Every connector and when it last ran
- Scheduled skills (morning brief, overnight work, weekly summary)
- Run history and any errors
- Manual trigger buttons if you want to force a sync

You don't need to check it regularly. It's there when you want to see what's running or troubleshoot why something hasn't updated. If a connector fails, I'll usually notice and tell you -- but the dashboard gives you the full picture.

## Skills

Skills are recurring tasks I run automatically. The ones you enabled during setup are already scheduled. Common skills include:

- **Morning brief** -- Compiles your day ahead: calendar, priorities, overnight activity, commitments due
- **Overnight work** -- Autonomous research and maintenance while you sleep
- **Weekly summary** -- End-of-week rollup of what happened, what's pending, what needs attention
- **Ops dashboard** -- System health check that writes status pages to the briefing book

You can also trigger skills manually by asking me: "run the morning brief" or "do an ops check."

## Giving Me Tasks

Just tell me what you need. I'll either do it immediately (Level 1 autonomy) or draft it for your approval (Level 2).

Some things I handle without asking:
- Reading email, calendar, messages
- Organizing the briefing book
- Tracking action items and commitments
- Research and lookups
- Updating my own memory

Some things I draft for you first:
- Replies to messages on your behalf
- Calendar changes
- Reports and summaries meant for other people

Some things I always ask about first:
- Sending messages as you
- Deleting anything
- Sharing data externally
- Anything involving money or access

These defaults come from your setup conversation. You can adjust them anytime -- just tell me to move something between levels.

## One More Thing

I get better over time. Right now my memory is thin -- connectors just started syncing and I'm building context from scratch. Give it a few days. As email, calendar, meetings, and messages flow in, I'll develop a richer understanding of your work, your people, and your priorities.

If something feels off or I'm missing context, tell me. I learn from corrections, and I remember them.
