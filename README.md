# Winning Team — Bot + Website

Drop-in replacement for your existing bot folder on justrunmy.app.

## What's inside
- `main.py` — your Telegram bot (unchanged features) + now also:
  - launches the Flask website on `PORT` (default 8080)
  - rotates the site password once a day at midnight **Dallas time (America/Chicago)**
  - edits the channel post at `t.me/c/1192930889/610` with the new password + site link
- `webapp.py` — Flask website (login gate, categories, product pages, media proxy)
- `password_manager.py` — password rotation + channel post editor
- `templates/`, `static/` — the redesigned pages with your logo
- `inventory.db` — your product database (shared with the bot)
- `requirements.txt`, `start.sh` — same entry point as before

## Environment variables
- `BOT_TOKEN` — your Telegram bot token (already defaults to your existing one)
- `PORT` — port the website listens on (justrunmy.app sets this automatically)
- `SITE_URL` — public URL used in the channel post (default `https://justrunmy.app`)
- `FLASK_SECRET` — set this to any long random string for session cookie security

## Channel post format
```
Affiliate Marketing Website
<blockquote>
With our website you can show products to your friends and family who are not in our menu!

Prices are not listed. We encourage everyone to take advantage and make money!💰
</blockquote>

🔗 https://justrunmy.app

PASSWORD: XXXX-XXXX-XXXX

PASSWORD CHANGES EVERY 24 HOURS!
```

The bot must be an **admin** in the channel `-1001192930889` with permission to
edit messages, otherwise editing post 610 will fail (you'll see the error in
the logs but the site will still work).

## Deploy
Zip the whole folder and drag-and-drop to justrunmy.app. The existing
`start.sh` runs `main.py`, which now also serves the website.
