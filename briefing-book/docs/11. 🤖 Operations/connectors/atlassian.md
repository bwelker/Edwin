---
type: connector-docs
connector: atlassian
---

# Atlassian Connector

Syncs Bitbucket repositories/PRs, Jira issues, and Confluence pages.

## Quick Setup

Requires separate credentials for Bitbucket (app password) and Jira/Confluence (API token).

### 1. Bitbucket Credentials

1. Go to [Bitbucket](https://bitbucket.org/) > Personal Settings > App Passwords
2. Create an app password with read access to repositories and pull requests

### 2. Jira/Confluence Credentials

1. Go to [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Create an API token

### 3. Store Credentials

Create `~/.edwin/credentials/atlassian/env`:
```bash
ATLASSIAN_EMAIL=your-email@company.com
ATLASSIAN_API_TOKEN=your-jira-confluence-api-token
ATLASSIAN_SITE=yoursite.atlassian.net
```

Create `~/.edwin/credentials/bitbucket/env`:
```bash
BITBUCKET_USERNAME=your-bitbucket-username
BITBUCKET_APP_PASSWORD=your-app-password
BITBUCKET_WORKSPACE=your-workspace-slug
```

Or add all of these to `~/Edwin/.env`.

### 4. Verify

```bash
./connectors/atlassian/atlassian status
```

## What It Captures

- **Bitbucket**: Repository listings, pull requests (title, author, reviewers, status, comments)
- **Jira**: Issues with full details (summary, description, status, assignee, comments, custom fields)
- **Confluence**: Pages with content (title, space, body text, labels)

## How It Works

- Bitbucket: REST v2 API with Basic auth (username + app password)
- Jira: REST v3 API with Basic auth (email + API token)
- Confluence: REST v2 API with Basic auth (email + API token)
- Rate limiting with exponential backoff and 429/5xx retry
- HTML content stripped to plain text for markdown output
- Incremental sync based on modification timestamps

## Output Format

```
~/Edwin/data/atlassian/
  bitbucket/
    {workspace}/
      {repo}/
        pulls/
          {pr-id}.md
  jira/
    {project}/
      {issue-key}.md
  confluence/
    {space}/
      {page-title}.md
```

## Cadence

- Bitbucket: every 2 hours
- Jira: every 4 hours
- Confluence: every 8 hours
