# FXI Community Manager

FXI is being shifted from a private AI-chat bot to a Telegram group/channel management assistant.

## Current implementation on the development branch

- Private `/start` now explains how to add FXI to a group or channel; private free-form messages no longer trigger AI chat replies.
- Community message capture stores chat title/type, message count, recently observed member identity, and a bounded sample of recent text.
- Conservative anti-flood protection removes repeated rapid messages in groups when the bot has delete-message permission. Group administrators are exempt.
- Group rules: `/rules` and administrator-only `/setrules <text>`.
- Group activity summary: `/communitystats`.
- Administrator-only challenge publishing: `/challenge`.
- Administrator-only five-item idea list: `/suggest`.
- Reaction-count updates are recorded when Telegram delivers them; post records are ranked by total reactions.
- New-member welcome message is attempted when Telegram sends a chat-member update.
- Admin metrics expose observed communities, message counts, members seen, and tracked posts.

## Setup and Telegram permissions

1. Add the bot to the target group. Promote it to administrator and grant **Delete messages** for anti-flood moderation.
2. Add the bot to the target channel as administrator. Telegram channel post and reaction updates require appropriate channel access.
3. In BotFather, ensure group privacy settings are configured for the message visibility you intend. A bot with privacy mode enabled will not receive every ordinary group message; commands and replies are still subject to Telegram's rules.
4. The bot can only build its own history from updates received after it is added/configured. It cannot automatically download the group's old message history.
5. Reaction counts are only available for messages for which Telegram sends reaction-count updates. A bot cannot see private identities of people who reacted unless Telegram explicitly provides those details.

## Commands

| Command | Purpose |
|---|---|
| `/community` | Community feature guide |
| `/rules` | Show group rules |
| `/setrules <text>` | Change rules (group administrator only) |
| `/communitystats` | Show observed activity totals |
| `/challenge` | Publish a group challenge (administrator only) |
| `/suggest` | Produce five content/community ideas (administrator only) |

## Known limitations / next integration work

- The five suggestions currently use locally collected group activity and engagement records. The fifth item is a news-research prompt, **not** a live news result. A verified news/RSS provider must be connected before claiming real-time world-news recommendations.
- Reaction totals do not equal unique people or quality; the current ranking is a simple engagement signal.
- The current community state uses the existing bot-state persistence layer. For high-volume communities, move message/event history into dedicated PostgreSQL tables with retention and per-chat controls.
- Add configurable moderation thresholds, allowlists, warning/ban escalation, link policy, join-request review, polls, scheduled posts, and full dashboard workflows before calling this production-complete.
- Admin-only commands currently rely on Telegram group administrator status or configured FXI admin IDs.
- Do not enable automatic bans or mass deletions without explicit per-community policy and admin controls.
