# Remote Work Protocol

**Project:** CarAutopsy  
**Version:** v1.00  
**Status:** Active working rule  
**Owner:** @realarchitekt

## Purpose

This protocol allows CarAutopsy development to continue when the owner only has browser access to GitHub.

## Allowed Tools

- GitHub web file editor
- GitHub Issues
- GitHub Projects
- GitHub Pull Requests
- GitHub Actions
- GitHub Codespaces, if available
- Vercel / Cloudflare Pages browser deployment, if connected later

## Not Required

- Local Git
- Local npm
- Local Python
- SSH keys on the current machine
- Administrator access

## Workflow

1. Create or edit files through GitHub web.
2. Use GitHub Actions for validation, scripts, builds, and repository maintenance.
3. Store decisions in `docs/`.
4. Store session state in `.carautopsy/sessions/`.
5. Use Issues for bounded tasks.
6. Do not rely on chat memory as the source of truth.

## Safety Rules

- Do not add secrets to the repository.
- Do not paste API keys into Issues, Actions logs, or docs.
- Do not run paid APIs without owner approval.
- Do not activate scheduled crawling without source-policy review.
- Do not claim a test passed unless the GitHub Actions result was inspected.

## Current Principle

GitHub Actions is the remote computer. The office PC is only a browser terminal.
