# 📖 QA Bug Logger Bot — User Guide

## Getting Started

### Step 1: Get Your OpenProject API Key

1. Go to **https://project.intermesh.net/my/account**
2. Click **Access tokens** in the left sidebar
3. Click **+ API token** (or copy your existing token)
4. Copy the full token string

### Step 2: Register with the Bot

In the Google Chat space where the bot is added, type:

```
/register your_api_token_here
```

**Example:**
```
/register 15b9c97ba929dd4be122db8f7cef3e7c70e346460624e2200044b58782ad341b
```

The bot will verify your key and respond:
```
✅ Registration successful!

Your Details:
• Name: Manish Sharma1
• OpenProject ID: 2981
• Google Chat: Manish Sharma
• Registered: Yes ✅

🎉 You can now start reporting bugs!
```

### Step 3: Report a Bug

Simply send a message describing the bug. You can include:

- 📝 **Text description** — Describe what happened
- 📸 **Screenshots** — Attach images showing the bug
- 🎥 **Videos** — Attach screen recordings
- 🎤 **Voice notes** — Attach audio descriptions

---

## Bug Reporting Examples

### Example 1: Text Only

```
Login button not working on Samsung Galaxy S23.
Device: Samsung Galaxy S23
OS: Android 14
Environment: Stage
```

### Example 2: Text + Screenshot

```
The OTP screen is showing a blank white screen after entering phone number.
Device: iPhone 15 Pro
OS: iOS 17.2
```
*[Attach screenshot of the blank screen]*

### Example 3: Video Bug Report

```
App crashes when uploading a product image in seller dashboard.
```
*[Attach 10-second screen recording showing the crash]*

### Example 4: Quick Report

The AI is smart — even a short message works:

```
Payment page not loading on Redmi Note 12
```

The bot will automatically:
- Set **Project** → Android (detected from "Redmi")
- Set **Priority** → High (payment = critical)
- Set **Bug Type** → Functional/Logical
- Create proper **Steps to Reproduce**
- Format the **Title** professionally

---

## What the Bot Fills Automatically

| Field | How |
|-------|-----|
| **Title** | AI creates a concise, professional title |
| **Description** | Formatted with Actual/Expected Behavior, Steps, Environment |
| **Steps to Reproduce** | AI generates numbered steps |
| **Bug Type** | AI classifies: UI/UX, Functional, Network, Content, etc. |
| **Environment** | AI detects: STAGE or LIVE |
| **Project** | Auto-detected: Android or iOS |
| **Priority** | AI determines: High, Medium, or Low |

## What You Fill Manually (after ticket is created)

| Field | Why |
|-------|-----|
| **Category** | Only you know the exact feature area |
| **Assignee** | Team lead assigns to the right developer |
| **Accountable** | Set by QA lead |
| **Version** | Set to the current release version |

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/register <key>` | Register with OpenProject API key |
| `/status` | Check your registration status |

---

## Tips for Better Bug Reports

1. **Include device and OS** — "Samsung Galaxy S23, Android 14"
2. **Mention the environment** — "Stage" or "Live"
3. **Describe the exact behavior** — "Button doesn't respond" not "broken"
4. **Include app version** if known — "v13.3.7"
5. **Attach media** — Screenshots are worth a thousand words!
6. **One bug per message** — Don't combine multiple bugs

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "You are not registered" | Use `/register <api_key>` first |
| "Invalid API key" | Check your key at https://project.intermesh.net/my/account |
| Bot not responding | Make sure you @mention the bot in spaces |
| Ticket not created | Check the error message, verify your API key is still valid |
| Wrong project selected | Include "Android" or "iOS" in your message |

---

## FAQ

**Q: Can I update the ticket after creation?**
A: Yes! Click the ticket link, then edit fields in OpenProject.

**Q: Can I report multiple bugs at once?**
A: Send each bug as a separate message for best results.

**Q: What if the AI gets something wrong?**
A: Edit the ticket in OpenProject. The AI is ~95% accurate.

**Q: Is my API key stored securely?**
A: Yes, it's stored in an encrypted database and never logged.
