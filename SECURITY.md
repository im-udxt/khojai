# Security notes

This project runs on a home server and is published through a Cloudflare
tunnel, so the site is reachable by anyone who finds the address. These are the
choices made because of that, and the checklist to follow before going public.

## What is exposed and what is not

| Part | Reachable from the internet |
| --- | --- |
| Website on port 3000 | Yes, through the tunnel |
| Read only API on port 8080 | Yes, through the tunnel |
| Neo4j on 7474 and 7687 | No. Bound to 127.0.0.1 |
| Redis on 6379 | No. Bound to 127.0.0.1 |
| Ollama on 11434 | No. Runs on the host, containers reach it internally |

Point the tunnel at `localhost:3000` only. The site proxies the API calls it
needs. There is no reason to expose port 8080 separately.

## How the API is protected

- It only reads. There is no endpoint that writes, updates or deletes.
- Every query uses parameters. User input is never joined into a query string,
  so it cannot change what a query does.
- Text input is checked against a strict pattern, ids must be hexadecimal, and
  every numeric parameter has a minimum and maximum.
- Requests are counted per client address and refused past the limit.
  Cloudflare's real client header is used when present.
- Errors return a short message. Stack traces and internal details are logged
  on the server and never sent to the caller.
- API docs pages are turned off.
- Responses carry `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy` and a restrictive
  `Content-Security-Policy`.

## Containers

- The agents and API containers run as an unprivileged user, not root.
- No container mounts the Docker socket.
- No container needs extra kernel capabilities.
- Secrets come from `.env`, which is in `.gitignore` and never committed.

## Telegram

The bot is private. Every handler checks the sender against
`TELEGRAM_ALLOWED_USER_ID` and refuses anyone else. If that value is empty the
bot refuses to start rather than run open to the world.

## Before you make the site public

1. Set `ALLOWED_ORIGINS` in `.env` to your hostname, for example
   `https://khoj.example.com`. Leaving it as `*` lets any site call the API
   from a browser.
2. Change `NEO4J_PASSWORD` from the development value.
3. Rotate the Telegram bot token if it has ever been pasted into a chat, an
   issue or a commit. Tokens shared that way should be treated as public.
   BotFather can revoke and reissue with `/revoke`.
4. Turn on Cloudflare's bot protection and a rate limiting rule at the edge.
   The API limit is a backstop, not a substitute.
5. Check that `docker compose ps` shows database ports bound to `127.0.0.1`
   and not `0.0.0.0`.
6. Decide what should be visible. Everything in the graph came from public
   articles, but a page that gathers many facts about one person is different
   from those facts sitting on separate news sites.

## Reporting a problem

Open a private issue or contact the repository owner. Do not post details of a
live vulnerability in a public issue.
