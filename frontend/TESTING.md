# Talos — Manual Testing Guide

How to test every integrated feature end-to-end.

## 0. Prerequisites

**Start the stack** (from repo root `D:\gp_artifact`):

```powershell
docker compose up -d          # app, postgres, redis, minio
cd frontend; npm run dev      # Vite on http://localhost:5173
```

Open **http://localhost:5173** in the browser. (Vite proxies `/api`, `/auth`, `/socket.io` → `:8000`.)

**Test accounts** (already seeded):

| User | Password | State |
|------|----------|-------|
| `tester` | `TestPassw0rd123` | Owner of "Talos Workspace" (channels #general, #random), 6 messages, 5 documents |
| `newbie` | `NewbiePass123456` | 0 workspaces — use for onboarding + cross-user demo |

For **realtime / cross-user** tests you need two sessions at once: use a normal window for `tester` and an **incognito/private** window for `newbie`.

---

## 1. Signup (two-step, email-verified)

1. Log out if signed in. Go to `/signup`.
2. Fill name, username, email (use a **real inbox** you control, or reuse a Gmail alias), password (**≥12 chars**). Click **Create account**.
   - ✅ Button enables once fields are valid; on submit you see a **"Check your email"** screen with a Resend option.
3. Open the verification email (Subject: *Verify your Talos account*) and click the link → opens `/signup/complete?token=...`.
   - ✅ Shows **"Verifying your email…"** then auto-redirects to `/onboarding` (it does **not** re-ask for your details).

> No SMTP inbox handy? The link is also printed to the app logs:
> ```powershell
> docker compose logs --tail=40 app | Select-String "signup/complete"
> ```
> Paste that URL into the browser to continue.

---

## 2. Login

1. Go to `/login`, enter `tester` / `TestPassw0rd123`.
   - ✅ Redirects into the app (`/chat`). Top-left shows the workspace; sidebar lists channels.
2. Reload the page.
   - ✅ You stay logged in (Bearer token persisted in localStorage as `talos_token`).

---

## 3. Onboarding (create first workspace)

1. Log in as `newbie` / `NewbiePass123456` (incognito window).
   - ✅ Lands directly on `/onboarding` (because newbie owns 0 workspaces).
2. Enter a workspace name (e.g. "Newbie HQ"), submit.
   - ✅ Redirects to `/chat`; **#general** and **#random** channels exist automatically; you can send a message immediately.

---

## 4. Chat — messaging + realtime

Signed in as `tester`, on `/chat`:

1. Select **#general**, type a message, press **Enter**.
   - ✅ Message appears instantly (optimistic), then confirms.
2. **Formatting toolbar:** select text and click **Bold**/**Code**, or use markdown (`**x**`, `` `x` ``).
   - ✅ Rendered formatting shows in the sent message.
3. **Search:** click the 🔍 icon in the header, type a word.
   - ✅ Filters to matching messages and shows a match count; **Esc** or ✕ closes it.
4. **Realtime (two windows):** keep `tester` on #general; in the incognito `newbie` window join the **same** workspace/channel (see §6 to share it first). Send from one window.
   - ✅ The message appears in the **other** window within a second without reload (Socket.IO broadcast).

---

## 5. Chat — Members popover (live presence)

Signed in as `tester`, on `/chat`:

1. Click the **Users** (people) icon in the channel header.
   - ✅ Popover lists **real** workspace members (name + initials), not a hardcoded list.
   - ✅ The workspace **Owner** is labeled; anyone currently connected shows a **green online dot** + "Online".
2. Open a second window as another member of that workspace → the owner's popover shows them as online.

---

## 6. Workspace members (Settings → Workspace) — owner only

Signed in as `tester` (the owner), go to **Settings → Workspace** tab:

1. ✅ Members list loads from the server (`GET /workspaces/{id}/members`), owner has an amber **Owner** chip.
2. **Add a member:** click **Add member**, enter `newbie` (username) **or** newbie's email → **Add**.
   - ✅ Snackbar "Member added"; `newbie` appears in the list.
   - ✅ Bad name → inline error "No user found…"; adding an existing member → "already a member".
3. **Remove a member:** click **Remove** next to `newbie`.
   - ✅ Snackbar "Member removed"; row disappears. The **Owner row has no Remove button** (owner can't be removed).
4. Log in as `newbie` after being added → the shared **"Talos Workspace"** now shows in their sidebar and they can chat in it.
5. Sign in as a **non-owner** member and open this tab → ✅ no Add/Remove controls; note reads "Only the workspace owner can add or remove members."

---

## 7. Access & permissions (Settings → Access)

Signed in as `tester`, go to **Settings → Access** tab:

- ✅ Lists your **effective permissions** for the active workspace, fetched from `GET /workspaces/{id}/my_permissions` — e.g. `workspace:view`, `channel.message:send`, `files:read`, `files:write`, `files:create`, each with an **any/own** scope chip.
- ✅ Owner sees an **Owner** chip. (This replaces the old "not available in this build" placeholder.)

---

## 8. Documents (upload / download / delete)

Signed in as `tester`, go to **Documents**:

1. ✅ Grid/list shows the 5 seeded documents with type + status.
2. **Upload:** drag a file onto the page (or click **Upload**). Pick a small PDF/TXT.
   - ✅ Snackbar "Uploading… / Uploaded 1 file(s)"; the new file appears in the list (auto-reloads).
3. **Download:** open a document → **Download**.
   - ✅ Browser saves the file with its original filename; contents match what was uploaded.
4. **Delete:** delete a document.
   - ✅ It disappears from the list.
5. **View toggle / filter / search:** switch grid⇄list, filter by type, search by name.
   - ✅ List updates accordingly.

---

## 9. Security (Settings → Security)

Signed in as `tester`, go to **Settings → Security**:

1. **Change password** (Profile tab): enter current + new (≥8) + confirm → **Update password**.
   - ✅ Success snackbar; log out and back in with the new password. *(Reset it back to `TestPassw0rd123` if you want to keep the seed valid.)*
2. **Active sessions:** click **Load sessions**, enter your password.
   - ✅ Lists devices/sessions; **View** shows details; **Revoke** / **Sign out of all other devices** work (each asks for your password).
3. **Two-factor (TOTP):** toggle **2FA on** → confirm password → scan the QR with an authenticator app → enter the 6-digit code → **Enable**.
   - ✅ "Two-factor authentication enabled". Toggling off disables it.
4. **Passkeys:** **Add passkey** → password + name → follow the browser prompt.
   - ✅ "Passkey registered". *(Needs a platform authenticator / security key; works over `localhost`.)*
5. **Connected accounts:** Google / GitHub **Connect** buttons kick off the OAuth redirect.

---

## 10. Full cross-user end-to-end (the money test)

1. Window A: `tester` → **Settings → Workspace → Add member** → `newbie`.
2. Window B (incognito): log in as `newbie` → open **Talos Workspace → #general**.
3. Send a message from A → ✅ appears live in B (and vice-versa).
4. In A, open the **Members** popover → ✅ `newbie` shows as **online** (green dot).
5. In A, **Settings → Workspace → Remove** `newbie` → ✅ newbie loses access to that workspace.

---

## 11. API-level smoke test (optional, no UI)

Verifies the backend routes the UI depends on. Run from PowerShell:

```powershell
# 1) Login -> capture Bearer token from the X-Session-Token header
$form = @{ username = 'tester'; password = 'TestPassw0rd123' }
$resp = Invoke-WebRequest -Uri 'http://localhost:8000/api/auth/password/' -Method Post -Body $form -UseBasicParsing
$tok  = $resp.Headers['X-Session-Token']
$H    = @{ Authorization = "Bearer $tok" }

# 2) Workspaces + members + my permissions
$ws  = (Invoke-RestMethod 'http://localhost:8000/api/workspaces' -Headers $H)[0]
Invoke-RestMethod "http://localhost:8000/api/workspaces/$($ws.id)/members"        -Headers $H
Invoke-RestMethod "http://localhost:8000/api/workspaces/$($ws.id)/my_permissions" -Headers $H

# 3) Documents (list)
Invoke-RestMethod "http://localhost:8000/api/workspaces/$($ws.id)/files/m" -Headers $H
```

- ✅ Login returns a token; members returns `[{id,username,name,email,is_owner}]`; my_permissions returns a list of `{resource,action,scope}`; files/m returns the document list.

---

## Troubleshooting

- **401 everywhere / kicked to login** → the Bearer token wasn't captured. Hard-reload; check `localStorage.talos_token` exists in DevTools.
- **Realtime not delivering** → confirm the Socket.IO handshake in DevTools → Network → `socket.io` (status 101). Both users must be **members** of the same workspace.
- **Upload/download fails** → check MinIO is healthy (`docker compose ps`) and the app was restarted after seeding perms (`docker compose restart app`).
- **`GET http://localhost:8000/` → 500** → cosmetic (backend root reads a template not in the image); the SPA is served by Vite on `:5173`, ignore it.
